"""Public synthetic CLI and hidden Tk integration tests.

Never discover an installed Orca configuration or launch OrcaSlicer. Tk tests
skip without a working desktop/Tcl installation; CI separately runs explicit
smoke mode under its platform's desktop or Xvfb.
"""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

from orca_transfer import cli, profiles
from orca_transfer.profiles import PrinterProfile, ProfileError


MODEL = b'''<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
 <resources><object id="1" type="model"><mesh>
  <vertices><vertex x="10" y="10" z="0"/><vertex x="20" y="10" z="0"/>
   <vertex x="10" y="20" z="10"/></vertices>
  <triangles><triangle v1="0" v2="1" v3="2"/></triangles>
 </mesh></object></resources>
 <build><item objectid="1"/></build>
</model>'''


class SyntheticProject(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = self.root / "config"
        preset_dir = self.config / "user" / "default" / "machine"
        preset_dir.mkdir(parents=True)
        self.preset_path = preset_dir / "Synthetic target.json"
        self.preset = {
            "name": "Synthetic target", "type": "machine", "inherits": "",
            "nozzle_diameter": ["0.4"], "printer_model": "Synthetic target model",
            "printer_variant": "0.4", "printer_extruder_variant": ["Direct Drive Standard"],
            "default_bed_type": "High Temp Plate", "printable_height": "200",
            "printable_area": ["0x0", "200x0", "200x200", "0x200"],
            "machine_start_gcode": "G28 ; synthetic target only",
            "print_host": "synthetic-printer.invalid",
            "printhost_apikey": "SYNTHETIC_TEST_SECRET_NEVER_EXPORT",
        }
        self.preset_path.write_text(json.dumps(self.preset), encoding="utf-8")
        self.source_settings = {
            "printer_settings_id": "Synthetic source", "print_settings_id": "Synthetic process",
            "layer_height": "0.2", "machine_start_gcode": "G28 ; synthetic source",
            "nozzle_diameter": ["0.4"], "filament_colour": ["#FF0000", "#00FF00"],
            "filament_type": ["PLA", "TPU"],
            "filament_settings_id": ["Synthetic PLA", "Synthetic TPU"],
            "filament_flow_ratio": ["0.98", "1.01"], "filament_self_index": ["1", "2"],
            "filament_extruder_variant": ["Direct Drive Standard", "Direct Drive Standard"],
            "support_filament": "2",
        }
        self.source = self.root / "source.3mf"
        with zipfile.ZipFile(self.source, "w") as archive:
            archive.writestr("Metadata/project_settings.config", json.dumps(self.source_settings))
            archive.writestr("3D/3dmodel.model", MODEL)
        self.source_hash = hashlib.sha256(self.source.read_bytes()).hexdigest()
        resource_patch = patch.object(profiles, "_resource_dirs", side_effect=lambda config, explicit: [explicit] if explicit else [])
        resource_patch.start()
        self.addCleanup(resource_patch.stop)

    def assert_preserved_source(self):
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), self.source_hash)


