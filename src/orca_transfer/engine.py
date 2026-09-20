"""Offline, non-destructive transfer of supported editable Orca/Bambu 3MFs."""
from __future__ import annotations

from dataclasses import dataclass
import copy
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
import zipfile

from .geometry import GeometryError, check_fit, local_name, xml_document
from .profiles import PrinterProfile, SAFE_CONNECTION_KEYS, CONNECTION_KEYS as PROFILE_CONNECTION_KEYS

SCHEMA = json.loads(Path(__file__).with_name('schema.json').read_text(encoding='utf-8'))
PRINTER_KEYS = set(SCHEMA['printer_keys'])
FILAMENT_KEYS = set(SCHEMA['filament_keys'])
PROCESS_KEYS = set(SCHEMA['process_keys'])
VARIANT_KEYS = set(SCHEMA['filament_variant_keys'])
CONFIG = 'metadata/project_settings.config'
PLATES = ('Cool Plate', 'Engineering Plate', 'High Temp Plate', 'Textured PEI Plate',
          'Textured Cool Plate', 'Supertack Plate')
CONNECTION_KEYS = {
    'host_type', 'print_host', 'print_host_webui', 'bbl_use_printhost', 'printer_agent',
    'flashforge_serial_number', 'physical_printer_settings_id', 'printer_uuid',
    'device_id', 'dev_id', 'access_code', 'ip_address', 'user_id', 'account_id',
    'setting_id', 'base_id', 'sync_info', 'updated_time', 'bed_custom_texture',
    'bed_custom_model', 'printer_notes',
}
IDENTITY = {'inherits', 'inherits_group', 'different_settings_to_system',
            'compatible_machine_expression_group', 'compatible_process_expression_group',
            'compatible_printers', 'compatible_printers_condition', 'compatible_prints',
            'compatible_prints_condition', 'print_compatible_printers', 'printer_settings_id'}
ASSIGNMENTS = {'extruder', 'support_filament', 'support_interface_filament', 'wall_filament',
               'sparse_infill_filament', 'solid_infill_filament', 'wipe_tower_filament',
               'outer_wall_filament_id', 'inner_wall_filament_id', 'sparse_infill_filament_id',
               'internal_solid_filament_id', 'top_surface_filament_id', 'bottom_surface_filament_id'}
MAX_COMPRESSED = 512 * 1024 * 1024
MAX_EXPANDED = 2 * 1024 * 1024 * 1024
MAX_METADATA = 16 * 1024 * 1024


class ConversionError(ValueError):
    """An unsupported or inconsistent project, reported without changing input."""


@dataclass(frozen=True)
class ConversionResult:
    path: Path
    warnings: tuple[str, ...]
    changed_settings: tuple[str, ...]


def _private(key):
    key = key.casefold()
    if key in SAFE_CONNECTION_KEYS:
        return False
    return (key in CONNECTION_KEYS or key in PROFILE_CONNECTION_KEYS or key.startswith('printhost_') or
            any(term in key for term in ('password', 'api_key', 'apikey', 'access_token', 'auth_token', 'credential')))


def _plate(value):
    value = str(value).strip()
    if value.isdigit():
        idx = int(value)
        return PLATES[idx-1] if 1 <= idx <= len(PLATES) else None
    if value == 'SuperTack Plate':
        value = 'Supertack Plate'
    return value if value in PLATES else None


def default_plate_type(profile: PrinterProfile) -> str | None:
    """Use only an explicit profile default; never a universal printer guess."""
    return _plate(profile.settings.get('default_bed_type', ''))


def available_plate_types(profile: PrinterProfile) -> list[str]:
    """Orca's selectable plate vocabulary, not a physical compatibility claim."""
    default = default_plate_type(profile)
    return ([default] if default else []) + [p for p in PLATES if p != default]


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ConversionError('Duplicate keys in project JSON.')
        result[key] = value
    return result


