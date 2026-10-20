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
