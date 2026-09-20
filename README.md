# Orca Profile Transfer

Move an **editable OrcaSlicer or Bambu Studio 3MF project** to a saved OrcaSlicer
printer profile, using a small desktop GUI. Keep the project's model and tuning,
and create a new file for your printer. The original stays untouched.

This independent, early-release tool targets Windows, macOS, and Linux with
Python and Tkinter. It does not install into OrcaSlicer, change saved profiles or
preferences, register file associations, launch a slicer, or send print jobs.

**Supported scope:** single-plate projects for a single physical nozzle, including
multiple logical filament slots. The source and target nozzle diameters must
match; this version does not retune projects for a different diameter. It is not
a universal 3MF or hardware converter.
Read [supported formats and limits](docs/compatibility.md) before relying on a
conversion. Settings classification is pinned to OrcaSlicer **2.4.1**.

## Run from source

Install Python 3.10 or newer with Tkinter. On Windows and macOS, a standard
[python.org](https://www.python.org/downloads/) installation is suitable. On
Debian/Ubuntu Linux, Tkinter is commonly available as `python3-tk`; use the package
for your chosen Python version. The CLI does not require a working display.

From this repository directory:

```text
python -m venv .venv
```

Activate the environment with `.venv\Scripts\Activate.ps1` in Windows PowerShell
or `source .venv/bin/activate` on macOS/Linux, then run:

```text
python -m pip install .
python -m orca_transfer
```

On systems where the command is named `python3`, use that in place of `python`.
You can also run the installed `orca-profile-transfer` GUI command.

## Convert a project

1. Select the downloaded **editable `.3mf` project**.
2. Choose your OrcaSlicer configuration directory. Common locations are discovered
   automatically; a custom or portable installation can be selected manually.
3. Select the saved printer profile you want to use. If a parent vendor preset is
   missing, select the installation's `resources/profiles` directory as well.
4. Use the target profile's default plate, or explicitly select the plate you
   actually use. If the profile does not declare a usable default, choose one.
5. Optionally choose an output folder, then convert. A unique filename prevents
   overwriting the source or an earlier conversion.
6. In an **already-running OrcaSlicer**, use **File > Open** to open the result as
   a project. Check printer identity, plate, materials, temperatures, placement,
   and preview before printing.

The tool resolves the selected profile's inheritance within its vendor and user
account. It preserves the target preset identity so Orca can match the existing
local profile; it does not embed printer connection credentials. If Orca opens
the target as a temporary preset, select the corresponding saved printer before
using your usual connection. The converter never configures that connection.

**Orca startup caveat:** a reported OrcaSlicer 2.4.1 session reset PLA/TPU slots
to Generic ASA when a project was passed to a fresh Orca instance. The same
behavior occurred with an Orca-native saved project. File > Open in an existing
instance retained the materials in that session. This is not a guarantee for
every installation; always inspect the opened project. Archive-level tests do
not establish native slicer behavior.

## What is preserved

- Source process settings and filament tuning, including logical material slots
  and Standard/High Flow variant data. Each target variant must have matching
  source tuning; the converter does not invent missing variant values.
- Geometry, transforms, placement, painting, and object/modifier/height-range
  content, except the documented printer/plate metadata changes.
- The selected target's explicit inherited printer configuration and preset
  identity, with credentials and local-only connection information excluded.

Source printer-owned settings are removed before the target is applied. Options
not explicitly assigned by the target inheritance chain are left for Orca's
built-in defaults, rather than retaining source-printer values. Plate and preset
compatibility metadata are updated. Old sliced G-code is removed, so the result
must be sliced again.

Project hardware selectors and feeder mappings are reset for the selected
single-nozzle target. Logical material assignments stay intact; confirm physical
feeder assignments in Orca before printing.

The tool checks supported hardware and conservative geometry bounds. It does not
repack models, tune temperatures, certify material compatibility, simulate
collisions, or validate the eventual toolpath. User-entered G-code templates may
remain as settings where needed to preserve tuning; no G-code is executed by
this tool.

## Command line

List saved profiles in a configuration directory:

```text
orca-transfer --list-printers --config "/path/to/OrcaSlicer"
```

Convert using a uniquely matching printer name or a listed display label:

```text
orca-transfer --source "project.3mf" --config "/path/to/OrcaSlicer" --printer "My Printer 0.4" --output-dir "converted"
```

Add `--resources "/path/to/resources/profiles"` when installed vendor presets
are required, `--account "account-directory"` to select a local account, or
`--plate "High Temp Plate"` to explicitly select a plate. Duplicate names can be
disambiguated with the profile path returned by `--list-printers`. Listing prints
local profile paths, so redact them before sharing terminal output.

The same commands work as `python -m orca_transfer --cli ...`. Run
`orca-transfer --help` for current arguments. Errors explain why conversion
cannot proceed and leave the source unchanged.

## Development and builds

```text
python -m pip install -e ".[build]"
python -m unittest discover -s tests -v
python -m orca_transfer --smoke-test
python -m build
```

The hidden smoke test creates the GUI widgets without showing a window or reading
real printer profiles. It needs a display server; Linux CI uses Xvfb. Test
fixtures are generated synthetic projects and profiles, with no user files.

GitHub Actions defines tests on Windows, macOS, and Linux with Python 3.10, 3.12,
and 3.13. A separate manual workflow builds desktop bundles. Configuring CI is
not proof that those remote runs have passed. Native macOS/Linux GUI use and
opening converted projects in those slicer installations still need validation.
See [build and release instructions](docs/building.md), the [Python API](docs/api.md),
the [local validation record](docs/validation.md), and the repository's actual
Actions results for the current state.

## Privacy and contributions

Conversion is local and does not require network access. Configuration files are
read only. Known credential fields are removed from copied settings, but model
names, author metadata, thumbnails, and arbitrary source content are not a
general privacy scrub. Review a project before sharing it publicly.

Please report problems with a **small synthetic or explicitly shareable project**
and an anonymized description of the profiles involved. Do not attach your Orca
configuration folder, account identifiers, printer addresses, API keys, or
private models. See [contributing](docs/contributing.md).

Licensed under **AGPL-3.0-or-later**. See [LICENSE](LICENSE) and
[third-party provenance](THIRD_PARTY_NOTICES.md). No Orca vendor profile catalog,
personal printer configuration, or private converter is bundled.
