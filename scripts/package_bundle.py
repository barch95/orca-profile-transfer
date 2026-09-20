"""Package a native build with its corresponding source and license notices.

Only repository source directories and the explicit PyInstaller output are read.
No Orca installation, user configuration, or printer project is included.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import re
import stat
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = ("src/orca_transfer", "scripts", "tests", "docs", ".github", "third_party_licenses")
SOURCE_FILES = ("pyproject.toml", "MANIFEST.in", "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", ".gitignore")
SOURCE_SUFFIXES = {".py", ".json", ".md", ".yml", ".yaml", ".toml", ".txt", ".terms"}


def source_paths():
    for name in SOURCE_FILES:
        yield ROOT / name
    for name in SOURCE_DIRS:
        for path in sorted((ROOT / name).rglob("*")):
            if path.is_file() and path.suffix in SOURCE_SUFFIXES and "__pycache__" not in path.parts:
                if path.is_symlink():
                    raise SystemExit(f"Do not package source symlinks: {path.name}")
                yield path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True, help="Platform label, e.g. windows-x64")
    parser.add_argument("--bundle", type=Path, help="Override the PyInstaller bundle path")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "release")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.label):
        parser.error("Platform label may contain only letters, numbers, hyphens and underscores.")

    # PyInstaller emits both a plain folder and an .app on macOS. Package only .app.
    bundle = args.bundle
    if bundle is None:
        bundle = ROOT / "dist" / "OrcaProfileTransfer.app"
        if not bundle.is_dir():
            bundle = ROOT / "dist" / "OrcaProfileTransfer"
    if not bundle.is_dir():
        parser.error("Build the application with PyInstaller before packaging.")

    version = importlib.metadata.version("orca-profile-transfer")
    release = args.output_dir
    release.mkdir(parents=True, exist_ok=True)
    output = release / f"OrcaProfileTransfer-{version}-{args.label}.zip"
    prefix = f"OrcaProfileTransfer-{version}"
    manifest: dict[str, str] = {}
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(bundle.rglob("*")):
            if not path.is_file() and not path.is_symlink():
                continue
            # Preserve framework links on macOS so the .app structure remains valid.
            # Refuse links escaping the build folder, where private data could live.
            try:
                path.resolve().relative_to(bundle.resolve())
            except ValueError:
                raise SystemExit(f"Bundle link escapes the build folder: {path.name}")
            name = f"{prefix}/{bundle.name}/{path.relative_to(bundle).as_posix()}"
            if path.is_symlink():
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, str(path.readlink()).encode("utf-8"))
            else:
                archive.write(path, name)
        for path in source_paths():
            relative = path.relative_to(ROOT).as_posix()
            data = path.read_bytes()
            archive.writestr(f"{prefix}/source/{relative}", data)
            manifest[relative] = hashlib.sha256(data).hexdigest()
        for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
            archive.write(ROOT / name, f"{prefix}/{name}")
        launcher = (
            "OrcaProfileTransfer.app" if bundle.suffix == ".app"
            else "OrcaProfileTransfer/OrcaProfileTransfer.exe" if platform.system() == "Windows"
            else "OrcaProfileTransfer/OrcaProfileTransfer"
        )
        archive.writestr(
            f"{prefix}/README.md",
            f"# Orca Profile Transfer {version}\n\n"
            f"Extract this whole archive, then open `{launcher}`. "
            "Keep the application folder intact.\n\n"
            "Read the [usage instructions and limitations](source/README.md) before converting. "
            "The result must be opened in Orca and reviewed before slicing or printing.\n\n"
            "This portable build does not install into Orca or register file associations. "
            "It is unsigned and not notarized.\n\n"
            "The complete corresponding source is in `source/`. "
            "See `LICENSE`, `THIRD_PARTY_NOTICES.md`, and `third_party_licenses/` for license terms.\n",
        )
        for path in sorted((ROOT / "third_party_licenses").iterdir()):
            if path.is_file():
                archive.write(path, f"{prefix}/third_party_licenses/{path.name}")
        # Python.org Windows includes additional dependency notices in LICENSE.txt.
        # Preserve that exact runtime document when supplied by the distribution.
        runtime_license = Path(sys.base_prefix) / "LICENSE.txt"
        if runtime_license.is_file():
            archive.write(runtime_license, f"{prefix}/third_party_licenses/Python-runtime-LICENSE.txt")
        metadata = {
            "application_version": version,
            "python_version": platform.python_version(),
            "platform": platform.system(),
            "architecture": platform.machine(),
            "pyinstaller_version": importlib.metadata.version("pyinstaller"),
            "source_sha256": manifest,
        }
        archive.writestr(f"{prefix}/BUILD-INFO.json", json.dumps(metadata, indent=2) + "\n")
    print(f"Created {output.name}")


if __name__ == "__main__":
    main()
