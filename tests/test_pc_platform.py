import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import struct,unittest
from unittest.mock import patch
import mkadt,adt
from pc_session import PcSession,INPUT_MAGIC,INPUT_ADDRESS,map_pointer

class DeviceTreeTests(unittest.TestCase):
    def test_qemu_topology_roundtrip_and_rtc(self):
        with patch.object(mkadt,'d22ap_product',return_value=None):
            for count in range(1,9):
                tree=adt.parse(adt.serialize(mkadt.build(qemu=True,cpu_count=count)))[0]
                cpus=next(n for n in tree.children if n.name=='cpus')
                regs=[struct.unpack('<I',dict((k,v) for k,f,v in n.props)['reg'])[0] for n in cpus.children]
                self.assertEqual(regs,list(range(count)))
                rtc=next(n for n in tree.children if n.name=='sweet-pc-rtc')
                self.assertEqual(struct.unpack('<QQ',dict((k,v) for k,f,v in rtc.props)['reg']),(0x09010000,0x1000))
    def test_phone_topology_and_peripherals_stay_separate(self):
        with patch.object(mkadt,'d22ap_product',return_value=None):
            tree=mkadt.build()
        self.assertNotIn('sweet-pc-rtc',[n.name for n in tree.children])
        cpus=next(n for n in tree.children if n.name=='cpus')
        self.assertEqual([struct.unpack('<I',dict((k,v) for k,f,v in n.props)['reg'])[0] for n in cpus.children],[i<<8 for i in range(8)])
        for count in (0,9,-1):
            with self.assertRaises(ValueError):mkadt.build(qemu=True,cpu_count=count)

class MemoryChannel:
    def __init__(self,head=0,tail=0):
        self.header=[INPUT_MAGIC,1,head,tail,0,0,0,0];self.events=[]
    def read(self,address,size):return struct.pack('<8I',*self.header)
    def write(self,address,data):self.events.append((address,struct.unpack('<8I',data)))
    def write32(self,address,value):self.header[2]=value

class InputTests(unittest.TestCase):
    def session(self,head=0,tail=0):
        s=PcSession('.');s.input_ready=True;s.qtest=MemoryChannel(head,tail);return s
    def test_ring_full_rejects_release_without_forgetting_hold(self):
        s=self.session();self.assertTrue(s.input(1,0,True,540,2399))
        s.qtest.header[2]=65
        self.assertFalse(s.input(1,0,False,540,1200))
        self.assertIn((1,0),s.held_inputs)
        s.qtest.header[3]=65
        self.assertTrue(s.input(1,0,False,540,1200))
        self.assertFalse(s.held_inputs)
        self.assertEqual(s.qtest.events[-1][1][1:6],(1,0,0,540,1200))
    def test_touch_move_waits_for_guest_to_consume_down(self):
        s=self.session();self.assertTrue(s.input(1,0,True,540,2000))
        self.assertFalse(s.input(1,0,True,540,1000))
        self.assertEqual(len(s.qtest.events),1)
        s.qtest.header[3]=s.qtest.header[2]
        self.assertTrue(s.input(1,0,True,540,1000))
        self.assertEqual(s.qtest.events[-1][1][4:6],(540,1000))

    def test_ring_counter_wrap_keeps_sequence_and_slot_valid(self):
        s=self.session(0xffffffff,0xffffffff)
        self.assertTrue(s.input(2,0,True))
        self.assertEqual(s.qtest.events[0][0],INPUT_ADDRESS+64+63*32)
        self.assertEqual(s.qtest.events[0][1][0],0)
        self.assertEqual(s.qtest.header[2],0)
    def test_letterbox_and_rotated_edges(self):
        self.assertIsNone(map_pointer(0,0,20,30,108,240))
        self.assertEqual(map_pointer(128,270,20,30,108,240),(1079,2399))
        self.assertEqual(map_pointer(20,30,20,30,240,108,90),(0,2399))
        self.assertEqual(map_pointer(-100,999,20,30,240,108,90,True),(1079,2399))

