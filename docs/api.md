# Python API

The engine and profile loader do not import Tkinter, start OrcaSlicer, or write to
the configuration directory. Public API names may change before version 1.0.

```python
from pathlib import Path

from orca_transfer.engine import ConversionError, convert_project
from orca_transfer.profiles import ProfileError, load_printer_profiles

config_dir = Path("/path/to/OrcaSlicer")
selected_profile_path = Path("/path/to/OrcaSlicer/user/default/machine/My Printer.json")

try:
    profiles = load_printer_profiles(config_dir)
    matches = [
        profile for profile in profiles
        if profile.path.resolve() == selected_profile_path.resolve()
    ]
    if len(matches) != 1:
        raise ProfileError("Select one exact saved printer profile.")
    result = convert_project(
        Path("example.3mf"),
        matches[0],
        output_dir=Path("converted"),
        plate=None,  # Use a declared target default, otherwise conversion errors.
    )
except (ProfileError, ConversionError, OSError) as error:
    print(f"Cannot transfer: {error}")
else:
    print(result.path)
    for warning in result.warnings:
        print(warning)
```

`load_printer_profiles(config_dir, resources_dir=None, account=None)` accepts an
optional installed vendor resource directory and a local account selector.
`discover_config_dirs()` returns existing platform-specific configuration
candidates; choosing between multiple candidates belongs to the caller.

`default_plate_type(profile)` returns a recognized default or `None`.
`available_plate_types(profile)` supplies Orca's selectable plate vocabulary,
not a physical compatibility guarantee for the printer.
Passing an explicit `plate` to `convert_project` overrides automatic selection.

`convert_project` returns a `ConversionResult` with `path`, `warnings`, and
`changed_settings`. It chooses an unused output filename and never overwrites
the source. A successful return describes a valid transfer under the supported
format checks; it does not mean Orca has loaded or sliced the result.

The profile object contains resolved machine settings. Treat it as local data:
do not log or serialize it for diagnostics. Share minimal synthetic reproductions
instead of profiles or actual configuration directories.
