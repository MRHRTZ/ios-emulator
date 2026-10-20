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