class GuiTests(unittest.TestCase):
    def test_touch_area_has_no_tooltip_and_controls_have_names(self):
        from PySide6.QtWidgets import QApplication,QToolButton
        from PySide6.QtCore import QEvent
        from emulator_gui import Window
        app=QApplication.instance() or QApplication([])
        window=Window(auto_start=False)
        self.assertEqual(window.screen.toolTip(),'')
        self.assertTrue(window.screen.event(QEvent(QEvent.Type.ToolTip)))
        buttons=window.findChildren(QToolButton)
        names={b.accessibleName():b for b in buttons if b.accessibleName()}
        for name in ('Home','Apps','Power','Vol+','Vol-','Screenshot','Rotate','Fullscreen','Settings'):
            self.assertIn(name,names)
            self.assertEqual(names[name].text(),'')
            self.assertTrue(names[name].toolTip())
            self.assertFalse(names[name].icon().isNull())
        window.close()


class EmulationTimeoutTests(unittest.TestCase):
    def test_multicore_timeouts_are_five_seconds_in_kernel_input_units(self):
        from pc_platform import multicore_boot_args
        self.assertEqual(multicore_boot_args(1), '')
        for cpus in (2,4):
            values=dict(field.split('=') for field in multicore_boot_args(cpus).split())
            self.assertEqual(int(values['slto_us']) / 1_000_000, 5)
            self.assertEqual(int(values['tlto_us']) / 1_000_000, 5)
            self.assertEqual(int(values['ml-timeout-lock-panic']) // 1000 / 1_000_000_000, 5)


class DesktopInteractionTests(unittest.TestCase):
    def test_keyboard_mapping_and_capability_guard(self):
        from emulator_gui import keyboard_usage
        from PySide6.QtCore import Qt
        self.assertEqual(keyboard_usage(Qt.Key.Key_A),4)
        self.assertEqual(keyboard_usage(Qt.Key.Key_0),39)
        self.assertEqual(keyboard_usage(Qt.Key.Key_Shift),225)
        self.assertIsNone(keyboard_usage(Qt.Key.Key_unknown))
        session=PcSession('.');session.input_ready=True;session.qtest=MemoryChannel()
        session.header=[INPUT_MAGIC,1,0,0,0,0,0,0]
        with self.assertRaisesRegex(ValueError,'0091'): session.input(3,4,True)
        session.header[7]=1
        self.assertTrue(session.input(3,4,True))
        self.assertIn((3,4),session.held_inputs)
        self.assertTrue(session.input(3,4,False))
        self.assertFalse(session.held_inputs)

    def test_windows_text_packets_and_shifted_physical_key_release(self):
        from emulator_gui import Screen, ascii_key_strokes
        from PySide6.QtCore import Qt,QEvent
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtWidgets import QApplication
        app=QApplication.instance() or QApplication([])
        screen=Screen();screen.enabled_input=True
        events=[];screen.keyboard.connect(lambda usage,down:events.append((usage,down)))
        packet=QKeyEvent(QEvent.Type.KeyPress,Qt.Key.Key_unknown,Qt.KeyboardModifier.NoModifier,0,0xE7,0,'A!z')
        screen.keyPressEvent(packet)
        self.assertEqual(events,[(225,True),(4,True),(4,False),(225,False),
                                 (225,True),(30,True),(30,False),(225,False),(29,True),(29,False)])
        self.assertFalse(screen.held_keys)
        self.assertEqual(ascii_key_strokes('\u00e9'),[])
        events.clear()
        screen.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress,Qt.Key.Key_Exclam,Qt.KeyboardModifier.ShiftModifier,2,0x31,0,'!'))
        screen.keyReleaseEvent(QKeyEvent(QEvent.Type.KeyRelease,Qt.Key.Key_1,Qt.KeyboardModifier.NoModifier,2,0x31,0,'1'))
        self.assertEqual(events,[(30,True),(30,False)])
        screen.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress,Qt.Key.Key_A,Qt.KeyboardModifier.NoModifier,'a'))
        screen.release_keys()
        self.assertEqual(events[-2:],[(4,True),(4,False)])
        screen.close()

    def test_stop_clears_screen_and_drops_queued_frames(self):
        from emulator_gui import Window
        from PySide6.QtWidgets import QApplication,QToolBar
        from PySide6.QtGui import QImage
        from types import SimpleNamespace
        import threading
        app=QApplication.instance() or QApplication([])
        window=Window(auto_start=False)
        window.worker=SimpleNamespace(stopping=threading.Event())
        frame=QImage(10,10,QImage.Format.Format_RGB32)
        window.screen.image=frame
        window.stop()
        self.assertTrue(window.screen.image.isNull())
        self.assertFalse(window.screen.enabled_input)
        window.new_frame(frame)
        self.assertTrue(window.screen.image.isNull())
        self.assertFalse(window.findChildren(QToolBar))
        window.worker=None;window.close()

    def test_theme_contrast_and_menu_choices(self):
        from emulator_gui import Window
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QPalette
        app=QApplication.instance() or QApplication([])
        window=Window(auto_start=False)
        for mode in ('Light','Dark','Auto'):
            window.settings['theme']=mode;window.apply_theme()
            self.assertEqual(window.fps_label.palette().color(QPalette.ColorRole.WindowText),
                             window.palette().color(QPalette.ColorRole.WindowText))
        self.assertEqual({a.text() for a in window.theme_group.actions()},{'Auto','Light','Dark'})
        self.assertTrue(window.log_button.isCheckable())
        self.assertTrue(window.home.toolTip())
        window.close()


