# License and provenance

Orca Profile Transfer is an independent project. It is not an official OrcaSlicer
or Bambu Lab product. Those names identify compatible file formats and software;
no logos or other branding assets are included.

Original implementation: Copyright (C) 2026 Orca Profile Transfer contributors.
This project is distributed under **GNU AGPL version 3 or later**, without
warranty. See [LICENSE](LICENSE). This license is used conservatively because the
package includes a small settings catalog derived from AGPL OrcaSlicer sources.
No code from a private converter is included.

## OrcaSlicer-derived settings catalog

`src/orca_transfer/schema.json` contains option names and option classifications
derived from the official **OrcaSlicer v2.4.1** release. It is not a collection of
printer profiles. The source files are:

- [Preset.cpp](https://github.com/OrcaSlicer/OrcaSlicer/blob/v2.4.1/src/libslic3r/Preset.cpp)
- [PrintConfig.cpp](https://github.com/OrcaSlicer/OrcaSlicer/blob/v2.4.1/src/libslic3r/PrintConfig.cpp)
- [PrintConfig.hpp](https://github.com/OrcaSlicer/OrcaSlicer/blob/v2.4.1/src/libslic3r/PrintConfig.hpp)
  was consulted to verify serialized plate values.

OrcaSlicer copyright belongs to its contributors and the upstream Slic3r,
PrusaSlicer, Bambu Studio, and other credited authors. OrcaSlicer identifies its
license as AGPL-3.0 in its [release README](https://github.com/OrcaSlicer/OrcaSlicer/blob/v2.4.1/README.md#license)
and [license](https://github.com/OrcaSlicer/OrcaSlicer/blob/v2.4.1/LICENSE.txt).
The repository's LICENSE is an unmodified copy of that standard license text.

The schema records the upstream URLs and SHA-256 hashes. Its derivation script is
`scripts/generate_schema.py`. The transformation extracts classification data;
the upstream C++ implementation is not bundled. Review that script and the schema
provenance when upgrading the supported Orca version.

No separate permissive license was found under `resources/profiles` in the
v2.4.1 tree during the September 2026 review. Consequently this repository does
not vendor or redistribute Orca's vendor profile catalogs. Users provide their
own installed profiles, which the application reads locally. This does not
relicense those files. A converted project may contain profile values and the
source project's models; the tool's license does not grant permission to
redistribute someone else's model or profile content.

## Runtime and build tools

The source application has no third-party Python package dependencies. It uses
Python's standard library, including Tkinter. A desktop bundle includes an
unmodified Python interpreter and Tcl/Tk runtime assembled by PyInstaller.

| Component | License / reference | Bundled notice |
| --- | --- | --- |
| Python | [PSF license and historical licenses](https://docs.python.org/3/license.html) | `third_party_licenses/Python-LICENSE.txt` (Python 3.12 branch) |
| Tcl | [Tcl/Tk permissive license](https://www.tcl-lang.org/software/tcltk/license.html) | `third_party_licenses/Tcl-license.terms` (8.6 branch) |
| Tk | [Tcl/Tk permissive license](https://www.tcl-lang.org/software/tcltk/license.html) | `third_party_licenses/Tk-license.terms` (8.6 branch) |
| PyInstaller bootloader | [GPL-2.0-or-later with distribution exception](https://pyinstaller.org/en/stable/license.html) | `third_party_licenses/PyInstaller-COPYING.txt` (6.22.3) |

License texts were retrieved from the respective official repositories. They are
license documents, not vendored implementations. The PyInstaller exception
permits distributing bundles under the application's license; PyInstaller itself
retains its own license. Build-only dependencies (`setuptools`, `build`, and the
PyInstaller tool and hooks) are installed by the package manager, not copied into
the application source. Final binary dependencies vary by operating system and
Python distribution. Release maintainers must retain any additional notices
supplied with their chosen runtime and inspect the final bundle when changing
Python, Tcl/Tk, or PyInstaller versions.

The desktop packaging script includes the application's complete corresponding
source and license files alongside every binary archive. It records build
versions and source hashes in `BUILD-INFO.json`.