class CliTests(SyntheticProject):
    def run_cli(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            status = cli.main(list(args))
        return status, stdout.getvalue(), stderr.getvalue()

    def test_lists_real_synthetic_saved_profile_without_credentials(self):
        status, stdout, stderr = self.run_cli("--list-printers", "--config", str(self.config))
        self.assertEqual(status, 0)
        self.assertIn("Synthetic target [Custom]", stdout)
        # The CLI resolves paths, including Windows 8.3 and macOS /var aliases.
        self.assertIn(str(self.preset_path.resolve()), stdout)
        self.assertNotIn("SYNTHETIC_TEST_SECRET", stdout + stderr)
        self.assertNotIn("synthetic-printer.invalid", stdout + stderr)

    def test_cli_converts_by_exact_path_with_real_engine(self):
        output_dir = self.root / "output"
        output_dir.mkdir()
        status, stdout, stderr = self.run_cli(
            "--cli", "--source", str(self.source), "--config", str(self.config),
            "--printer", str(self.preset_path), "--output-dir", str(output_dir),
        )
        self.assertEqual(status, 0, stderr)
        created = list(output_dir.glob("*.3mf"))
        self.assertEqual(len(created), 1)
        self.assertIn(str(created[0].resolve()), stdout)
        with zipfile.ZipFile(created[0]) as archive:
            result = json.loads(archive.read("Metadata/project_settings.config"))
            self.assertEqual(archive.read("3D/3dmodel.model"), MODEL)
        self.assertEqual(result["printer_settings_id"], self.preset["name"])
        self.assertEqual(result["filament_flow_ratio"], self.source_settings["filament_flow_ratio"])
        self.assertEqual(result["curr_bed_type"], "High Temp Plate")
        self.assertNotIn("SYNTHETIC_TEST_SECRET", json.dumps(result) + stdout + stderr)
        self.assertNotIn("print_host", result)
        self.assert_preserved_source()

    def test_cli_incompatible_target_has_actionable_error_and_no_output(self):
        self.preset["nozzle_diameter"] = ["0.6"]
        self.preset_path.write_text(json.dumps(self.preset), encoding="utf-8")
        status, stdout, stderr = self.run_cli(
            "--source", str(self.source), "--config", str(self.config),
            "--printer", "Synthetic target",
        )
        self.assertEqual(status, 2)
        self.assertIn("nozzle diameters differ", stderr)
        self.assertEqual(stdout, "")
        self.assertEqual(list(self.root.glob("*.3mf")), [self.source])
        self.assert_preserved_source()

    def test_profile_identity_is_never_guessed_from_duplicate_names(self):
        first = PrinterProfile("Same printer", "Vendor A", "default", self.root / "first.json", {})
        second = PrinterProfile("Same printer", "Vendor B", "default", self.root / "second.json", {})
        with self.assertRaisesRegex(ProfileError, "ambiguous"):
            cli.select_profile([first, second], "Same printer")
        self.assertIs(cli.select_profile([first, second], second.display_label), second)
        self.assertIs(cli.select_profile([first, second], str(first.path)), first)

    def test_ambiguous_configuration_requires_explicit_choice(self):
        with patch.object(cli, "discover_config_dirs", return_value=[self.root / "one", self.root / "two"]):
            status, _, stderr = self.run_cli("--list-printers")
        self.assertEqual(status, 2)
        self.assertIn("More than one", stderr)
        self.assertIn("--config", stderr)


class GuiTests(SyntheticProject):
    def setUp(self):
        super().setUp()
        try:
            import tkinter as tk
            from orca_transfer import gui
        except ImportError:
            self.skipTest("Tcl/Tk is not installed")
        try:
            self.window = tk.Tk()
        except tk.TclError:
            self.skipTest("No desktop display or working Tcl/Tk installation")
        self.window.withdraw()
        def destroy_window():
            try:
                self.window.update_idletasks()
                self.window.destroy()
            except tk.TclError:
                pass  # The teardown regression deliberately destroys its own root.
        self.addCleanup(destroy_window)
        self.gui = gui
        self.app = gui.TransferApp(self.window, auto_discover=False)

    def wait_for_worker(self):
        deadline = time.monotonic() + 10
        def poll():
            if not self.app.busy or time.monotonic() >= deadline:
                self.window.quit()
            else:
                self.window.after(10, poll)
        # Match the real application event loop; repeated update() can block
        # inside Cocoa's nested event processing on macOS.
        self.window.after(10, poll)
        self.window.mainloop()
        self.assertFalse(self.app.busy, "GUI worker did not finish")

    def test_hidden_widget_smoke_and_real_threaded_conversion(self):
        self.app.config.set(str(self.config))
        with patch.object(self.gui.messagebox, "showerror") as error_dialog:
            self.app._load_profiles()
            self.wait_for_worker()
            self.assertEqual(len(self.app.profiles), 1)
            self.assertEqual(self.app.printer_box.current(), 0)
            self.app.source.set(str(self.source))
            self.app._convert()
            self.assertTrue(self.app.busy)
            self.wait_for_worker()
            error_dialog.assert_not_called()
        self.assertTrue(self.app.output_path.is_file())
        self.assertIn("File > Open", self.app.result_text.get("1.0", "end"))
        self.assertEqual(str(self.app.convert_button["state"]), "normal")
        self.assert_preserved_source()

    def test_changed_configuration_requires_reload_before_conversion(self):
        self.app.config.set(str(self.config))
        self.app._load_profiles()
        self.wait_for_worker()
        self.app.source.set(str(self.source))
        self.app.config.set(str(self.root / "different"))
        with patch.object(self.gui.messagebox, "showinfo") as info_dialog, patch.object(self.gui, "convert_project") as convert:
            self.app._convert()
        info_dialog.assert_called_once()
        self.assertIn("Load printers", info_dialog.call_args.args[1])
        convert.assert_not_called()

    def test_destroy_cancels_pending_poll_callback(self):
        # Tk interpreters on one thread share an event queue; two concurrent
        # roots can leave Cocoa's event loop blocked in the following test.
        pending_timer = self.app._drain_after_id
        self.assertIsNotNone(pending_timer)
        # Flush Tcl's own pending theme events before destroying this interpreter.
        self.window.update_idletasks()
        self.window.destroy()
        self.assertTrue(self.app._destroyed)
        self.assertIsNone(self.app._drain_after_id)
        self.assertNotIn(pending_timer, self.window.tk.call("after", "info"))


if __name__ == "__main__":
    unittest.main()
