import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest

from pc_diagnostics import VisualRate, system_information, PipelineRates, PIPELINE_MAGIC


class DisplayMeasurementTests(unittest.TestCase):
    def test_auto_uses_only_hardware_gl_and_vulkan_is_not_silently_accepted(self):
        from pc_renderer import resolve_renderer
        self.assertEqual(resolve_renderer('Auto', {'available':True,'hardware':True}), 'OpenGL')
        self.assertEqual(resolve_renderer('Auto', {'available':True,'hardware':False}), 'Software')
        self.assertEqual(resolve_renderer('Software', {'available':True,'hardware':True}), 'Software')
        self.assertEqual(resolve_renderer('OpenGL', {'available':False}), 'Software')
        with self.assertRaisesRegex(ValueError, 'not implemented'):
            resolve_renderer('Vulkan', {'available':True,'hardware':True})

    def test_wheel_swipe_is_bounded_and_does_not_overlap_contact(self):
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QPoint, QPointF
        from emulator_gui import Screen
        from unittest.mock import Mock
        app = QApplication.instance() or QApplication([])
        screen = Screen(); screen.resize(540,1200); screen.enabled_input = True
        event = SimpleNamespace(position=lambda:QPointF(270,600),
            angleDelta=lambda:QPoint(0,-120), pixelDelta=lambda:QPoint(), accept=Mock(),ignore=Mock())
        gestures=[]
        screen.swipe.connect(lambda *args:gestures.append(args))
        screen.wheelEvent(event)
        self.assertEqual(gestures,[(540,1200,540,600,.35,0.)])
        screen.down=True;screen.wheelEvent(event)
        self.assertEqual(len(gestures),1)
        event.ignore.assert_called_once()
        screen.down=False;screen.close()

    def test_pipeline_counters_distinguish_submit_vsync_and_work_with_wrap(self):
        rates = PipelineRates()
        fields = [PIPELINE_MAGIC, 0xfffffffe, 0xfffffffc, 1000, 0xffffff00, 1000, 2, 1]
        self.assertNotIn('vsync_hz', rates.update(fields, 10.))
        updated = [PIPELINE_MAGIC, 2, 6, 2000, 0x1e40, 2000, 2, 1]
        info = rates.update(updated, 12.)
        self.assertEqual(info['vsync_hz'], 2.)
        self.assertEqual(info['swap_hz'], 5.)
        self.assertEqual(info['average_callback_ms'], 2.)
        self.assertIsNone(rates.update([0]*8, 14.))
        self.assertEqual(rates.rates, {})

    def test_fast_drag_final_move_precedes_release(self):
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import Qt, QEvent, QPointF
        from PySide6.QtGui import QMouseEvent
        from emulator_gui import Screen
        app = QApplication.instance() or QApplication([])
        screen = Screen()
        screen.resize(540, 1200)
        screen.down = True
        screen.last = (100, 100)
        received = []
        screen.touch.connect(lambda down, x, y: received.append((down,x,y)))
        end = QPointF(300, 500)
        expected = screen.coordinates(end, True)
        event = QMouseEvent(QEvent.Type.MouseButtonRelease, end, end,
            Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
        screen.mouseReleaseEvent(event)
        self.assertEqual(received, [(True,*expected), (False,*expected)])
        self.assertFalse(screen.down)
        screen.close()

    def test_repaint_does_not_inflate_rate_and_idle_decays_to_zero(self):
        rate = VisualRate()
        rate.painted(1, 10.)
        for _ in range(60):
            rate.painted(1, 10.5)
        self.assertEqual(rate.fps(11.), .5)
        for serial in range(2, 11):
            rate.painted(serial, 10.+serial*.1)
        self.assertEqual(rate.fps(11.5), 5.)
        self.assertEqual(rate.fps(13.2), 0.)

    def test_information_separates_target_pixels_presentations_and_host(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'data/root').mkdir(parents=True)
            (root/'data/root/ready.json').write_text('{"version":"16.7.16","build":"20H392"}')
            session = SimpleNamespace(guest_present_fps=30., frame_export_ms=35.,
                video_metadata={'copy_us':5000}, duplicate_frames=42)
            text = system_information(root, {'cpu_count':4,'memory_mib':4096,'fps':60},
                {'host_mib':32768}, session, visual_fps=5., capture_fps=6.)
            self.assertIn('Visual changes painted: 5.0 fps', text)
            self.assertIn('presentations: 30.0 /s', text)
            self.assertIn('60 fps (not animation speed)', text)
            self.assertIn('16.7.16 (20H392)', text)
            self.assertNotIn(folder, text)

    def test_missing_local_metadata_is_not_reported_as_verified_ios(self):
        with tempfile.TemporaryDirectory() as folder:
            text = system_information(folder, {'cpu_count':1,'memory_mib':2048,'fps':15},
                {'host_mib':8192})
            self.assertIn('iOS root metadata: Unavailable (Unavailable)', text)
            self.assertIn('iOS framebuffer presentations: Unavailable', text)
