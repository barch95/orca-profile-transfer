"""Synthetic profile/account fixtures; never reads an installed Orca profile."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from orca_transfer import profiles
from orca_transfer.profiles import ProfileError, load_printer_profiles


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / "config"
        self.config.mkdir()
        self.resources = self.root / "resources"
        self.resources.mkdir()
        # Integration tests must not discover this machine's real installation.
        resource_patch = patch.object(profiles, "_resource_dirs", side_effect=lambda config, explicit: [explicit] if explicit else [])
        resource_patch.start()
        self.addCleanup(resource_patch.stop)

    def write(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    def conf(self, active="default", models=None):
        self.write(self.config / "OrcaSlicer.conf", {"app": {"preset_folder": active}, "models": models or []})

    def user(self, name="Saved Printer", parent="Acme Printer 0.4", account="default", **values):
        data = {"name": name, "type": "machine", "inherits": parent, **values}
        self.write(self.config / "user" / account / "machine" / f"{name}.json", data)

    def vendor(self, vendor="Acme", root=None, records=None, models=None):
        root = root or self.config / "system"
        records = records or [
            {"name": "fdm_machine_common", "instantiation": "false", "nozzle_diameter": ["0.4"], "printable_height": "250", "default_bed_type": "Smooth PEI Plate"},
            {"name": "Acme Printer 0.4", "inherits": "fdm_machine_common", "instantiation": "true", "printer_model": "Acme Model", "printer_variant": "0.4"},
        ]
        self.write(root / f"{vendor}.json", {
            "name": vendor,
            "machine_model_list": [{"name": name} for name in (models or ["Acme Model"])],
            "machine_list": [{"name": r["name"], "sub_path": f"machine/{i}.json"} for i, r in enumerate(records)],
        })
        for i, record in enumerate(records):
            self.write(root / vendor / "machine" / f"{i}.json", {"type": "machine", **record})

    def test_resolves_user_chain_and_retains_immediate_identity(self):
        self.vendor()
        self.user("Tuned Base", machine_max_speed_x=["200"])
        self.user("My Printer", parent="Tuned Base", nozzle_diameter=["0.6"])
        found = {p.name: p for p in load_printer_profiles(self.config)}
        preset = found["My Printer"]
        self.assertEqual(preset.vendor, "Acme")
        self.assertEqual(preset.settings["inherits"], "Tuned Base")
        self.assertEqual(preset.settings["printer_settings_id"], "My Printer")
        self.assertEqual(preset.settings["nozzle_diameter"], ["0.6"])
        self.assertEqual(preset.settings["printable_height"], "250")
        self.assertEqual(preset.settings["machine_max_speed_x"], ["200"])

    def test_only_active_account_is_used(self):
        self.vendor()
        self.user(account="cloud_one", nozzle_diameter=["0.6"])
        self.user(account="cloud_two", nozzle_diameter=["0.8"])
        self.conf("cloud_one")
        found = load_printer_profiles(self.config)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].settings["nozzle_diameter"], ["0.6"])
        self.assertNotIn("cloud_one", found[0].display_label)
        self.assertNotIn(str(self.root), found[0].display_label)

    def test_explicit_account_override(self):
        self.vendor()
        self.user(account="cloud_one", nozzle_diameter=["0.6"])
        self.user(account="cloud_two", nozzle_diameter=["0.8"])
        self.conf("cloud_one")
        found = load_printer_profiles(self.config, account="cloud_two")
        self.assertEqual(found[0].settings["nozzle_diameter"], ["0.8"])

    def test_empty_config_account_means_default_not_other_account(self):
        self.vendor()
        self.user(account="cloud_one")
        self.conf("")
        with self.assertRaisesRegex(ProfileError, "No saved or enabled"):
            load_printer_profiles(self.config)

    def test_missing_config_ambiguous_accounts_requires_selection(self):
        self.user(parent="", account="cloud_one")
        self.user(parent="", account="cloud_two")
        with self.assertRaisesRegex(ProfileError, "multiple accounts"):
            load_printer_profiles(self.config)

    def test_account_path_traversal_rejected_on_all_operating_systems(self):
        for account in ("../elsewhere", "..\\elsewhere", "/absolute", "C:relative", ".", "..", "name."):
            with self.subTest(account=account), self.assertRaisesRegex(ProfileError, "not a path"):
                load_printer_profiles(self.config, account=account)

    def test_cross_vendor_common_parents_stay_with_the_vendor(self):
        self.vendor()
        self.vendor("Other", records=[
            {"name": "fdm_machine_common", "printable_height": "999", "instantiation": "false"},
            {"name": "Other Printer", "inherits": "fdm_machine_common", "printer_model": "Other Model"},
        ], models=["Other Model"])
        self.user(parent="Other Printer")
        preset = load_printer_profiles(self.config)[0]
        self.assertEqual(preset.vendor, "Other")
        self.assertEqual(preset.settings["printable_height"], "999")

    def test_ambiguous_user_parent_never_uses_first_vendor(self):
        self.vendor()
        self.vendor("Other")
        self.user()
        with self.assertRaisesRegex(ProfileError, "ambiguous parent"):
            load_printer_profiles(self.config)

    def test_explicit_model_disambiguates_parent(self):
        self.vendor()
        self.vendor("Other", models=["Other Model"])
        self.user(printer_model="Other Model")
        self.assertEqual(load_printer_profiles(self.config)[0].vendor, "Other")

    def test_installed_bundle_overrides_resources_as_whole(self):
        self.vendor(root=self.resources)
        self.vendor(records=[{"name": "Acme Printer 0.4", "inherits": "fdm_machine_common"}])
        self.user()
        with self.assertRaisesRegex(ProfileError, "missing parent"):
            load_printer_profiles(self.config, self.resources)

    def test_resources_can_supply_absent_vendor(self):
        self.vendor(root=self.resources)
        self.user()
        found = load_printer_profiles(self.config, self.resources)
        self.assertEqual(found[0].settings["printable_height"], "250")

    def test_legacy_aliases_normalize_before_inheritance(self):
        self.vendor(records=[{"name": "Acme Printer 0.4", "extruder_clearance_radius": "20", "machine_tool_change_time": "10"}])
        self.user(extruder_clearance_max_radius="30", machine_switch_extruder_time="15")
        settings = load_printer_profiles(self.config)[0].settings
        self.assertEqual(settings["extruder_clearance_radius"], "30")
        self.assertEqual(settings["machine_tool_change_time"], "15")
        self.assertNotIn("extruder_clearance_max_radius", settings)
        self.assertNotIn("machine_switch_extruder_time", settings)

    def test_canonical_key_wins_over_alias_in_same_record(self):
        self.user(parent="", extruder_clearance_radius="40", extruder_clearance_max_radius="30")
        settings = load_printer_profiles(self.config)[0].settings
        self.assertEqual(settings["extruder_clearance_radius"], "40")

    def test_only_known_ignored_vendor_fields_are_removed(self):
        self.user(parent="", auto_toolchange_command="T", bed_texture_area=["0x0"], support_multi_filament="1", future_hardware_option="1")
        settings = load_printer_profiles(self.config)[0].settings
        self.assertFalse(profiles._IGNORED_VENDOR_FIELDS & settings.keys())
        self.assertEqual(settings["future_hardware_option"], "1")

    def test_renamed_system_parent_is_resolved_and_canonicalized(self):
        self.vendor(records=[{"name": "Current Printer", "renamed_from": "Old Printer;Older Printer", "printable_height": "250"}])
        self.user(parent="Older Printer")
        preset = load_printer_profiles(self.config)[0]
        self.assertEqual(preset.settings["inherits"], "Current Printer")
        self.assertEqual(preset.settings["printable_height"], "250")

    def test_ambiguous_renamed_parent_rejected(self):
        self.vendor(records=[{"name": "Current Printer", "renamed_from": "Old Printer"}])
        self.vendor("Other", records=[{"name": "Other Current Printer", "renamed_from": "Old Printer"}])
        self.user(parent="Old Printer")
        with self.assertRaisesRegex(ProfileError, "ambiguous parent"):
            load_printer_profiles(self.config)

    def test_nullable_overrides_are_rejected_instead_of_guessed(self):
        self.vendor()
        for value in (None, [None, "2"], ["nil", "2"], ["null", "2"]):
            with self.subTest(value=value):
                self.user(retraction_length=value)
                with self.assertRaisesRegex(ProfileError, "nil/null"):
                    load_printer_profiles(self.config)

    def test_reordered_user_extruder_variants_are_rejected(self):
        self.vendor(records=[{"name": "Acme Printer 0.4", "printer_extruder_id": ["1", "1"], "printer_extruder_variant": ["Standard", "High Flow"]}])
        self.user(printer_extruder_variant=["High Flow", "Standard"])
        with self.assertRaisesRegex(ProfileError, "extruder variant layout"):
            load_printer_profiles(self.config)

    def test_duplicate_json_keys_rejected(self):
        (self.config / "OrcaSlicer.conf").write_text('{"app": {}, "app": {}}', encoding="utf-8")
        with self.assertRaisesRegex(ProfileError, "duplicate JSON keys"):
            load_printer_profiles(self.config)

    def test_cycle_is_actionable_error(self):
        self.user("One", parent="Two")
        self.user("Two", parent="One")
        with self.assertRaisesRegex(ProfileError, "cycle"):
            load_printer_profiles(self.config)

    def test_duplicate_user_names_rejected(self):
        self.user(parent="")
        self.write(self.config / "user/default/machine/duplicate.json", {"name": "Saved Printer"})
        with self.assertRaisesRegex(ProfileError, "duplicate printer"):
            load_printer_profiles(self.config)

    def test_same_name_user_override_resolves_system_parent(self):
        self.vendor()
        self.user("Acme Printer 0.4", parent="Acme Printer 0.4", nozzle_diameter=["0.8"])
        found = load_printer_profiles(self.config)
        self.assertEqual(found[0].settings["nozzle_diameter"], ["0.8"])

    def test_connection_and_sync_fields_removed_from_memory(self):
        self.vendor()
        self.user(print_host="private.invalid", printhost_password="synthetic-secret", user_id="synthetic-account", setting_id="synthetic-id", machine_start_gcode="G28", host_type="duet", printhost_authorization_type="user")
        found = load_printer_profiles(self.config)
        self.assertFalse(set(found[0].settings) & (profiles.CONNECTION_KEYS | profiles._PRIVATE_METADATA))
        self.assertEqual(found[0].settings["machine_start_gcode"], "G28")
        self.assertEqual(found[0].settings["host_type"], "duet")
        self.assertEqual(found[0].settings["printhost_authorization_type"], "user")
        self.assertNotIn("synthetic-secret", repr(found[0]))

    def test_enabled_stock_profiles_use_vendor_model_variant(self):
        self.vendor()
        self.conf(models=[{"vendor": "Acme", "model": "Acme Model", "nozzle_diameter": "0.4;0.6"}])
        found = load_printer_profiles(self.config)
        self.assertEqual([p.name for p in found], ["Acme Printer 0.4"])
        self.assertEqual(found[0].account, "")
        self.assertEqual(found[0].settings["default_bed_type"], "Smooth PEI Plate")

    def test_disabled_stock_profiles_not_offered(self):
        self.vendor()
        self.conf(models=[{"vendor": "Other", "model": "Acme Model", "nozzle_diameter": "0.4"}])
        with self.assertRaisesRegex(ProfileError, "No saved or enabled"):
            load_printer_profiles(self.config)

    def test_checksum_config_and_utf8_bom(self):
        self.vendor()
        self.user()
        text = json.dumps({"app": {"preset_folder": "default"}}) + "\n# MD5 checksum " + "0" * 32 + "\n"
        (self.config / "OrcaSlicer.conf").write_text(text, encoding="utf-8-sig")
        self.assertEqual(len(load_printer_profiles(self.config)), 1)

    def test_invalid_json_error_does_not_disclose_contents_or_path(self):
        (self.config / "OrcaSlicer.conf").write_text('{"password": "synthetic-secret"', encoding="utf-8")
        with self.assertRaises(ProfileError) as caught:
            load_printer_profiles(self.config)
        self.assertNotIn("synthetic-secret", str(caught.exception))
        self.assertNotIn(str(self.root), str(caught.exception))

    def test_manifest_path_escape_rejected(self):
        self.write(self.config / "system/Acme.json", {"machine_list": [{"name": "Bad", "sub_path": "../../private.json"}]})
        with self.assertRaisesRegex(ProfileError, "outside its bundle"):
            load_printer_profiles(self.config)

    def test_logical_material_variants_not_flattened(self):
        self.user(parent="", printer_extruder_id=["1", "1"], printer_extruder_variant=["Direct Drive Standard", "Direct Drive High Flow"], nozzle_diameter=["0.4"])
        found = load_printer_profiles(self.config)
        self.assertEqual(found[0].settings["printer_extruder_id"], ["1", "1"])
        self.assertEqual(len(found[0].settings["nozzle_diameter"]), 1)

    def test_loader_is_read_only(self):
        self.vendor()
        self.user()
        self.conf()
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        load_printer_profiles(self.config)
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)


class DiscoveryTests(unittest.TestCase):
    def test_windows_roaming_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "OrcaSlicer/user").mkdir(parents=True)
            with patch.object(profiles.sys, "platform", "win32"), patch.object(profiles.Path, "home", return_value=root), patch.dict(os.environ, {"APPDATA": str(root)}, clear=True), patch.object(profiles.shutil, "which", return_value=None):
                self.assertEqual(profiles.discover_config_dirs(), [(root / "OrcaSlicer").resolve()])

    def test_linux_xdg_and_flatpak(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            xdg = home / "configuration"
            flatpak = home / ".var/app/com.orcaslicer.OrcaSlicer/config/OrcaSlicer"
            (xdg / "OrcaSlicer/user").mkdir(parents=True)
            (flatpak / "user").mkdir(parents=True)
            with patch.object(profiles.sys, "platform", "linux"), patch.object(profiles.Path, "home", return_value=home), patch.dict(os.environ, {"XDG_CONFIG_HOME": str(xdg)}, clear=True), patch.object(profiles.shutil, "which", return_value=None):
                self.assertEqual(profiles.discover_config_dirs(), [(xdg / "OrcaSlicer").resolve(), flatpak.resolve()])

    def test_macos_application_support(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            expected = home / "Library/Application Support/OrcaSlicer"
            (expected / "user").mkdir(parents=True)
            with patch.object(profiles.sys, "platform", "darwin"), patch.object(profiles.Path, "home", return_value=home), patch.dict(os.environ, {}, clear=True), patch.object(profiles.shutil, "which", return_value=None):
                self.assertEqual(profiles.discover_config_dirs(), [expected.resolve()])

    def test_explicit_resources_accepts_installation_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = root / "resources/profiles/Acme.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text("{}", encoding="utf-8")
            self.assertEqual(profiles._resource_dirs(root / "data_dir", root), [manifest.parent.resolve()])

    def test_invalid_explicit_resource_directory_is_explained(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ProfileError, "no vendor manifests"):
                profiles._resource_dirs(Path(temporary), Path(temporary))


if __name__ == "__main__":
    unittest.main()