class StatusSharingTests(unittest.TestCase):
    def test_diagnostic_file_sharing_violation_does_not_abort_guest(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as folder:
            session=PcSession('.')
            session.out=Path(folder)
            session.process=SimpleNamespace(pid=42,poll=lambda:None)
            session.qtest=MemoryChannel()
            with patch.object(Path,'replace',side_effect=PermissionError('Windows sharing violation')):
                self.assertIn('guest continues',session.poll())
            self.assertTrue(session.input_ready)
            session.last_status=0
            session.poll()
            self.assertTrue((session.out/'live.json').is_file())
            self.assertFalse(session.status_warning)


class FrameCacheTests(unittest.TestCase):
    def test_frame_cache_is_unique_outside_guest_disk_and_cleaned(self):
        from pathlib import Path
        from types import SimpleNamespace
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            session=PcSession(folder);session.out=Path(folder)
            def export(command,**args):
                self.assertEqual(command,'pmemsave')
                self.assertNotEqual(Path(args['filename']).parent,session.out)
                Path(args['filename']).write_bytes(b'abcd')
            session.qmp=SimpleNamespace(call=export,close=lambda:None)
            with patch('pc_session.FB_WIDTH',1),patch('pc_session.FB_HEIGHT',1):
                self.assertEqual(session.frame(),b'abcd')
            path=Path(session.frame_directory.name)
            self.assertGreater(session.frame_export_ms,0)
            session.stop()
            self.assertFalse(path.exists())


class StartupDisplayTests(unittest.TestCase):
    def test_apple_then_black_wakes_and_white_clock_schedules_home_once(self):
        from emulator_gui import Window
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QImage,QPainter,QColor
        from types import SimpleNamespace
        app=QApplication.instance() or QApplication([])
        window=Window(auto_start=False);window.worker=SimpleNamespace();window.stage='display'
        image=QImage(1080,2400,QImage.Format.Format_RGB32);image.fill(QColor('black'))
        painter=QPainter(image);painter.fillRect(400,1000,280,300,QColor('white'));painter.end()
        with patch.object(window,'key_click') as key,patch('emulator_gui.QTimer.singleShot') as schedule:
            black=QImage(image);black.fill(QColor('black'))
            window.startup_display_at=-1000
            window.new_frame(black);key.assert_not_called()
            window.new_frame(image)
            key.assert_not_called();schedule.assert_not_called()
            image.fill(QColor('black'));window.new_frame(image)
            key.assert_called_once_with(0)
            painter=QPainter(image);painter.fillRect(100,120,600,240,QColor('white'));painter.end()
            window.new_frame(image);window.new_frame(image)
            schedule.assert_called_once()
            self.assertFalse(window.auto_home_pending)
        window.worker=None;window.close()


class VideoMetadataTests(unittest.TestCase):
    def test_unchanged_and_inflight_frames_do_not_export_full_memory(self):
        from types import SimpleNamespace
        import tempfile
        from pathlib import Path
        from pc_session import VIDEO_MAGIC
        with tempfile.TemporaryDirectory() as folder:
            s=PcSession(folder)
            metadata=[VIDEO_MAGIC,2,1,120,1,1,4,0]
            s.qtest=SimpleNamespace(read=lambda address,size:struct.pack('<8I',*metadata))
            exports=[]
            def export(command,**args):
                exports.append(command);Path(args['filename']).write_bytes(b'abcd')
            s.qmp=SimpleNamespace(call=export)
            with patch('pc_session.FB_WIDTH',1),patch('pc_session.FB_HEIGHT',1),patch('pc_session.time.monotonic',return_value=0) as stamp:
                self.assertEqual(s.frame(),b'abcd')
                self.assertIsNone(s.frame())
                metadata[1:3]=[3,2]
                self.assertIsNone(s.frame())
                metadata[1]=4
                stamp.return_value=2
                self.assertEqual(s.frame(),b'abcd')
                self.assertEqual(s.guest_present_fps,.5)
                self.assertEqual(s.exported_frames,2)
            self.assertEqual(exports,['pmemsave','pmemsave'])
            self.assertEqual(s.frame_skips,2)
            s.frame_directory.cleanup()

    def test_old_kernel_reserved_words_preserve_capture(self):
        from types import SimpleNamespace
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            s=PcSession(folder)
            s.qtest=SimpleNamespace(read=lambda address,size:bytes(32))
            exports=[]
            def export(command,**args):
                exports.append(command);Path(args['filename']).write_bytes(b'abcd')
            s.qmp=SimpleNamespace(call=export)
            with patch('pc_session.FB_WIDTH',1),patch('pc_session.FB_HEIGHT',1):
                self.assertEqual(s.frame(),b'abcd');self.assertEqual(s.frame(),b'abcd')
            self.assertEqual(len(exports),2)
            s.frame_directory.cleanup()


class ClipboardInputTests(unittest.TestCase):
    def test_paste_is_text_not_guest_control_v_and_modifier_is_released(self):
        from emulator_gui import Screen
        from PySide6.QtCore import Qt,QEvent
        from PySide6.QtGui import QKeyEvent,QInputMethodEvent
        from PySide6.QtWidgets import QApplication
        app=QApplication.instance() or QApplication([])
        screen=Screen();screen.enabled_input=True
        keyboard=[];text=[];notices=[]
        screen.keyboard.connect(lambda key,down:keyboard.append((key,down)))
        screen.text_input.connect(text.append);screen.input_notice.connect(notices.append)
        old=app.clipboard().text()
        try:
            app.clipboard().setText('Ab9!')
            screen.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress,Qt.Key.Key_Control,Qt.KeyboardModifier.ControlModifier))
            screen.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress,Qt.Key.Key_V,Qt.KeyboardModifier.ControlModifier))
            screen.keyReleaseEvent(QKeyEvent(QEvent.Type.KeyRelease,Qt.Key.Key_V,Qt.KeyboardModifier.ControlModifier))
            screen.keyReleaseEvent(QKeyEvent(QEvent.Type.KeyRelease,Qt.Key.Key_Control,Qt.KeyboardModifier.NoModifier))
            self.assertEqual(text,['Ab9!'])
            self.assertEqual(keyboard,[(224,True),(224,False),(224,True),(224,False)])
            self.assertFalse(screen.held_keys)
            screen.commit_text('Unicode: \u00e9')
            self.assertEqual(len(text),1);self.assertEqual(len(notices),1)
            event=QInputMethodEvent();event.setCommitString('input');screen.inputMethodEvent(event)
            self.assertEqual(text[-1],'input')
        finally:
            app.clipboard().setText(old);screen.close()


