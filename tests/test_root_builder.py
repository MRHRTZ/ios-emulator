import struct
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import root_builder
import mkadt


class PreparedRootTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / 'data/root'
        self.base.mkdir(parents=True)
        self.staging = self.base / 'ios-root-build.img'
        self.staging.write_bytes(bytes(4096))

    def header(self, clean=True, free=2):
        with self.staging.open('r+b') as stream:
            stream.seek(1024)
            data = bytearray(512)
            data[:2] = b'HX'
            struct.pack_into('>I', data, 4, 0x100 if clean else 0)
            struct.pack_into('>3I', data, 40, 512, 8, free)
            stream.write(data)

    def test_rejects_invalid_volume_geometry(self):
        self.header(free=9)
        with self.assertRaises(ValueError):
            root_builder.hfs_header(self.staging)

    def test_success_text_alone_cannot_publish_dirty_root(self):
        self.header(clean=False)
        with patch.object(root_builder, 'DISK_BYTES', 4096):
            with self.assertRaises(ValueError):
                root_builder.promote(self.root, 'ROOT_BUILD_OK\n')
        self.assertTrue(self.staging.exists())
        self.assertFalse((self.base / 'ready.json').exists())

    def test_requires_complete_success_marker(self):
        self.header()
        with self.assertRaises(ValueError):
            root_builder.promote(self.root, 'echo ROOT_BUILD_OK\nROOT_BUILD_FAILED\n')

    def test_clean_success_promotes_without_overwriting(self):
        self.header()
        with patch.object(root_builder, 'DISK_BYTES', 4096):
            output = root_builder.promote(self.root, '\r\nROOT_BUILD_OK\r\n')
        self.assertTrue(output.exists())
        self.assertFalse(self.staging.exists())
        self.assertTrue((self.base / 'ready.json').exists())
        self.staging.write_bytes(bytes(4096))
        self.header()
        before = output.read_bytes()
        with patch.object(root_builder, 'DISK_BYTES', 4096):
            with self.assertRaises(ValueError):
                root_builder.promote(self.root, 'ROOT_BUILD_OK\n')
        self.assertEqual(output.read_bytes(), before)


class QemuTreeTests(unittest.TestCase):
    def test_pc_storage_uart_and_memory_match_hardware(self):
        with patch.object(mkadt, 'd22ap_product', return_value=None):
            tree = mkadt.build(qemu=True, memory_mib=2048)
        children = {child.name: child for child in tree.children}
        props = lambda n: {key: value for key, _, value in n.props}
        self.assertEqual(props(children['chosen'])['dram-size'], struct.pack('<Q', 2048 * 1024**2))
        self.assertEqual(props(children['sweet-virtio'])['reg'], struct.pack('<QQ', 0x0a000000, 0x4000))
        uart = next(child for child in children['arm-io'].children if child.name == 'uart0')
        self.assertEqual(props(uart)['reg'], struct.pack('<QQ', 0x08000000, 0x1000))
        self.assertNotIn('ufs', children)

    def test_invalid_memory_rejected(self):
        for args in ({'qemu': True, 'memory_mib': 4097}, {'memory_mib': 1024}):
            with self.assertRaises(ValueError):
                mkadt.build(**args)
