"""Regenerate the reviewed option vocabulary from OrcaSlicer v2.4.1 sources.

Usage: python scripts/generate_schema.py /path/to/upstream-source-directory
Inputs: unmodified Preset.cpp and PrintConfig.cpp. No network or private inputs.
Derived metadata is distributed under AGPL-3.0-or-later; see THIRD_PARTY_NOTICES.
"""
import hashlib
import json
from pathlib import Path
import re
import sys


def uncomment(text):
    # Preserve quoted strings while discarding C++ comments.
    return re.sub(r'"(?:\\.|[^"\\])*"|/\*.*?\*/|//[^\n]*',
                  lambda m: m[0] if m[0].startswith('"') else '', text, flags=re.S)


def names(text, variable):
    match = re.search(r'\b' + re.escape(variable) + r'\s*(?:=\s*)?\{(.*?)\};', text, re.S)
    if not match:
        raise ValueError('Missing upstream set: ' + variable)
    return set(re.findall(r'"([a-zA-Z0-9_]+)"', match[1]))


def main():
    folder = Path(sys.argv[1])
    raw = {n: (folder / n).read_bytes() for n in ('Preset.cpp', 'PrintConfig.cpp')}
    preset, config = (uncomment(raw[n].decode('utf-8')) for n in raw)
    printer = (names(preset, 's_Preset_printer_options') |
               names(preset, 's_Preset_machine_limits_options') |
               names(config, 'm_extruder_option_keys'))
    schema = {
        'upstream_version': '2.4.1',
        'sources': {n: {'sha256': hashlib.sha256(data).hexdigest(),
                       'url': 'https://raw.githubusercontent.com/OrcaSlicer/OrcaSlicer/v2.4.1/src/libslic3r/' + n}
                    for n, data in raw.items()},
        'printer_keys': sorted(printer),
        'process_keys': sorted(names(preset, 's_Preset_print_options')),
        'filament_keys': sorted(names(preset, 's_Preset_filament_options')),
        'filament_variant_keys': sorted(names(config, 'filament_options_with_variant')),
        'printer_variant_keys': sorted(names(config, 'printer_options_with_variant_1')),
        'printer_double_variant_keys': sorted(names(config, 'printer_options_with_variant_2')),
        'option_types': dict(sorted(re.findall(r'(?:this->)?add\("([a-zA-Z0-9_]+)",\s*(co\w+)\)', config))),
    }
    assert len(printer) > 140 and len(schema['filament_keys']) > 60
    dest = Path(__file__).resolve().parents[1] / 'src/orca_transfer/schema.json'
    dest.write_text(json.dumps(schema, indent=2) + '\n', encoding='utf-8')
    print('Generated', len(printer), 'printer option keys.')


if __name__ == '__main__':
    main()
