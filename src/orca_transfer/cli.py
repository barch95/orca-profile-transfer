"""Command-line entry point. Tk is imported only when the GUI is requested."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Sequence

from .engine import ConversionError, convert_project
from .profiles import (
    PrinterProfile,
    ProfileError,
    discover_config_dirs,
    load_printer_profiles,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="orca-transfer",
        description=(
            "Transfer an editable 3MF project to a saved OrcaSlicer printer "
            "profile. With no options, open the graphical application."
        ),
        epilog=(
            "The original project and Orca settings are never modified. "
            "Open the result with File > Open in an already running OrcaSlicer; "
            "check its selected printer, materials, and plate before slicing."
        ),
    )
    parser.add_argument("--cli", action="store_true", help="use the command-line interface")
    parser.add_argument("--source", type=Path, metavar="FILE.3mf", help="editable source 3MF")
    parser.add_argument("--config", type=Path, metavar="DIR", help="OrcaSlicer configuration directory")
    parser.add_argument("--resources", type=Path, metavar="DIR", help="optional OrcaSlicer resources or profiles directory")
    parser.add_argument("--account", help="optional local Orca account folder; otherwise use the active account")
    parser.add_argument("--printer", help="saved printer's unique name, display label, or exact JSON file path")
    parser.add_argument("--plate", help="explicit plate type; omitted uses the target printer's default")
    parser.add_argument("--output-dir", type=Path, metavar="DIR", help="destination directory; defaults to the source directory")
    parser.add_argument("--list-printers", action="store_true", help="list saved printer labels and paths, then exit")
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    return parser


def select_profile(profiles: Sequence[PrinterProfile], selector: str) -> PrinterProfile:
    """Resolve a selector without ever guessing between identically named presets."""
    selector_path = Path(selector).expanduser()
    try:
        selected_path = selector_path.resolve()
        path_matches = [profile for profile in profiles if Path(profile.path).resolve() == selected_path]
    except (OSError, ValueError):
        path_matches = []
    if len(path_matches) == 1:
        return path_matches[0]
    matches = [
        profile for profile in profiles
        if selector == profile.name or selector == profile.display_label
    ]
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise ProfileError(
            "That printer selection is ambiguous. Run --list-printers, then "
            "pass the exact JSON file path with --printer."
        )
    raise ProfileError("No saved printer matches that selection. Run --list-printers to see available profiles.")


def _config_path(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.expanduser()
    found = list(discover_config_dirs())
    if len(found) == 1:
        return Path(found[0])
    if not found:
        raise ProfileError("OrcaSlicer configuration was not found. Supply its directory with --config.")
    raise ProfileError("More than one OrcaSlicer configuration was found. Choose one with --config.")


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    cli_requested = args.cli or args.list_printers or any(
        value is not None for value in (
            args.source, args.config, args.resources, args.account,
            args.printer, args.plate, args.output_dir,
        )
    )
    if args.smoke_test or not cli_requested:
        try:
            from .gui import run_gui
            return run_gui(smoke_test=args.smoke_test)
        except ImportError as exc:
            if exc.name and (exc.name == "_tkinter" or exc.name.startswith("tkinter")):
                print(
                    "The graphical interface needs Python's Tk support. Install the "
                    "Tk package for your Python distribution (often python3-tk on Linux), "
                    "or run with --cli. See --help for options.",
                    file=sys.stderr,
                )
                return 2
            raise

    try:
        if not args.list_printers:
            if args.source is None:
                parser.error("--source is required for conversion")
            if not args.printer:
                parser.error("--printer is required for conversion; use --list-printers to see choices")
        profiles = list(load_printer_profiles(
            _config_path(args.config),
            resources_dir=args.resources.expanduser() if args.resources else None,
            account=args.account or None,
        ))
        if not profiles:
            raise ProfileError("No saved printer profiles were found. Save a printer preset in OrcaSlicer first.")
        if args.list_printers:
            for profile in profiles:
                print(profile.display_label)
                print(f"  {profile.path}")
            return 0
        profile = select_profile(profiles, args.printer)
        result = convert_project(
            args.source.expanduser(), profile,
            output_dir=args.output_dir.expanduser() if args.output_dir else None,
            plate=args.plate,
        )
        print(f"Created: {result.path}")
        for warning in result.warnings:
            print(f"Warning: {warning}", file=sys.stderr)
        print("Open using File > Open in an already running OrcaSlicer. Check printer, materials, and plate before slicing.")
        return 0
    except (ProfileError, ConversionError, OSError, ValueError) as exc:
        print(f"Cannot transfer: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
