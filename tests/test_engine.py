"""Entirely synthetic projects; no user profiles, model files or credentials."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from orca_transfer.engine import ConversionError, convert_project, default_plate_type, available_plate_types
from orca_transfer.profiles import PrinterProfile

MODEL = b'''<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
 <metadata name="Application">OrcaSlicer-2.4.1</metadata>
 <metadata name="BambuStudio:3mfVersion">1</metadata>
 <resources><object id="1" type="model"><mesh><vertices>
 <vertex x="0" y="0" z="0"/><vertex x="10" y="0" z="0"/>
 <vertex x="0" y="10" z="0"/><vertex x="0" y="0" z="10"/>
 </vertices><triangles><triangle v1="0" v2="1" v3="2" paint_color="1"/>
 <triangle v1="0" v2="1" v3="3"/><triangle v1="0" v2="2" v3="3"/>
 <triangle v1="1" v2="2" v3="3"/></triangles></mesh></object></resources>
 <build><item objectid="1" transform="1 0 0 0 1 0 0 0 1 20 20 0"/></build>
</model>'''
SETTINGS = b'''<?xml version="1.0"?><config>
<object id="1"><metadata key="extruder" value="2"/>
 <part id="1"><metadata key="wall_loops" value="6"/></part>
 <range min_z="2" max_z="4"><metadata key="layer_height" value="0.12"/></range>
</object><plate><metadata key="plater_id" value="1"/><metadata key="bed_type" value="Cool Plate"/>
<model_instance><metadata key="object_id" value="1"/><metadata key="instance_id" value="0"/></model_instance>
<metadata key="gcode_file" value="Metadata/plate_1.gcode"/></plate></config>'''


def source_config():
    return {
        'printer_settings_id': 'Source printer', 'print_settings_id': 'Authored process',
        'printer_model': 'Source model', 'printer_technology': 'FFF',
        'nozzle_diameter': ['0.4'], 'machine_start_gcode': 'SOURCE START',
        'machine_end_gcode': 'SOURCE END', 'retraction_length': ['0.3'],
        'gcode_flavor': 'marlin', 'layer_height': '0.2', 'wall_loops': '4',
        'sparse_infill_density': '18%', 'support_top_z_distance': '0.18',
        'filament_colour': ['#ABCDEF', '#FFAACC'], 'filament_type': ['PLA','TPU'],
        'filament_settings_id': ['Tuned PLA','Tuned TPU'],
        'filament_flow_ratio': ['0.98','1.03'], 'filament_max_volumetric_speed': ['15','3'],
        'nozzle_temperature': ['215','225'], 'nozzle_temperature_initial_layer': ['220','230'],
        'filament_self_index': ['1','2'],
        'filament_extruder_variant': ['Direct Drive Standard','Direct Drive Standard'],
        'filament_map': ['1','1'], 'flush_volumes_matrix': ['0','100','100','0'],
        'filament_start_gcode': ['; custom material start',''],
        'inherits_group': ['Unrelated process parent','PLA parent','TPU parent','Source parent'],
        'different_settings_to_system': ['','','',''], 'curr_bed_type': 'Cool Plate',
        'filament_retraction_length': ['nil','0.9'], 'printer_notes': 'private note',
        'printhost_apikey': 'synthetic-secret-never-export',
    }


def target_profile(**updates):
    config = {
        'name': 'Test printer', 'printer_settings_id': 'Test printer', 'inherits': 'Vendor base',
        'printer_model': 'Test model', 'printer_technology': 'FFF', 'gcode_flavor': 'klipper',
        'nozzle_diameter': ['0.4'], 'printable_area': ['0x0','200x0','200x200','0x200'],
        'printable_height': '200', 'machine_start_gcode': 'TARGET START',
        'machine_end_gcode': 'TARGET END', 'default_bed_type': 'High Temp Plate',
        'min_layer_height': ['0.08'], 'max_layer_height': ['0.3'],
        'printer_extruder_variant': ['Direct Drive Standard'], 'printer_extruder_id': ['1'],
        'print_host': 'synthetic.invalid', 'printhost_password': 'synthetic-target-secret',
    }
    config.update(updates)
    return PrinterProfile('Test printer', 'Synthetic vendor', 'default', Path('synthetic-profile.json'), config)


def make_project(path, config=None, model=MODEL, settings=SETTINGS, extra=None):
    files = {
        'Metadata/project_settings.config': json.dumps(config or source_config()).encode(),
        '3D/3dmodel.model': model,
        'Metadata/model_settings.config': settings,
        'Metadata/layer_height_profile.txt': b'1|0;0.2;10;0.12;',
        'Metadata/custom_gcode_per_layer.xml': b'<custom_gcodes><plate id="1"><layer top_z="5" type="1" extruder="2" color="#FFAACC" extra=""/></plate></custom_gcodes>',
        'Metadata/filament_sequence.json': b'{"1":{"sequence":[1,2]}}',
        'Metadata/plate_1.gcode': b'; synthetic sliced data\nM104 S999',
        '[Content_Types].xml': b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/><Override PartName="/Metadata/plate_1.gcode" ContentType="text/plain"/></Types>',
        '_rels/.rels': b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="r1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>',
    }
    if extra:
        files.update(extra)
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return files


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.source = self.folder/'authored.3mf'
        self.files = make_project(self.source)

    def output_config(self, result):
        with zipfile.ZipFile(result.path) as archive:
            return json.loads(archive.read('Metadata/project_settings.config'))

    def test_preserves_authored_data_and_source(self):
        before = self.source.read_bytes()
        result = convert_project(self.source, target_profile())
        cfg = self.output_config(result)
        original = source_config()
        for key in ('wall_loops','layer_height','filament_type','filament_flow_ratio',
                    'filament_retraction_length','nozzle_temperature','flush_volumes_matrix',
                    'filament_self_index','filament_extruder_variant','filament_settings_id'):
            self.assertEqual(cfg[key], original[key], key)
        self.assertEqual(cfg['machine_start_gcode'], 'TARGET START')
        self.assertEqual(cfg['printer_settings_id'], 'Test printer')
        self.assertEqual(cfg['inherits_group'], ['','','','Vendor base'])
        self.assertEqual(cfg['curr_bed_type'], 'High Temp Plate')
        self.assertNotIn('retraction_length', cfg)  # Source hardware cannot leak through omissions.
        self.assertEqual(before, self.source.read_bytes())
        with zipfile.ZipFile(result.path) as archive:
            for name in ('3D/3dmodel.model','Metadata/layer_height_profile.txt',
                         'Metadata/custom_gcode_per_layer.xml','Metadata/filament_sequence.json'):
                self.assertEqual(archive.read(name), self.files[name], name)
            settings = archive.read('Metadata/model_settings.config')
            self.assertIn(b'wall_loops', settings)
            self.assertIn(b'0.12', settings)
            self.assertIn(b'High Temp Plate', settings)
            self.assertNotIn('Metadata/plate_1.gcode', archive.namelist())
            self.assertNotIn(b'plate_1.gcode', archive.read('[Content_Types].xml'))
            self.assertNotIn(b'synthetic-target-secret', archive.read('Metadata/project_settings.config'))
            self.assertNotIn(b'synthetic-secret-never-export', archive.read('Metadata/project_settings.config'))
            self.assertNotIn(b'synthetic.invalid', archive.read('Metadata/project_settings.config'))
        self.assertTrue(result.warnings)

    def test_collision_never_overwrites(self):
        one = convert_project(self.source, target_profile())
        contents = one.path.read_bytes()
        two = convert_project(self.source, target_profile())
        self.assertNotEqual(one.path, two.path)
        self.assertEqual(one.path.read_bytes(), contents)

    def test_profile_unchanged(self):
        profile = target_profile()
        before = copy.deepcopy(profile.settings)
        convert_project(self.source, profile)
        self.assertEqual(before, profile.settings)

    def test_plate_requires_explicit_choice_if_missing(self):
        profile = target_profile(default_bed_type='')
        self.assertIsNone(default_plate_type(profile))
        with self.assertRaisesRegex(ConversionError, 'Select the plate'):
            convert_project(self.source, profile)
        self.assertEqual(self.output_config(convert_project(self.source, profile, plate='Textured PEI Plate'))['curr_bed_type'], 'Textured PEI Plate')

    def test_numeric_plate_default(self):
        self.assertEqual(default_plate_type(target_profile(default_bed_type='3')), 'High Temp Plate')
        self.assertEqual(available_plate_types(target_profile())[0], 'High Temp Plate')

    def test_variants_are_not_material_slots(self):
        cfg = source_config()
        cfg.update(filament_self_index=['1','1','2','2'],
                   filament_extruder_variant=['Direct Drive Standard','Direct Drive High Flow']*2,
                   filament_flow_ratio=['0.98','0.99','1.03','1.04'],
                   filament_max_volumetric_speed=['15','25','3','6'],
                   nozzle_temperature=['215','220','225','230'],
                   nozzle_temperature_initial_layer=['220','225','230','235'],
                   filament_retraction_length=['nil','nil','0.9','0.9'])
        make_project(self.source, cfg)
        out = self.output_config(convert_project(self.source, target_profile()))
        self.assertEqual(out['filament_type'], ['PLA','TPU'])
        self.assertEqual(out['filament_flow_ratio'], cfg['filament_flow_ratio'])
        self.assertEqual(out['filament_self_index'], cfg['filament_self_index'])
        self.assertEqual(len(out['inherits_group']), 4)

    def test_no_matching_variant_is_not_fabricated(self):
        with self.assertRaisesRegex(ConversionError, 'no matching source'):
            convert_project(self.source, target_profile(printer_extruder_variant=['Direct Drive High Flow']))

    def test_bad_variant_layout_rejected(self):
        cfg = source_config()
        cfg['filament_self_index'] = ['1','3']
        make_project(self.source, cfg)
        with self.assertRaisesRegex(ConversionError, 'indices'):
            convert_project(self.source, target_profile())

    def test_legacy_no_variant_metadata(self):
        cfg = source_config()
        cfg.pop('filament_self_index')
        cfg.pop('filament_extruder_variant')
        make_project(self.source, cfg)
        result = convert_project(self.source, target_profile())
        self.assertEqual(self.output_config(result)['filament_type'], ['PLA','TPU'])

    def test_different_nozzle_diameter_rejected(self):
        with self.assertRaisesRegex(ConversionError, 'diameters differ'):
            convert_project(self.source, target_profile(nozzle_diameter=['0.6']))

    def test_other_matching_diameter_supported(self):
        cfg = source_config()
        cfg['nozzle_diameter'] = ['0.6']
        make_project(self.source, cfg)
        self.assertTrue(convert_project(self.source, target_profile(nozzle_diameter=['0.6'])).path.exists())

    def test_multiple_physical_nozzles_rejected(self):
        with self.assertRaisesRegex(ConversionError, 'one physical nozzle'):
            convert_project(self.source, target_profile(nozzle_diameter=['0.4','0.4']))

    def test_resin_rejected(self):
        with self.assertRaisesRegex(ConversionError, 'resin'):
            convert_project(self.source, target_profile(printer_technology='SLA'))

    def test_missing_geometry_rejected(self):
        with zipfile.ZipFile(self.source, 'w') as archive:
            archive.writestr('Metadata/project_settings.config', '{}')
        with self.assertRaisesRegex(ConversionError, 'lacks editable'):
            convert_project(self.source, target_profile())

    def test_sliced_file_rejected(self):
        path = self.folder/'already.gcode.3mf'
        path.write_bytes(self.source.read_bytes())
        with self.assertRaisesRegex(ConversionError, 'editable'):
            convert_project(path, target_profile())

    def test_local_invalid_material_assignment(self):
        make_project(self.source, settings=SETTINGS.replace(b'value="2"', b'value="3"'))
        with self.assertRaisesRegex(ConversionError, 'assignment'):
            convert_project(self.source, target_profile())

    def test_multiple_plates_rejected(self):
        make_project(self.source, settings=SETTINGS.replace(b'</config>', b'<plate/></config>'))
        with self.assertRaisesRegex(ConversionError, 'Multi-plate'):
            convert_project(self.source, target_profile())

    def test_unsafe_zip_path(self):
        make_project(self.source, extra={'../outside': b'x'})
        with self.assertRaisesRegex(ConversionError, 'unsafe'):
            convert_project(self.source, target_profile())

    def test_case_collision(self):
        make_project(self.source, extra={'metadata/PROJECT_settings.config': b'{}'})
        with self.assertRaisesRegex(ConversionError, 'case-colliding'):
            convert_project(self.source, target_profile())

    def test_xml_entity_rejected(self):
        make_project(self.source, model=b'<!DOCTYPE model [<!ENTITY x "bad">]><model/>')
        with self.assertRaisesRegex(ConversionError, 'entities'):
            convert_project(self.source, target_profile())

    def test_duplicate_json_rejected(self):
        make_project(self.source, extra={'Metadata/project_settings.config': b'{"x":1,"x":2}'})
        with self.assertRaises(ConversionError):
            convert_project(self.source, target_profile())

    def test_outside_xy_rejected_without_output(self):
        with self.assertRaisesRegex(ConversionError, 'does not fit'):
            convert_project(self.source, target_profile(printable_area=['0x0','25x0','25x25','0x25']))
        self.assertEqual(list(self.folder.iterdir()), [self.source])

    def test_outside_height_rejected(self):
        with self.assertRaisesRegex(ConversionError, 'does not fit'):
            convert_project(self.source, target_profile(printable_height='5'))

    def test_bed_exclusion_rejected(self):
        with self.assertRaisesRegex(ConversionError, 'exclusion'):
            convert_project(self.source, target_profile(bed_exclude_area=['21x21','24x21','24x24','21x24']))

    def test_concave_notch_crossing_bbox_rejected(self):
        with self.assertRaisesRegex(ConversionError, 'Concave'):
            convert_project(self.source, target_profile(printable_area=['0x0','200x0','200x200','26x200','26x5','24x5','24x200','0x200']))

    def test_zero_based_physical_map_supported(self):
        cfg = source_config()
        cfg['physical_extruder_map'] = ['0']
        make_project(self.source, cfg)
        self.assertTrue(convert_project(self.source, target_profile(physical_extruder_map=['0'])).path.exists())

    def test_auto_max_layer_height_supported(self):
        self.assertTrue(convert_project(self.source, target_profile(max_layer_height=['0'])).path.exists())

    def test_source_refresh_token_removed(self):
        cfg = source_config()
        cfg['refresh_token'] = 'SYNTHETIC_REFRESH_SECRET'
        make_project(self.source, cfg)
        self.assertNotIn('refresh_token', self.output_config(convert_project(self.source, target_profile())))

    def test_hardware_project_selectors_use_target_without_changing_materials(self):
        cfg = source_config()
        cfg.update(nozzle_volume_type=['High Flow'], extruder_ams_count=['synthetic feeder inventory'])
        make_project(self.source, cfg)
        output = self.output_config(convert_project(self.source, target_profile(default_nozzle_volume_type=['Standard'])))
        self.assertEqual(output['nozzle_volume_type'], ['Standard'])
        self.assertNotIn('extruder_ams_count', output)
        self.assertEqual(output['filament_settings_id'], cfg['filament_settings_id'])

    def test_nested_component_transform_preserved(self):
        extra = '<object id="2"><components><component objectid="1" transform="1 0 0 0 1 0 0 0 1 5 0 0"/></components></object>'
        model = MODEL.replace(b'</resources>', extra.encode()+b'</resources>').replace(b'<item objectid="1"', b'<item objectid="2"')
        make_project(self.source, model=model)
        out = convert_project(self.source, target_profile())
        with zipfile.ZipFile(out.path) as archive:
            self.assertEqual(archive.read('3D/3dmodel.model'), model)

    def test_cyclic_components_rejected(self):
        model = MODEL.replace(b'<mesh>', b'<components><component objectid="1"/></components><mesh>')
        make_project(self.source, model=model)
        with self.assertRaisesRegex(ConversionError, 'Cyclic'):
            convert_project(self.source, target_profile())

    def test_unknown_target_hardware_rejected(self):
        with self.assertRaisesRegex(ConversionError, 'unrecognized printer'):
            convert_project(self.source, target_profile(future_toolchanger='1'))

    def test_source_changed_during_conversion_has_no_output(self):
        with patch('orca_transfer.engine._hash_file', side_effect=['before','after']):
            with self.assertRaisesRegex(ConversionError, 'changed during'):
                convert_project(self.source, target_profile())
        self.assertEqual(list(self.folder.iterdir()), [self.source])

    def test_no_private_profile_data_in_result(self):
        result = convert_project(self.source, target_profile())
        self.assertNotIn('synthetic-target-secret', repr(result))
        self.assertNotIn('synthetic-target-secret', json.dumps(self.output_config(result)))


if __name__ == '__main__':
    unittest.main()
