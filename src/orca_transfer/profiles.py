"""Read OrcaSlicer printer presets without changing its configuration.

The resolver uses exact preset names, account boundaries, and vendor manifests.
It resolves explicit JSON values, not Orca's compiled-in option defaults.
Format reference: OrcaSlicer v2.4.1, PresetBundle.cpp and AppConfig.cpp.
No upstream implementation or printer profiles are bundled in this module.
"""

from __future__ import annotations

import copy
import csv
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import shutil
import sys


class ProfileError(ValueError):
    """The selected local configuration cannot be resolved unambiguously."""


# Connection values deliberately stay in Orca's saved preset. Matching the exact
# saved preset identity lets Orca retain its own connection handling on import.
SAFE_CONNECTION_KEYS = frozenset({
    "host_type", "bbl_use_printhost", "printer_agent",
    "printhost_authorization_type", "printhost_ssl_ignore_revoke",
})
CONNECTION_KEYS = frozenset({
    "print_host", "print_host_webui", "printhost_apikey",
    "printhost_cafile", "printhost_port",
    "printhost_user", "printhost_password", "flashforge_serial_number",
    "access_code", "access_token", "refresh_token", "api_key", "password",
    "device_id", "dev_id", "ip_address", "serial_number",
})
_PRIVATE_METADATA = frozenset({
    "user_id", "setting_id", "base_id", "sync_info", "updated_time",
    "create_time", "update_time", "account_id", "local_machines",
})
_MAX_JSON_BYTES = 16 * 1024 * 1024
# Orca 2.4.1 PrintConfigDef::handle_legacy renames these before merging.
_LEGACY_ALIASES = {
    "extruder_clearance_max_radius": "extruder_clearance_radius",
    "machine_switch_extruder_time": "machine_tool_change_time",
}
# These vendor-catalog fields are not options in the pinned Orca 2.4.1 schema.
# Orca discards them; other unknown keys remain for the engine to reject.
_IGNORED_VENDOR_FIELDS = frozenset({
    "auto_toolchange_command", "bed_texture_area", "support_multi_filament",
})


@dataclass(frozen=True)
class PrinterProfile:
    name: str
    vendor: str
    account: str = field(repr=False)
    path: Path = field(repr=False)
    settings: dict[str, object] = field(repr=False)

    @property
    def display_label(self) -> str:
        """A local picker label that does not reveal an account ID or path."""
        return f"{self.name} [{self.vendor or 'Custom'}]"


@dataclass(frozen=True)
class _Record:
    name: str
    vendor: str
    path: Path
    settings: dict[str, object] = field(repr=False)
    system: bool = False


def _safe_component(value: object) -> bool:
    return (isinstance(value, str) and bool(value) and value not in {".", ".."}
            and not any(c in value for c in '/\\:\x00') and not value.endswith((".", " ")))


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ProfileError("An Orca configuration file contains duplicate JSON keys. Re-save it in Orca.")
        result[key] = value
    return result


def _invalid_constant(value: str) -> object:
    raise ProfileError("An Orca configuration file contains an invalid numeric value. Re-save it in Orca.")


def _json(path: Path, *, config: bool = False) -> dict[str, object]:
    """Read only an object; never include file contents or private paths in errors."""
    try:
        if path.stat().st_size > _MAX_JSON_BYTES:
            raise ProfileError("An Orca configuration file is too large to read safely.")
        text = path.read_text(encoding="utf-8-sig")
        if config:
            # Windows Orca appends a checksum comment after its JSON object.
            text = re.sub(r"\s*# MD5 checksum [0-9a-fA-F]{32}\s*$", "", text)
        value = json.loads(text, object_pairs_hook=_object, parse_constant=_invalid_constant)
    except (OSError, UnicodeError, json.JSONDecodeError):
        what = "OrcaSlicer.conf" if config else "a printer preset or vendor manifest"
        raise ProfileError(f"Could not read {what}. Open Orca and repair or re-save the configuration.") from None
    if not isinstance(value, dict):
        raise ProfileError("An Orca configuration file must contain a JSON object.")
    return value


