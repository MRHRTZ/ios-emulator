import importlib.util
from pathlib import Path
import plistlib
import tempfile
import unittest
import zipfile

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('emulator', root / 'emulator.py')
emulator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(emulator)


class ManifestTargetTests(unittest.TestCase):
    def test_wrong_board_cannot_be_silently_selected(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / 'wrong.ipsw'
            with zipfile.ZipFile(archive, 'w') as output:
                output.writestr('BuildManifest.plist', plistlib.dumps({'BuildIdentities': [
                    {'Info': {'DeviceClass': 'anotherboard'}, 'Manifest': {}}]}))
            with self.assertRaisesRegex(ValueError, 'D22AP'):
                emulator.manifest_info(archive)

    def test_empty_identities_reports_missing_target(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / 'empty.ipsw'
            with zipfile.ZipFile(archive, 'w') as output:
                output.writestr('BuildManifest.plist', plistlib.dumps({'BuildIdentities': []}))
            with self.assertRaisesRegex(ValueError, 'D22AP'):
                emulator.manifest_info(archive)


if __name__ == '__main__':
    unittest.main()


class GuestStatusTests(unittest.TestCase):
    def test_static_test_and_exec_attempt_are_not_apple_boot(self):
        for text in ['*** SWEET userspace: init running as PID 1 ***',
                     'load_init_program: attempting to load /sbin/launchd\nexec SpringBoard\n']:
            self.assertFalse(emulator.guest_status(text)['apple_userland_started'])

    def test_apple_early_boot_and_springboard_are_distinct_milestones(self):
        text = 'com.apple.xpc.launchd| UUID...\nEarly boot complete. Continuing system boot.\n'
        status = emulator.guest_status(text)
        self.assertTrue(status['apple_userland_started'])
        self.assertFalse(status['springboard_exec_observed'])
        self.assertTrue(emulator.guest_status(text + 'exec SpringBoard\r\n')['springboard_exec_observed'])

    def test_panic_remains_visible_after_early_boot(self):
        text = 'com.apple.xpc.launchd| Early boot complete. Continuing system boot.\npanic(cpu 0 caller ...\n'
        self.assertTrue(emulator.guest_status(text)['kernel_panic_observed'])

    def test_display_pipeline_detected_from_backboardd_surface_and_swap(self):
        base = 'com.apple.xpc.launchd| Early boot complete. Continuing system boot.\nexec SpringBoard\n'
        self.assertFalse(emulator.guest_status(base)['display_pipeline_active'])
        for marker in ['SWEET SURF: backboardd create id 2\n',
                       'SWEET FB: backboardd sel 55 in 1/72 out 0/0 -> 0x0\n',
                       'SWEET FB: swap 2 layer 0 surface 2\n']:
            status = emulator.guest_status(base + marker)
            self.assertTrue(status['display_pipeline_active'])
            self.assertTrue(status['springboard_exec_observed'])


if __name__ == '__main__':
    unittest.main()


class ExtractionIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name);self.archive=self.directory/'fixture.ipsw'
        self.roles=('OS','Cryptex1,SystemOS','Cryptex1,AppOS','DeviceTree')
        self.components={role:{'Info':{'Path':f'part{i}.bin'}} for i,role in enumerate(self.roles)}

    def write_archive(self, build='20H392', components=None):
        manifest={'ProductVersion':'16.7.16','ProductBuildVersion':build,
                  'SupportedProductTypes':['iPhone10,3'], 'BuildIdentities':[
                      {'Info':{'DeviceClass':'d22ap'},'Manifest':components or self.components}]}
        with zipfile.ZipFile(self.archive,'w',compression=zipfile.ZIP_STORED) as z:
            z.writestr('BuildManifest.plist',plistlib.dumps(manifest))
            for i in range(4):z.writestr(f'part{i}.bin',b'fixture-component-'+bytes([65+i])*16)

    def test_complete_extraction_checks_existing_crc(self):
        from unittest.mock import patch
        self.write_archive()
        with patch.object(emulator,'ROOT',self.directory):
            emulator.extract(self.archive)
            folder=self.directory/'data/extracted/20H392'
            self.assertTrue((folder/'manifest.json').exists())
            emulator.extract(self.archive)
            (folder/'part1.bin').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'differs'):
                emulator.extract(self.archive)
            self.assertFalse((folder/'manifest.json').exists())

    def test_bad_build_identifier_creates_no_destination(self):
        from unittest.mock import patch
        self.write_archive(build='../outside')
        with patch.object(emulator,'ROOT',self.directory):
            with self.assertRaisesRegex(ValueError,'build identifier'):emulator.extract(self.archive)
        self.assertFalse((self.directory/'data').exists())

    def test_duplicate_basename_and_missing_zip_member_rejected(self):
        self.write_archive()
        for path,message in [('other/part0.bin','conflicting'),('missing.bin','missing'),('../part.bin','unsafe')]:
            parts={role:{'Info':dict(value['Info'])} for role,value in self.components.items()}
            parts['DeviceTree']['Info']['Path']=path
            self.write_archive(components=parts)
            with self.assertRaisesRegex(ValueError,message):emulator.manifest_info(self.archive)

    def test_crc_failure_never_promotes_partial_component(self):
        from unittest.mock import patch
        self.write_archive()
        with zipfile.ZipFile(self.archive) as z:
            offset=z.getinfo('part0.bin').header_offset
        data=bytearray(self.archive.read_bytes())
        import struct
        name_len,extra_len=struct.unpack_from('<HH',data,offset+26)
        data[offset+30+name_len+extra_len]^=1
        self.archive.write_bytes(data)
        with patch.object(emulator,'ROOT',self.directory):
            with self.assertRaises(zipfile.BadZipFile):emulator.extract(self.archive)
        folder=self.directory/'data/extracted/20H392'
        self.assertFalse((folder/'part0.bin').exists())
        self.assertFalse((folder/'part0.bin.part').exists())
        self.assertFalse((folder/'manifest.json').exists())

    def test_malformed_identity_container_is_reported_cleanly(self):
        for malformed in ({}, ['bad'], [{'Info':[]} ]):
            with zipfile.ZipFile(self.archive,'w') as z:
                z.writestr('BuildManifest.plist',plistlib.dumps({'BuildIdentities':malformed}))
            with self.assertRaisesRegex(ValueError,'malformed build identities'):
                emulator.manifest_info(self.archive)