class PausedFrameTests(unittest.TestCase):
    def test_paused_worker_never_exports_frames_and_reports_zero_fps(self):
        from emulator_gui import Worker
        from types import SimpleNamespace
        from unittest.mock import Mock
        from pathlib import Path
        worker=Worker({'memory_mib':2048,'cpu_count':2,'fps':60})
        frame=Mock(side_effect=AssertionError('Paused guest must not be exported'))
        def poll():worker.stopping.set();return ''
        session=SimpleNamespace(start=lambda:None,pause=Mock(return_value=None),poll=poll,frame=frame,
                                out=Path('.'),input_ready=True,stage='display',stop=lambda:None)
        states=[];worker.state.connect(lambda *args:states.append(args))
        worker.submit('pause',True)
        with patch('emulator_gui.PcSession',return_value=session):worker.run()
        session.pause.assert_called_once_with(True)
        frame.assert_not_called()
        self.assertIn(('paused',True,0.),states)


class ResumeCalendarTests(unittest.TestCase):
    def test_resume_system_event_is_capability_gated_and_acknowledged(self):
        from types import SimpleNamespace
        for capabilities in (1,3):
            s=PcSession('.');s.input_ready=True;s.header=[INPUT_MAGIC,1,0,0,0,0,0,capabilities]
            channel=MemoryChannel();s.qtest=channel
            def publish(address,value):channel.header[2]=value;channel.header[3]=value
            channel.write32=publish
            calls=[];s.qmp=SimpleNamespace(call=calls.append)
            self.assertIsNone(s.pause(False))
            self.assertEqual(calls,['cont'])
            if capabilities & 2:
                self.assertEqual(channel.events[0][1],(1,4,0,0,0,0,0,0))
            else:self.assertEqual(channel.events,[])

    def test_clock_resume_does_not_overwrite_full_ring(self):
        s=PcSession('.');s.qtest=MemoryChannel(64,0)
        self.assertFalse(s.resume_calendar());self.assertFalse(s.qtest.events)


