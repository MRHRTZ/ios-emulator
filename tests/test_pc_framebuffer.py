from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from pc_framebuffer import mapped_address, WindowsFramebuffer
from pc_session import PcSession, VIDEO_MAGIC


class FramebufferTransportTests(unittest.TestCase):
    def test_mapping_parser_requires_the_requested_guest_address(self):
        qmp = SimpleNamespace(call=Mock(return_value=
            'Host virtual address for 0x9c000000 (mach-virt.ram) is 000001d068700000\r\n'))
        self.assertEqual(mapped_address(qmp, 0x9c000000), 0x1d068700000)
        qmp.call.return_value = 'Host virtual address for 0x40000000 (ram) is 0x12345678\n'
        with self.assertRaises(OSError): mapped_address(qmp, 0x9c000000)
        qmp.call.return_value = 'Error: not RAM'
        with self.assertRaises(OSError): mapped_address(qmp, 0x9c000000)

    def test_noncontiguous_framebuffer_is_rejected_before_open_process(self):
        with patch('pc_framebuffer.mapped_address', side_effect=[0x1000, 0x2000]):
            with self.assertRaisesRegex(OSError, 'not contiguous'):
                WindowsFramebuffer(123, None, 0x9c000000, 4)

    def test_inflight_copy_during_read_is_discarded_then_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            session = PcSession(folder)
            before = [VIDEO_MAGIC, 2, 1, 20, 1, 1, 4, 0]
            after = [VIDEO_MAGIC, 3, 1, 20, 1, 1, 4, 0]
            session.qtest = SimpleNamespace(read=Mock(side_effect=[
                struct.pack('<8I', *before), struct.pack('<8I', *after),
                struct.pack('<8I', *before), struct.pack('<8I', *before)]))
            session.frame_reader = SimpleNamespace(read=Mock(return_value=b'abcd'),close=Mock())
            with patch('pc_session.FB_WIDTH', 1), patch('pc_session.FB_HEIGHT', 1):
                self.assertIsNone(session.frame())
                self.assertIsNone(session.last_video_frame)
                self.assertEqual(session.exported_frames, 0)
                self.assertEqual(session.frame(), b'abcd')
                self.assertEqual(session.last_video_frame, 1)
                self.assertEqual(session.exported_frames, 1)
            self.assertIsNone(session.frame_directory)

    def test_failed_direct_read_closes_handle_and_falls_back(self):
        with tempfile.TemporaryDirectory() as folder:
            session = PcSession(folder)
            reader = SimpleNamespace(read=Mock(side_effect=OSError('incomplete')), close=Mock())
            session.frame_reader = reader
            def export(command, **args): Path(args['filename']).write_bytes(b'abcd')
            session.qmp = SimpleNamespace(call=export)
            with patch('pc_session.FB_WIDTH', 1), patch('pc_session.FB_HEIGHT', 1):
                self.assertEqual(session.frame(), b'abcd')
            reader.close.assert_called_once()
            self.assertIsNone(session.frame_reader)
            self.assertIn('QMP file export', session.frame_transport)
            session.frame_directory.cleanup()
