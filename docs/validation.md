# Validation record — 0.1.0

Validated locally on Windows and on GitHub-hosted runners on 2026-09-20. These
results describe the tested cases, not a guarantee for arbitrary printers or
projects.

- 78 synthetic unit/integration tests passed with Python 3.12 and 3.13. Tests cover
  account/vendor inheritance, legacy profile aliases, ambiguous names, secret
  exclusion, untouched source files, output collisions, geometric fit checks,
  model bytes, local process settings, painting, height-range metadata, logical
  materials and variant arrays, CLI conversion, and hidden threaded GUI use.
- The Tk GUI passed a hidden construction/startup check on Windows.
- A Windows PyInstaller bundle passed the same hidden startup check. The bundle
  includes corresponding source, schema provenance, dependency notices and a
  source hash manifest.
- The Python wheel and source distribution were built successfully.
- The [nine-job GitHub Actions matrix](https://github.com/barch95/orca-profile-transfer/actions/runs/35535866969)
  passed on Windows, macOS, and Ubuntu with Python 3.10, 3.12, and 3.13. It checks
  the synthetic suite, CLI startup, hidden GUI startup, and wheel/source builds.
  Linux runs the full GUI regressions under Xvfb. The GUI tests use the same native
  main loop as the application, including threaded conversion.
- Two fully synthetic converted projects were loaded by the installed
  OrcaSlicer 2.4.1 command-line parser using `--export-settings`. Both returned
  exit code zero. The exported settings retained the target identity, Klipper
  flavor, target start template, High Temp Plate, source layer height/walls,
  PLA/TPU identities/colors, nozzle temperatures, flow ratios and nullable
  material retraction overrides. The second case retained two logical materials
  with four Standard/High Flow tuning entries and indices `1,1,2,2`.

Native checks used a synthetic input and isolated data/output/temp/log directories
and child-process environment. No personal Orca data was supplied, no slicer GUI
session was opened, no G-code was executed, and no print job was sent.

Native parser success does **not** verify GUI saved-printer connection matching,
the fresh-start material-selection behavior, slicing, actual printing, or native
macOS/Linux behavior. The known startup caveat remains documented in the README.
The automated test matrix has passed; the separate native desktop build workflow
has not been run. macOS/Linux desktop bundles and manual interactive use remain
unverified.

For native validation in another environment, use a synthetic editable project,
an isolated `--datadir` and `--outputdir`, task-local temporary directories and
working directory, and the explicit `--export-settings output.json` CLI action.
Use `--arrange 0 --ensure-on-bed=0`. Do not pass slicing, printing, or
default-filament replacement options. Compare the exported settings to the input
and converted configuration. Never substitute a live user configuration into a
public test fixture.