class StartupTimerTests(unittest.TestCase):
    def test_console_is_not_unlock_ready_and_idle_timer_can_wake(self):
        from emulator_gui import Window
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QImage,QColor,QPainter
        from types import SimpleNamespace
        app=QApplication.instance() or QApplication([])
        window=Window(auto_start=False);window.worker=SimpleNamespace();window.stage='display'
        image=QImage(1080,2400,QImage.Format.Format_RGB32);image.fill(QColor('black'))
        painter=QPainter(image)
        for y in range(20,2400,35):painter.fillRect(20,y,900,6,QColor('white'))
        painter.end()
        with patch('emulator_gui.QTimer.singleShot') as schedule,patch.object(window,'key_click') as key:
            window.new_frame(image)
            schedule.assert_not_called();self.assertTrue(window.auto_home_pending)
            image.fill(QColor('black'));window.new_frame(image)
            key.assert_called_once_with(0)
            with patch('emulator_gui.time.monotonic',return_value=window.startup_last_wake+31):
                window.check_startup()
            self.assertEqual(key.call_count,2)
        window.worker=None;window.close()


class OrderlyShutdownTests(unittest.TestCase):
    def test_request_is_capability_gated_and_does_not_quit_qemu(self):
        from unittest.mock import Mock
        s=PcSession('.');s.input_ready=True;s.qtest=MemoryChannel();s.qmp=Mock()
        s.header=[INPUT_MAGIC,1,0,0,0,0,0,3]
        with self.assertRaisesRegex(ValueError,'0094'):s.request_shutdown()
        s.header[7]=7
        s.request_shutdown()
        self.assertTrue(s.shutdown_requested)
        self.assertEqual(s.qtest.events[-1][1],(1,4,1,0,0,0,0,0))
        s.qmp.call.assert_not_called()

    def test_zero_exit_needs_requested_platform_halt_without_panic(self):
        from pathlib import Path
        from types import SimpleNamespace
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            s=PcSession(folder);s.out=Path(folder);s.process=SimpleNamespace(poll=lambda:0,returncode=0)
            log=s.out/'serial.txt'
            log.write_text('SWEET PC: platform halt reached\n')
            with self.assertRaises(RuntimeError):s.poll()
            s.serial_position=0;s.serial_tail='';s.shutdown_requested=True
            self.assertIn('platform halt',s.poll());self.assertEqual(s.stage,'shutdown')
            s.serial_position=0;s.serial_tail=''
            log.write_text('panic(cpu 0 caller...)\nSWEET PC: platform halt reached\n')
            with self.assertRaises(RuntimeError):s.poll()

    def test_worker_waits_for_guest_shutdown_without_exporting_more_frames(self):
        from emulator_gui import Worker
        from unittest.mock import Mock
        from types import SimpleNamespace
        from pathlib import Path
        w=Worker({'memory_mib':2048,'cpu_count':2,'fps':30})
        session=SimpleNamespace(start=lambda:None,out=Path('.'),stage='display',input_ready=True,
            request_shutdown=Mock(),stop=Mock(),frame=Mock(side_effect=AssertionError('Export during shutdown')))
        def poll():session.stage='shutdown';return 'SWEET PC: platform halt reached'
        session.poll=poll
        w.submit('shutdown');errors=[];w.finished.connect(errors.append)
        with patch('emulator_gui.PcSession',return_value=session):w.run()
        session.request_shutdown.assert_called_once();session.frame.assert_not_called()
        session.stop.assert_called_once();self.assertEqual(errors,[''])


