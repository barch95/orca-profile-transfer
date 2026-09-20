# Contributing

Use Python 3.10-compatible syntax, keep runtime dependencies small, and keep the
conversion engine independent from the GUI. Contributions use this repository's
AGPL-3.0-or-later license. Retain upstream provenance for derived data.

Run `python -m unittest discover -s tests -v` before submitting changes. For GUI
changes, run `python -m orca_transfer --smoke-test` and manually exercise the
affected flow with synthetic data. Linux smoke tests require a display server
(for example, `xvfb-run -a python -m orca_transfer --smoke-test`).

Never commit your real Orca `user`/`system` folders, downloaded models, converted
3MF files, logs, printer connection information, or secrets. Tests should create
small synthetic archives in temporary directories. The `.gitignore` blocks
common private file types but cannot recognize every secret; review all staged
changes before publishing.

Useful regression tests assert a user-visible invariant: source preservation,
correct vendor/account inheritance, logical filament assignments, collision-safe
output, explicit rejection of unsupported hardware/layouts, or removal of known
credentials. Do not add fixtures copied from a private baseline or third-party
model without an explicit redistribution license.

When reporting a conversion issue, describe the source writer and version,
target printer family, OS, Orca version, and the error text with private paths
redacted. Prefer a minimal synthetic reproduction. A real profile can reveal
hostnames, keys, custom G-code, and account information even when it looks like
ordinary JSON.