def _json(data):
    try:
        value = json.loads(data.decode('utf-8-sig'), object_pairs_hook=_unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (UnicodeError, ValueError) as exc:
        raise ConversionError('Malformed project settings JSON.') from exc
    if not isinstance(value, dict):
        raise ConversionError('Project settings must be a JSON object.')
    return value


def _index(archive):
    entries = {}
    total = 0
    for info in archive.infolist():
        name = info.filename
        if '\\' in name or ':' in name or name.startswith('/') or '..' in PurePosixPath(name).parts or '\x00' in name:
            raise ConversionError('The archive contains unsafe entry paths.')
        key = name.casefold()
        if key in entries:
            raise ConversionError('The archive contains duplicate or case-colliding entries.')
        if info.flag_bits & 1 or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise ConversionError('Encrypted or unusually compressed 3MF files are unsupported.')
        if (info.external_attr >> 16) & 0o170000 == 0o120000:
            raise ConversionError('Symbolic links inside projects are unsupported.')
        total += info.file_size
        if total > MAX_EXPANDED or len(entries) >= 10000:
            raise ConversionError('The project exceeds the 2 GB expanded / 10,000-entry limit.')
        entries[key] = info
    return entries


def _read(archive, info):
    if info.file_size > MAX_METADATA:
        raise ConversionError('Project metadata exceeds the 16 MB inspection limit.')
    return archive.read(info)


def _positive(value, field):
    try:
        value = float(value)
        if not math.isfinite(value) or value <= 0:
            raise ValueError()
        return value
    except (TypeError, ValueError) as exc:
        raise ConversionError('Invalid positive number in ' + field + '.') from exc


def _single_nozzle(settings, label):
    if str(settings.get('printer_technology', 'FFF')).upper() != 'FFF':
        raise ConversionError(label + ': resin/SLA printer profiles are unsupported.')
    nozzles = settings.get('nozzle_diameter')
    if not isinstance(nozzles, list) or len(nozzles) != 1:
        raise ConversionError(label + ': only one physical nozzle is supported. IDEX, tool changers and multi-nozzle projects need manual transfer.')
    diameter = _positive(nozzles[0], 'nozzle_diameter')
    for field, default in (('printer_extruder_id', '1'), ('physical_extruder_map', '0')):
        values = settings.get(field, [default])
        if not isinstance(values, list) or not values or any(str(x) != default for x in values):
            raise ConversionError(label + ': unsupported physical extruder mapping.')
    if str(settings.get('support_parallel_printheads', '0')).lower() in ('1', 'true'):
        raise ConversionError(label + ': parallel printheads are unsupported.')
    return diameter


def _logical_slots(config):
    colors = config.get('filament_colour')
    if not isinstance(colors, list) or not 1 <= len(colors) <= 256:
        raise ConversionError('The project must contain 1–256 logical filament colors.')
    count = len(colors)
    for key in ('filament_type', 'filament_settings_id'):
        if not isinstance(config.get(key), list) or len(config[key]) != count:
            raise ConversionError(key + ' must match logical material slots, not extruder variants. Save the project in Orca first.')
    indices = config.get('filament_self_index', [str(i+1) for i in range(count)])
    if not isinstance(indices, list):
        raise ConversionError('Invalid filament_self_index vector.')
    try:
        ids = [int(i) for i in indices]
        if any(str(a) != str(b) for a,b in zip(ids, indices)) or set(ids) != set(range(1, count+1)) or ids != sorted(ids):
            raise ValueError()
    except (ValueError, TypeError) as exc:
        raise ConversionError('Material variant indices must be grouped logical slots numbered from one.') from exc
    variants = config.get('filament_extruder_variant', ['Direct Drive Standard'] * count)
    if not isinstance(variants, list) or len(variants) != len(ids):
        raise ConversionError('Material variant names and logical-slot indices disagree.')
    for key in VARIANT_KEYS & config.keys():
        if not isinstance(config[key], list) or len(config[key]) != len(ids):
            raise ConversionError('The ' + key + ' vector does not match the material variant layout. Save the project in Orca first.')
    return count, ids, variants


def _assignment(value, count):
    try:
        values = value if isinstance(value, list) else [value]
        if any(float(x) != int(float(x)) or not 0 <= int(float(x)) <= count for x in values):
            raise ValueError()
    except (TypeError, ValueError, OverflowError) as exc:
        raise ConversionError('An object/process material assignment references an unavailable logical filament slot.') from exc


def _configuration(source, profile, plate, warnings):
    required = {'printer_settings_id', 'print_settings_id', 'layer_height', 'machine_start_gcode'}
    if not required <= source.keys():
        raise ConversionError('Choose a full editable Orca/Bambu project with process and printer settings; geometry-only 3MF files are unsupported.')
    target = profile.settings
    source_diameter = _single_nozzle(source, 'Source project')
    target_diameter = _single_nozzle(target, 'Target profile')
    count, indices, variants = _logical_slots(source)
    if source_diameter != target_diameter:
        raise ConversionError('Source and target nozzle diameters differ. Retuning line widths, layers and material flow is outside a settings-preserving transfer.')
    layer = _positive(source['layer_height'], 'layer_height')
    maximum = target.get('max_layer_height', [str(target_diameter * .8)])
    minimum = target.get('min_layer_height', ['0'])
    try:
        max_height = float(maximum[0]) or target_diameter * .8
        min_height = float(minimum[0])
        if not math.isfinite(max_height) or not math.isfinite(min_height) or layer > max_height or layer < min_height:
            raise ConversionError('Source layer height is outside the target profile’s layer-height range.')
    except (ValueError, TypeError, IndexError) as exc:
        if isinstance(exc, ConversionError):
            raise
        raise ConversionError('Invalid target layer-height limits.') from exc
    selected = plate or default_plate_type(profile)
    if selected not in PLATES:
        raise ConversionError('This profile has no recognized default plate. Select the plate fitted to the target printer explicitly.')
    target_variants = target.get('printer_extruder_variant')
    layout = target.get('extruder_variant_list')
    if layout is not None:
        # Orca expands the comma-separated variant list for each physical nozzle
        # in PrintConfig.cpp::extend_extruder_variant. It is not a material list.
        if not isinstance(layout, list) or len(layout) != 1 or not isinstance(layout[0], str):
            raise ConversionError('Unsupported target physical-nozzle variant layout.')
        expanded = [item.strip() for item in layout[0].split(',')]
        if target_variants is not None and target_variants != expanded:
            raise ConversionError('The target printer has inconsistent extruder variant declarations. Re-save its variant layout in Orca before transferring.')
        target_variants = expanded
    if target_variants is None:
        target_variants = ['Direct Drive Standard']
    if not isinstance(target_variants, list) or not target_variants or any(not isinstance(v, str) or not v for v in target_variants) or len(set(target_variants)) != len(target_variants):
        raise ConversionError('Invalid target printer extruder variants.')
    for slot in range(1, count+1):
        available = {v for i,v in zip(indices, variants) if i == slot}
        if not set(target_variants) <= available:
            raise ConversionError('A target extruder variant has no matching source material tuning. Standard/High Flow/Bowden variants cannot be invented without retuning.')
    for key in ASSIGNMENTS & source.keys():
        _assignment(source[key], count)
    maps = source.get('filament_map', ['1'] * count)
    if not isinstance(maps, list) or any(str(v) != '1' for v in maps):
        raise ConversionError('The source uses an unsupported physical nozzle assignment.')
    if any(str(v) != '1' for v in source.get('print_extruder_id', ['1'])):
        raise ConversionError('The source process references another physical nozzle.')
    unknown_hardware = {k for k in source if k not in SCHEMA['option_types'] and
                        k.startswith(('machine_', 'printer_', 'nozzle_', 'extruder_')) and
                        k not in {'printer_settings_id'}}
    if unknown_hardware:
        raise ConversionError('This project uses hardware settings newer than the supported Orca 2.4.1 schema: ' + ', '.join(sorted(unknown_hardware)))
    unknown_target = {k for k in target if k not in PRINTER_KEYS and k not in
                      {'name','inherits','printer_settings_id','type','from','instantiation','version','vendor','setting_id','base_id','user_id','updated_time','sync_info','description','alias','renamed_from'} and not _private(k)}
    if unknown_target:
        raise ConversionError('The target has unrecognized printer settings: ' + ', '.join(sorted(unknown_target)) + '. Update this tool before transferring.')
    result = copy.deepcopy(source)
    for key in list(result):
        if key in PRINTER_KEYS or key in IDENTITY or _private(key):
            del result[key]
    for key in PRINTER_KEYS & target.keys():
        if not _private(key) and key != 'inherits':
            result[key] = copy.deepcopy(target[key])
    result['printer_settings_id'] = profile.name
    parent = target.get('inherits', '')
    result['inherits_group'] = [''] * (count+1) + [parent]
    result['compatible_machine_expression_group'] = [''] * (count+2)
    result['compatible_process_expression_group'] = [''] * count
    result['print_compatible_printers'] = list(dict.fromkeys([profile.name, *([parent] if parent else [])]))
    # Mark every copied source process/material option as explicit, so a same-name
    # installed preset cannot silently refresh them from its unrelated parent.
    result['different_settings_to_system'] = [
        ';'.join(sorted(PROCESS_KEYS & result.keys())),
        *[';'.join(sorted(FILAMENT_KEYS & result.keys()))] * count,
        ';'.join(sorted((PRINTER_KEYS & result.keys()) - {'inherits'})),
    ]
    result['curr_bed_type'] = selected
    # These are project-level hardware selectors, not logical material indices.
    # Retain the material variant table but select the target's default hardware.
    result['nozzle_volume_type'] = copy.deepcopy(target.get('default_nozzle_volume_type', ['Standard']))
    result['printer_extruder_id'] = ['1'] * len(target_variants)
    result['printer_extruder_variant'] = copy.deepcopy(target_variants)
    result['print_extruder_id'] = ['1'] * len(target_variants)
    result['print_extruder_variant'] = copy.deepcopy(target_variants)
    result['filament_map'] = ['1'] * count
    result.pop('extruder_ams_count', None)
    if count > 1:
        warnings.append('Logical material slots and painting are preserved. Verify your printer’s manual/automatic material-change capability and purge behavior in Orca.')
    if len(indices) > count:
        warnings.append('Standard/High Flow tuning variants were preserved separately from logical material slots.')
    warnings.append('Review plate temperatures, flow, retraction, supports, brims and custom material/process G-code in Orca before slicing. A profile transfer is not print validation.')
    return result, count


def _discard(name):
    return (name.endswith(('.gcode', '.gcode.md5', '.gcode.sha256', '.bgcode')) or
            name == 'metadata/slice_info.config' or
            bool(re.fullmatch(r'metadata/plate_\d+\.json', name)))


def _metadata(data, plate, count):
    root = xml_document(data)
    plates = [element for element in root.iter() if local_name(element.tag) == 'plate']
    if len(plates) > 1:
        raise ConversionError('Multi-plate layouts are not supported yet. Export one editable plate/project at a time from Orca.')
    changed = False
    derived = {'gcode_file', 'slice_valid', 'slice_prediction', 'slice_weight', 'outside', 'first_layer_time',
               'nozzle_diameter', 'printer_model', 'nozzle_volume'}
    for parent in root.iter():
        for node in list(parent):
            key = node.get('key', node.get('opt_key', ''))
            if key in ASSIGNMENTS:
                _assignment(node.get('value', node.text), count)
            if _private(key) or local_name(parent.tag) == 'plate' and key in derived:
                parent.remove(node)
                changed = True
            elif local_name(parent.tag) == 'plate' and key == 'bed_type':
                node.set('value', plate)
                changed = True
            elif local_name(parent.tag) == 'plate' and key == 'filament_maps':
                values = node.get('value', '').replace(';', ' ').replace(',', ' ').split()
                if any(v != '1' for v in values):
                    raise ConversionError('A plate maps material to an unsupported physical nozzle.')
            elif key in PRINTER_KEYS:
                raise ConversionError('A local object/plate override contains printer hardware settings. Open and resolve the override in Orca first.')
    return ET.tostring(root, encoding='utf-8', xml_declaration=True) if changed else data


def _references(data, removed):
    root = xml_document(data)
    changed = False
    for parent in root.iter():
        for node in list(parent):
            target = node.get('Target', node.get('PartName', '')).lstrip('/').casefold()
            if target in removed or any(target.endswith('/'+n) or n.endswith('/'+target) for n in removed if target):
                parent.remove(node)
                changed = True
    return ET.tostring(root, encoding='utf-8', xml_declaration=True) if changed else data


def _hash_file(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _safe_stem(value):
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '-', value).strip(' .')[:70]
    return text or 'project'


def _publish(temp, folder, stem):
    """Exclusive creation prevents races and overwrites on every supported OS."""
    for index in range(1, 10001):
        path = folder / (stem + ('' if index == 1 else f' ({index})') + '.3mf')
        try:
            dest = path.open('xb')
        except FileExistsError:
            continue
        try:
            with dest, temp.open('rb') as src:
                shutil.copyfileobj(src, dest)
                dest.flush()
                os.fsync(dest.fileno())
            return path
        except BaseException:
            path.unlink(missing_ok=True)
            raise
    raise ConversionError('No free output filename found after 10,000 collisions.')


def convert_project(source: Path, profile: PrinterProfile, output_dir: Path | None = None,
                    plate: str | None = None) -> ConversionResult:
    """Create a verified new file. Never write presets, input or printer devices."""
    source = Path(source).expanduser().resolve()
    folder = Path(output_dir).expanduser().resolve() if output_dir else source.parent
    if source.suffix.lower() != '.3mf' or source.name.lower().endswith('.gcode.3mf'):
        raise ConversionError('Choose an editable .3mf project, not sliced G-code.')
    if not folder.is_dir():
        raise ConversionError('Choose an existing output folder.')
    warnings = ['Open the result using File > Open in an already running OrcaSlicer. A fresh Orca 2.4.1 startup can reset project materials; verify the material list after opening.']
    temporary = None
    try:
        if source.stat().st_size > MAX_COMPRESSED:
            raise ConversionError('The project exceeds the 512 MB input limit.')
        fingerprint = _hash_file(source)
        with zipfile.ZipFile(source) as incoming:
            entries = _index(incoming)
            if CONFIG not in entries or '3d/3dmodel.model' not in entries:
                raise ConversionError('This file lacks editable Orca/Bambu project settings or 3MF geometry.')
            original = _json(_read(incoming, entries[CONFIG]))
            converted, count = _configuration(original, profile, plate, warnings)
            updates = {CONFIG: (json.dumps(converted, ensure_ascii=False, indent=2)+'\n').encode('utf-8')}
            removed = {name for name in entries if _discard(name)}
            if any(name in entries for name in ('metadata/print_profile.config', 'metadata/slic3r_pe.config', 'metadata/slic3r_pe_model.config')):
                raise ConversionError('This project contains an additional legacy settings snapshot. Open and save an editable project in Orca first.')
            for name, info in entries.items():
                if name == 'metadata/model_settings.config':
                    updates[name] = _metadata(_read(incoming, info), converted['curr_bed_type'], count)
                elif name.endswith('.rels') or name == '[content_types].xml':
                    updates[name] = _references(_read(incoming, info), removed)
            check_fit(incoming, entries, converted)
            if removed:
                warnings.append('Cached slicing results were removed. Slice the transferred project again in Orca.')
            fd, temp_name = tempfile.mkstemp(prefix='.orca-transfer-', suffix='.tmp', dir=folder)
            os.close(fd)
            temporary = Path(temp_name)
            expected = {}
            with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as outgoing:
                for name, info in entries.items():
                    if name in removed:
                        continue
                    h = hashlib.sha256()
                    # Do not carry ZIP comments or unrelated filesystem metadata.
                    with outgoing.open(info.filename, 'w', force_zip64=True) as dest:
                        if name in updates:
                            dest.write(updates[name])
                            h.update(updates[name])
                        else:
                            with incoming.open(info) as src:
                                for chunk in iter(lambda: src.read(1024*1024), b''):
                                    dest.write(chunk)
                                    h.update(chunk)
                    expected[name] = h.hexdigest()
        with zipfile.ZipFile(temporary) as check:
            actual = _index(check)
            if actual.keys() != expected.keys():
                raise ConversionError('Output archive verification failed.')
            for name, info in actual.items():
                h = hashlib.sha256()
                with check.open(info) as stream:
                    for chunk in iter(lambda: stream.read(1024*1024), b''):
                        h.update(chunk)
                if h.hexdigest() != expected[name]:
                    raise ConversionError('Output content verification failed.')
        if _hash_file(source) != fingerprint:
            raise ConversionError('The source changed during conversion. Retry after it finishes saving.')
        path = _publish(temporary, folder, _safe_stem(source.stem) + ' — ' + _safe_stem(profile.name))
        changed = tuple(sorted(k for k in original.keys() | converted.keys() if original.get(k) != converted.get(k)))
        return ConversionResult(path, tuple(warnings), changed)
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError, GeometryError) as exc:
        if isinstance(exc, GeometryError):
            raise ConversionError(str(exc)) from exc
        raise ConversionError('The project could not be read or written. Check that it is a valid editable ZIP-based 3MF and that the output folder is writable.') from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
