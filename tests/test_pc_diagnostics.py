import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest

from pc_diagnostics import VisualRate, system_information


class DisplayMeasurementTests(unittest.TestCase):
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