class SupportedCpuLimitTests(unittest.TestCase):
    def test_gui_rejects_saved_cpu_counts_that_current_pc_kernel_panics_on(self):
        import tempfile,json
        from pathlib import Path
        from emulator_gui import Window,host_limits
        from PySide6.QtWidgets import QApplication
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);settings=root/'data/gui/settings.json'
            settings.parent.mkdir(parents=True)
            settings.write_text(json.dumps(dict(cpu_count=8)))
            with patch('emulator_gui.ROOT',root),patch('emulator_gui.os.cpu_count',return_value=64):
                self.assertEqual(host_limits()['cpu_count'],4)
                window=Window(auto_start=False)
                self.assertLessEqual(window.settings['cpu_count'],4)
                window.close()


class UnlockRetryTests(unittest.TestCase):
    def test_retries_only_dark_lock_clock_and_stops_after_three_attempts(self):
        from emulator_gui import Window
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QImage,QColor,QPainter
        from types import SimpleNamespace
        app=QApplication.instance() or QApplication([])
        w=Window(auto_start=False);w.worker=SimpleNamespace();w.stage='display'
        image=QImage(1080,2400,QImage.Format.Format_RGB32);image.fill(QColor('black'))
        painter=QPainter(image);painter.fillRect(350,350,380,100,QColor('red'));painter.end()
        self.assertTrue(w.lock_clock_visible(image))
        w.screen.image=image;w.auto_home_pending=False
        with patch.object(w,'go_home') as home,patch('emulator_gui.time.monotonic',return_value=10):
            w.startup_unlock()
            for stamp in (19,28,37):
                with patch('emulator_gui.time.monotonic',return_value=stamp):w.check_startup()
            self.assertEqual(home.call_count,3)
        image.fill(QColor('white'));self.assertFalse(w.lock_clock_visible(image))
        image.fill(QColor('black'));painter=QPainter(image)
        painter.fillRect(300,300,200,170,QColor('blue'));painter.end()
        self.assertFalse(w.lock_clock_visible(image))
        w.worker=None;w.close()
