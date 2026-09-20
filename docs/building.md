# Build and release

## Source packages

Use an isolated environment and a clean checkout. No Orca installation or real
printer profile is required to build or run synthetic tests.

```text
python -m venv .venv
```

Activate it, then:

```text
python -m pip install -e ".[build]"
python -m unittest discover -s tests -v
python -m build
```

The wheel and source distribution are created under `dist`. The source
distribution includes tests, build scripts, docs, and the schema generator.

## Desktop GUI bundle

PyInstaller builds for the operating system and CPU running it; it is not a
cross-compiler. Build separately on Windows, macOS Apple Silicon, macOS Intel,
and Linux as needed. Use Python 3.12 for the release workflow. An installed Python
with working Tcl/Tk is required on the build machine.

```text
python -m PyInstaller --noconfirm --clean --onedir --windowed --name OrcaProfileTransfer --collect-data orca_transfer scripts/gui_entry.py
python scripts/package_bundle.py --label windows-x64
```

Replace the label with `macos-arm64`, `macos-x64`, or `linux-x64` for the actual
build environment. Labels describe the build; they do not convert its
architecture. The package script creates a ZIP under `release`, including:

- The GUI application folder, or `.app` on macOS.
- Matching application source and build instructions.
- Application and runtime license notices.
- `BUILD-INFO.json`, containing tool versions and source hashes.

Extract the complete archive and keep the application folder intact. On Windows,
open `OrcaProfileTransfer.exe` inside its folder. On macOS, open the `.app`; use
Archive Utility or `ditto` to preserve framework symbolic links. On Linux, run
`OrcaProfileTransfer` from its folder; a desktop session and compatible system
libraries are still required. The Linux workflow uses Ubuntu 22.04 to provide a
defined build baseline, not a claim of support for every distribution.

The build does not install shortcuts, write registry entries, or integrate with
OrcaSlicer. These builds are not signed or notarized; platform protections may
show publisher warnings. A public maintainer can add signing with their own
credentials, kept in CI secrets and excluded from artifacts.

## GitHub Actions

`.github/workflows/tests.yml` runs unit tests, CLI startup, a hidden GUI smoke
test, and source/wheel builds on Windows, macOS, and Linux, across Python 3.10,
3.12, and 3.13. The GUI smoke test creates and destroys the application widgets;
it does not open a model in Orca or simulate a full user session. Linux uses Xvfb.

`.github/workflows/build.yml` is manual (`workflow_dispatch`). Open Actions,
select **Build desktop bundles**, and run it on the reviewed commit. Each OS job
produces an Actions artifact containing its ZIP. The workflow has read-only
repository permissions and does not create releases, tags, or upload packages to
a public package index.

The first successful matrix run is still required after the repository is
published. CI configuration alone does not establish macOS/Linux runtime support.

## Before publishing a release

1. Run tests and inspect the build artifacts on the intended platforms.
2. Use a synthetic editable project and synthetic profile to complete a GUI
   conversion. Separately verify an explicitly shareable project in Orca,
   recording the Orca version and whether File > Open was used.
3. Inspect the archive and matching source for accidental real profiles, machine
   addresses, account IDs, private models, logs, or credentials.
4. Check `THIRD_PARTY_NOTICES.md` against the Python/Tcl/Tk/PyInstaller versions
   recorded in the build. Include additional dependency notices supplied by the
   runtime distribution if needed. Do not strip the bundled license documents.
5. Publish the matching source together with the binary archive and document
   tested OS/CPU/Orca versions, known limitations, and unsigned status.

The tool is AGPL-3.0-or-later; redistribution of binaries needs the corresponding
source under that license. Every desktop ZIP includes it. No upstream vendor
profile catalogs are needed in the release.

## Updating the schema

`scripts/generate_schema.py` derives setting ownership and variant classifications
from official OrcaSlicer sources. Download the unmodified `Preset.cpp` and
`PrintConfig.cpp` from the pinned URLs recorded in `src/orca_transfer/schema.json`
to a temporary directory outside the repository. Run
`python scripts/generate_schema.py /path/to/that-directory`. The application
ships the resulting schema, so
conversion does not fetch or compile OrcaSlicer. Changing the schema is a
compatibility change: review extracted classifications, update provenance and
license notices, and extend synthetic tests before claiming support for another
Orca release.