def _public_settings(settings: dict[str, object]) -> dict[str, object]:
    result = {key: copy.deepcopy(value) for key, value in settings.items()
            if key not in CONNECTION_KEYS and key not in _PRIVATE_METADATA
            and key not in _IGNORED_VENDOR_FIELDS
            and (not key.startswith("printhost_") or key in SAFE_CONNECTION_KEYS)}
    for old, current in _LEGACY_ALIASES.items():
        if old in result:
            result.setdefault(current, result.pop(old))
    return result


def _unique_existing(paths: list[Path]) -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        try:
            resolved = path.expanduser().resolve()
            if resolved.is_dir() and resolved not in seen:
                found.append(resolved)
                seen.add(resolved)
        except OSError:
            continue
    return found


def discover_config_dirs() -> list[Path]:
    """Return existing standard, Flatpak, and discoverable portable data dirs.

    ORCA_SLICER_CONFIG is an optional override for this tool. Portable or custom
    --datadir locations can always be selected manually in the interface.
    """
    home = Path.home()
    candidates: list[Path] = []
    if os.environ.get("ORCA_SLICER_CONFIG"):
        candidates.append(Path(os.environ["ORCA_SLICER_CONFIG"]))
    if sys.platform == "win32":
        candidates.append(Path(os.environ.get("APPDATA", home / "AppData/Roaming")) / "OrcaSlicer")
    elif sys.platform == "darwin":
        candidates.append(home / "Library/Application Support/OrcaSlicer")
    else:
        candidates.append(Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")) / "OrcaSlicer")
        for app_id in ("com.orcaslicer.OrcaSlicer", "io.github.softfever.OrcaSlicer"):
            candidates.append(home / ".var/app" / app_id / "config/OrcaSlicer")
    for executable in ("orca-slicer", "OrcaSlicer", "orca-slicer.exe"):
        location = shutil.which(executable)
        if location:
            candidates.append(Path(location).resolve().parent / "data_dir")
    return [p for p in _unique_existing(candidates)
            if (p / "OrcaSlicer.conf").is_file() or (p / "user").is_dir() or (p / "system").is_dir()]


def _resource_dirs(config_dir: Path, explicit: Path | None) -> list[Path]:
    candidates: list[Path] = []
    if explicit is not None:
        root = Path(explicit).expanduser()
        candidates.extend([root, root / "profiles", root / "resources/profiles",
                           root / "Contents/Resources/profiles"])
    else:
        if os.environ.get("ORCA_SLICER_RESOURCES"):
            root = Path(os.environ["ORCA_SLICER_RESOURCES"])
            candidates.extend([root, root / "profiles"])
        candidates.extend([config_dir.parent / "resources/profiles", config_dir / "resources/profiles"])
        home = Path.home()
        if sys.platform == "win32":
            for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
                if base:
                    candidates.append(Path(base) / "OrcaSlicer/resources/profiles")
            if os.environ.get("LOCALAPPDATA"):
                candidates.append(Path(os.environ["LOCALAPPDATA"]) / "Programs/OrcaSlicer/resources/profiles")
        elif sys.platform == "darwin":
            candidates.extend([Path("/Applications/OrcaSlicer.app/Contents/Resources/profiles"),
                               home / "Applications/OrcaSlicer.app/Contents/Resources/profiles"])
        else:
            for base in ("/usr/share/OrcaSlicer", "/usr/share/orca-slicer", "/opt/OrcaSlicer"):
                candidates.extend([Path(base) / "resources/profiles", Path(base) / "profiles"])
        for executable in ("orca-slicer", "OrcaSlicer", "orca-slicer.exe"):
            location = shutil.which(executable)
            if location:
                base = Path(location).resolve().parent
                candidates.extend([base / "resources/profiles", base.parent / "Resources/profiles"])
    valid = [path for path in _unique_existing(candidates) if any(path.glob("*.json"))]
    if explicit is not None and not valid:
        raise ProfileError("The selected resources folder has no vendor manifests. Select Orca's resources/profiles folder.")
    # Do not merge multiple installations, whose catalog versions may differ.
    return valid[:1]


def list_accounts(config_dir: Path) -> list[str]:
    """Return local account-folder names for explicit selection; do not log them."""
    root = Path(config_dir).expanduser() / "user"
    if not root.is_dir():
        return []
    try:
        return sorted(p.name for p in root.iterdir()
                      if p.is_dir() and _safe_component(p.name) and (p / "machine").is_dir())
    except OSError:
        raise ProfileError("Could not read Orca's account folders. Check folder permissions.") from None


def _select_account(config_dir: Path, conf: dict[str, object], account: str | None,
                    has_conf: bool) -> str:
    if account is not None:
        if not _safe_component(account):
            raise ProfileError("Choose a valid account folder name, not a path.")
        if not (config_dir / "user" / account / "machine").is_dir():
            raise ProfileError("The selected account has no printer folder. Save a printer in that Orca account first.")
        return account
    if has_conf:
        app = conf.get("app", {})
        if not isinstance(app, dict):
            raise ProfileError("OrcaSlicer.conf has an invalid app section. Re-save the settings in Orca.")
        selected = app.get("preset_folder", "") or "default"
        if not _safe_component(selected):
            raise ProfileError("Orca's active account folder is invalid. Select an account explicitly.")
        return selected
    accounts = list_accounts(config_dir)
    if "default" in accounts:
        return "default"
    if len(accounts) == 1:
        return accounts[0]
    if len(accounts) > 1:
        raise ProfileError("Orca's active account is unknown and multiple accounts exist. Select an account explicitly.")
    return "default"


def _preset_name(settings: dict[str, object], fallback: str) -> str:
    name = settings.get("name", fallback)
    if not isinstance(name, str) or not name.strip():
        raise ProfileError("A printer preset is missing its name. Re-save it in Orca.")
    return name


def _load_catalog(config_dir: Path, resources_dir: Path | None) -> tuple[list[_Record], dict[str, set[str]]]:
    manifests: dict[str, Path] = {}
    for root in _resource_dirs(config_dir, resources_dir):
        manifests.update({p.stem: p for p in root.glob("*.json")})
    # A whole installed vendor bundle overrides the shipped bundle. Missing
    # parents in it are errors; borrowing a stale resource parent is unsafe.
    manifests.update({p.stem: p for p in (config_dir / "system").glob("*.json")})
    records: list[_Record] = []
    model_vendors: dict[str, set[str]] = {}
    for vendor, path in sorted(manifests.items()):
        manifest = _json(path)
        models = manifest.get("machine_model_list", [])
        machine_list = manifest.get("machine_list", [])
        if not isinstance(models, list) or not isinstance(machine_list, list):
            raise ProfileError("A vendor manifest has invalid printer lists. Repair its bundle in Orca.")
        for item in models:
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                model_vendors.setdefault(item["name"], set()).add(vendor)
        vendor_root = (path.parent / vendor).resolve()
        for item in machine_list:
            if not isinstance(item, dict) or not isinstance(item.get("sub_path"), str):
                raise ProfileError("A vendor manifest has an invalid printer entry. Repair its bundle in Orca.")
            relative = item["sub_path"].replace("\\", "/")
            preset_path = (vendor_root / relative).resolve()
            if not preset_path.is_relative_to(vendor_root):
                raise ProfileError("A vendor manifest points outside its bundle. Select a valid Orca installation.")
            preset = _json(preset_path)
            name = _preset_name(preset, str(item.get("name", preset_path.stem)))
            if item.get("name") and item["name"] != name:
                raise ProfileError("A vendor manifest and preset disagree on a printer name. Repair its bundle in Orca.")
            records.append(_Record(name, vendor, preset_path, _public_settings(preset), True))
    return records, model_vendors


class _Resolver:
    def __init__(self, system: list[_Record], users: list[_Record], model_vendors: dict[str, set[str]]) -> None:
        self.system: dict[tuple[str, str], _Record] = {}
        self.users: dict[str, _Record] = {}
        self.model_vendors = model_vendors
        self.renamed: dict[tuple[str, str], list[_Record]] = {}
        self.cache: dict[Path, tuple[dict[str, object], str]] = {}
        for record in system:
            key = (record.vendor, record.name)
            if key in self.system:
                raise ProfileError("A vendor has duplicate printer preset names. Repair that bundle in Orca.")
            self.system[key] = record
            aliases = record.settings.get("renamed_from", [])
            if isinstance(aliases, str):
                try:
                    aliases = next(csv.reader([aliases], delimiter=";", escapechar="\\", strict=True))
                except (csv.Error, StopIteration):
                    raise ProfileError("A printer's renamed_from list is invalid. Repair its vendor bundle in Orca.") from None
            if not isinstance(aliases, list) or any(not isinstance(alias, str) for alias in aliases):
                raise ProfileError("A printer's renamed_from list is invalid. Repair its vendor bundle in Orca.")
            for alias in aliases:
                if alias:
                    self.renamed.setdefault((record.vendor, alias), []).append(record)
        for record in users:
            if record.name in self.users:
                raise ProfileError("The selected account has duplicate printer preset names. Rename them in Orca before continuing.")
            self.users[record.name] = record

    def _vendor_hint(self, record: _Record) -> str:
        if record.vendor:
            return record.vendor
        explicit = record.settings.get("vendor", "")
        if isinstance(explicit, str) and explicit:
            return explicit
        model = record.settings.get("printer_model", "")
        vendors = self.model_vendors.get(model, set()) if isinstance(model, str) else set()
        return next(iter(vendors)) if len(vendors) == 1 else ""

    def resolve(self, record: _Record, stack: tuple[Path, ...] = ()) -> tuple[dict[str, object], str]:
        if record.path in self.cache:
            return copy.deepcopy(self.cache[record.path])
        if record.path in stack or len(stack) >= 64:
            raise ProfileError("Printer inheritance has a cycle or is too deep. Repair the saved profile in Orca.")
        parent_name = record.settings.get("inherits", "")
        if not isinstance(parent_name, str):
            raise ProfileError("A printer's inherits value must be one exact preset name. Re-save it in Orca.")
        vendor = self._vendor_hint(record)
        merged: dict[str, object] = {}
        if parent_name:
            if not record.system and parent_name in self.users and parent_name != record.name:
                parent = self.users[parent_name]
            else:
                candidates = [r for (v, n), r in self.system.items()
                              if n == parent_name and (not vendor or v == vendor)]
                if not candidates:
                    candidates = [r for (v, n), aliases in self.renamed.items()
                                  if n == parent_name and (not vendor or v == vendor) for r in aliases]
                if not candidates:
                    raise ProfileError(f"Printer '{record.name}' has a missing parent preset. Install its vendor in Orca or select the matching resources folder.")
                if len(candidates) != 1:
                    raise ProfileError(f"Printer '{record.name}' has an ambiguous parent across vendors. Re-save it with a printer model or vendor identity in Orca.")
                parent = candidates[0]
            merged, parent_vendor = self.resolve(parent, stack + (record.path,))
            if vendor and parent_vendor and vendor != parent_vendor:
                raise ProfileError("A printer inherits from a different vendor. Repair its ancestry in Orca.")
            vendor = vendor or parent_vendor
            parent_name = parent.name
            if not record.system:
                for key in ("printer_extruder_id", "printer_extruder_variant"):
                    previous, current = merged.get(key), record.settings.get(key)
                    if previous and current and previous != current:
                        raise ProfileError("A saved printer changes its parent's extruder variant layout. This transfer cannot resolve that layout safely; use a profile with the same parent layout.")
        for value in record.settings.values():
            if value is None or (isinstance(value, list) and any(item is None or item in ("nil", "null") for item in value)):
                raise ProfileError("A printer contains nil/null inherited values. This transfer requires explicit printer values; choose or save a profile without nullable overrides.")
        merged.update(copy.deepcopy(record.settings))
        # Retain the immediate parent, rather than a parent's own ancestor.
        merged["inherits"] = parent_name
        merged["name"] = record.name
        merged["printer_settings_id"] = record.name
        result = (merged, vendor or "Custom")
        self.cache[record.path] = copy.deepcopy(result)
        return result


def _enabled_models(conf: dict[str, object]) -> set[tuple[str, str, str]]:
    models = conf.get("models", [])
    if not isinstance(models, list):
        raise ProfileError("Orca's enabled printer list is invalid. Re-save the configuration in Orca.")
    enabled: set[tuple[str, str, str]] = set()
    for item in models:
        if not isinstance(item, dict):
            continue
        vendor, model, variants = item.get("vendor"), item.get("model"), item.get("nozzle_diameter")
        if isinstance(variants, str):
            variants = [part.strip().strip('"') for part in variants.split(";")]
        if isinstance(vendor, str) and isinstance(model, str) and isinstance(variants, list):
            enabled.update((vendor, model, str(variant)) for variant in variants)
    return enabled


def load_printer_profiles(config_dir: Path, resources_dir: Path | None = None,
                          account: str | None = None) -> list[PrinterProfile]:
    """Load saved user printers and enabled stock printers, without writing files.

    The active account is read from OrcaSlicer.conf; an explicit account selects
    only that account. Never pools account directories or guesses a vendor when
    duplicate parent names exist. Connection values are removed from settings.
    """
    config_dir = Path(config_dir).expanduser().resolve()
    if not config_dir.is_dir():
        raise ProfileError("The Orca configuration folder does not exist. Select it using Orca's Help menu.")
    conf_path = config_dir / "OrcaSlicer.conf"
    conf = _json(conf_path, config=True) if conf_path.is_file() else {}
    selected_account = _select_account(config_dir, conf, account, conf_path.is_file())
    system, model_vendors = _load_catalog(config_dir, resources_dir)
    users: list[_Record] = []
    for path in sorted((config_dir / "user" / selected_account / "machine").glob("*.json")):
        preset = _json(path)
        if preset.get("type", "machine") != "machine":
            continue
        name = _preset_name(preset, path.stem)
        users.append(_Record(name, "", path.resolve(), _public_settings(preset)))
    resolver = _Resolver(system, users, model_vendors)
    profiles: list[PrinterProfile] = []
    user_identities: set[tuple[str, str]] = set()
    for record in users:
        settings, vendor = resolver.resolve(record)
        profiles.append(PrinterProfile(record.name, vendor, selected_account, record.path, settings))
        user_identities.add((record.name, vendor))
    enabled = _enabled_models(conf)
    if enabled:
        for record in system:
            if str(record.settings.get("instantiation", "true")).lower() in {"false", "0"}:
                continue
            settings, vendor = resolver.resolve(record)
            key = (vendor, str(settings.get("printer_model", "")), str(settings.get("printer_variant", "")))
            if key in enabled and (record.name, vendor) not in user_identities:
                profiles.append(PrinterProfile(record.name, vendor, "", record.path, settings))
    if not profiles:
        raise ProfileError("No saved or enabled printer profiles were found for this Orca account. Add or save a printer in Orca, then reload.")
    return sorted(profiles, key=lambda profile: (profile.name.casefold(), profile.vendor.casefold()))
