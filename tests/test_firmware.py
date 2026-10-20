import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import firmware


class Reply(io.BytesIO):
    def __init__(self, data, status=200, **headers):
        super().__init__(data)
        self.status = status
        self.headers = headers
        self.url = 'https://updates.cdn-apple.com/test.ipsw'


class DownloadIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.partial = Path(self.directory.name) / 'test.ipsw.part'

    def test_range_ignored_restarts_instead_of_appending(self):
        self.partial.write_bytes(b'abc')
        with patch.object(firmware, 'urlopen', return_value=Reply(b'abcdef', **{'Content-Length': '6'})):
            firmware.receive('https://updates.cdn-apple.com/test.ipsw', self.partial, 6, lambda *a: None)
        self.assertEqual(self.partial.read_bytes(), b'abcdef')

    def test_valid_range_resumes(self):
        self.partial.write_bytes(b'abc')
        reply = Reply(b'def', 206, **{'Content-Range': 'bytes 3-5/6', 'Content-Length': '3'})
        with patch.object(firmware, 'urlopen', return_value=reply) as request:
            firmware.receive('https://updates.cdn-apple.com/test.ipsw', self.partial, 6, lambda *a: None)
        self.assertEqual(request.call_args.args[0].headers['Range'], 'bytes=3-')
        self.assertEqual(self.partial.read_bytes(), b'abcdef')

    def test_wrong_range_does_not_modify_partial(self):
        self.partial.write_bytes(b'abc')
        with patch.object(firmware, 'urlopen', return_value=Reply(b'xx', 206, **{'Content-Range': 'bytes 4-5/6'})):
            with self.assertRaises(ValueError):
                firmware.receive('https://updates.cdn-apple.com/test.ipsw', self.partial, 6, lambda *a: None)
        self.assertEqual(self.partial.read_bytes(), b'abc')

    def test_truncated_transfer_is_resumable(self):
        with patch.object(firmware, 'urlopen', return_value=Reply(b'abc')):
            with self.assertRaises(OSError):
                firmware.receive('https://updates.cdn-apple.com/test.ipsw', self.partial, 6, lambda *a: None)
        self.assertEqual(self.partial.read_bytes(), b'abc')

    def test_wrong_checksum_never_marks_download_ready(self):
        entry = dict(url='https://updates.cdn-apple.com/test.ipsw', version='16.7.16',
                     buildid='20H392', filesize=6, sha256sum='0' * 64)
        with patch.object(firmware, 'select_firmware', return_value=entry), \
             patch.object(firmware, 'urlopen', return_value=Reply(b'abcdef')):
            with self.assertRaises(ValueError):
                firmware.download(Path(self.directory.name))
        self.assertFalse((Path(self.directory.name) / 'test.ipsw').exists())
        self.assertTrue(self.partial.exists())
        self.assertIn('"phase": "error"', (Path(self.directory.name) / 'progress.json').read_text())


if __name__ == '__main__':
    unittest.main()
