"""Native Windows controls around the live iOS framebuffer; MuMu-style sidebar and English UI."""
import os
import ctypes
import heapq
import json
from pathlib import Path
import queue
import sys
import threading
import time

from PySide6.QtCore import Qt, QEvent, QPointF, QRectF, QSize, Signal, QObject, QTimer
from PySide6.QtGui import QAction, QActionGroup, QPalette, QColor, QIcon, QImage, QKeySequence, QPainter, QPen, QPixmap, QPolygonF, QTransform
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QDialogButtonBox,
    QDockWidget, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
    QPlainTextEdit, QSpinBox, QSizePolicy, QStyle, QStyleFactory, QToolBar,
    QToolButton, QToolTip, QVBoxLayout, QWidget)

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'data/python-deps'))
from pc_session import PcSession, FB_WIDTH, FB_HEIGHT, map_pointer
from pc_diagnostics import VisualRate, system_information


def control_icon(name, color="#d9dce5"):
    """Clear monochrome control glyphs on the dark native Qt button surfaces."""
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(color), 1.7, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    def lines(points):
        painter.drawPolyline(QPolygonF([QPointF(x, y) for x, y in points]))
    if name == 'Home':
        lines([(3, 11), (12, 4), (21, 11)])
        lines([(6, 10), (6, 20), (10, 20), (10, 14), (14, 14), (14, 20), (18, 20), (18, 10)])
    elif name == 'Apps':
        painter.drawRoundedRect(QRectF(4, 7, 12, 13), 1.5, 1.5)
        lines([(8, 4), (20, 4), (20, 17)])
    elif name == 'Power':
        painter.drawArc(QRectF(4, 4, 16, 16), 130 * 16, 280 * 16)
        painter.drawLine(12, 2, 12, 11)
    elif name in ('Vol+', 'Vol-'):
        lines([(4, 9), (8, 9), (12, 5), (12, 19), (8, 15), (4, 15), (4, 9)])
        painter.drawLine(16, 12, 22, 12)
        if name == 'Vol+': painter.drawLine(19, 9, 19, 15)
    elif name == 'Screenshot':
        lines([(3, 8), (7, 8), (9, 5), (15, 5), (17, 8), (21, 8), (21, 20), (3, 20), (3, 8)])
        painter.drawEllipse(QRectF(8, 10, 8, 8))
    elif name in ('Rotate', 'Restart'):
        painter.drawArc(QRectF(5, 5, 14, 14), 40 * 16, 285 * 16)
        lines([(16, 3), (19, 7), (14, 8)])
    elif name == 'Fullscreen':
        for points in ([(3, 9), (3, 3), (9, 3)], [(15, 3), (21, 3), (21, 9)],
                       [(21, 15), (21, 21), (15, 21)], [(9, 21), (3, 21), (3, 15)]): lines(points)
    elif name == 'Settings':
        for y, x in ((6, 9), (12, 16), (18, 7)):
            painter.drawLine(3, y, 21, y)
            painter.setBrush(QColor('#1a1b20'))
            painter.drawEllipse(QRectF(x-2, y-2, 4, 4))
    elif name == 'Logs':
        painter.drawRoundedRect(QRectF(4, 3, 16, 18), 2, 2)
        for y in (8, 12, 16): painter.drawLine(8, y, 17, y)
    elif name == 'Keyboard':
        painter.drawRoundedRect(QRectF(2, 6, 20, 13), 2, 2)
        for x in (6, 10, 14, 18):
            for y in (10, 13): painter.drawPoint(x, y)
        painter.drawLine(7, 16, 17, 16)
    elif name == 'Start':
        lines([(7, 4), (19, 12), (7, 20), (7, 4)])
    elif name == 'Pause':
        painter.drawLine(8, 5, 8, 19)
        painter.drawLine(16, 5, 16, 19)
    elif name == 'Stop': painter.drawRect(QRectF(5, 5, 14, 14))
    painter.end()
    return QIcon(pixmap)


class Worker(QObject):
    frame = Signal(object)
    state = Signal(str, bool, float)
    log = Signal(str)
    finished = Signal(str)

    def __init__(self, settings, kernel=None, overlay=None):
        super().__init__()
        self.settings = settings.copy()
        self.kernel, self.overlay = kernel, overlay
        self.commands = queue.Queue(maxsize=512)
        self.stopping = threading.Event()
        self.frame_pending = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True, name='iOS emulator')
        self.session = None

    def submit(self, *command):
        if not self.stopping.is_set():
            try:
                self.commands.put_nowait(command)
            except queue.Full:
                self.stopping.set()
                self.log.emit('Input overflow; session halted to release held keys.')

    def run(self):
        error = ''
        paused = False
        shutting_down = False
        shutdown_deadline = None
        scheduled = []
        order = 0
        next_frame = next_poll = 0
        frames, fps, measured = 0, 0., time.monotonic()
        previous_pixels = None
        try:
            self.session = PcSession(ROOT, self.settings['memory_mib'], self.kernel, self.overlay, self.settings['cpu_count'])
            self.state.emit('starting', False, 0)
            self.session.start()
            self.log.emit('Session: ' + str(self.session.out))
            while not self.stopping.is_set():
                now = time.monotonic()
                for _ in range(32):
                    try:
                        command = self.commands.get_nowait()
                    except queue.Empty:
                        break
                    if command[0] == 'refresh':
                        self.settings['fps'] = command[1]
                        next_frame = 0
                    elif command[0] == 'shutdown' and not paused and not shutting_down:
                        scheduled.clear()
                        self.session.request_shutdown()
                        shutting_down = True
                        shutdown_deadline = now + 120
                        frames, fps = 0, 0.
                    elif command[0] == 'pause' and not shutting_down:
                        scheduled.clear()
                        paused = bool(command[1])
                        warning = self.session.pause(paused)
                        if warning: self.log.emit(warning)
                        frames, fps, measured = 0, 0., time.monotonic()
                        next_frame = 0
                    elif command[0] == 'input' and not paused and not shutting_down and self.session.input_ready:
                        order += 1
                        heapq.heappush(scheduled, (now, order, command[1:]))
                    elif command[0] == 'text' and not paused and not shutting_down and self.session.input_ready:
                        for usage, down in ascii_key_strokes(command[1]):
                            order += 1
                            heapq.heappush(scheduled, (now, order, (3, usage, down, 0, 0)))
                    elif command[0] == 'gesture' and not paused and not shutting_down and self.session.input_ready:
                        _, x0, y0, x1, y1, duration, hold = command
                        for step in range(2):
                            x, y = round(x0 + (x1 - x0) * step), round(y0 + (y1 - y0) * step)
                            order += 1
                            heapq.heappush(scheduled, (now + duration * step, order, (1, 0, True, x, y)))
                        order += 1
                        heapq.heappush(scheduled, (now + duration + hold + .03, order, (1, 0, False, x1, y1)))
                while scheduled and scheduled[0][0] <= time.monotonic() and not paused and not shutting_down:
                    due, sequence, event = scheduled[0]
                    if not self.session.input(*event):
                        break
                    heapq.heappop(scheduled)
                if now >= next_poll:
                    delta = self.session.poll()
                    if delta:
                        self.log.emit(delta)
                    if self.session.stage == 'shutdown':
                        self.log.emit('iOS completed orderly shutdown; QEMU exited.')
                        break
                    stage = 'shutting-down' if shutting_down else ('paused' if paused else self.session.stage)
                    if shutting_down and now >= shutdown_deadline:
                        stage = 'shutdown-stalled'
                    self.state.emit(stage, self.session.input_ready and not shutting_down, fps)
                    next_poll = now + .25
                if not paused and not shutting_down and now >= next_frame and not self.frame_pending.is_set():
                    data = self.session.frame()
                    if data is not None and data != previous_pixels:
                        previous_pixels = data
                        image = QImage(data, FB_WIDTH, FB_HEIGHT, FB_WIDTH * 4, QImage.Format.Format_RGB32).copy()
                        self.frame_pending.set()
                        self.frame.emit(image)
                        frames += 1
                    elif data is not None:
                        self.session.duplicate_frames = getattr(self.session, 'duplicate_frames', 0) + 1
                    interval = 2. if self.session.stage == 'booting' else (.5 if self.session.stage in ('services', 'springboard') else 1 / self.settings['fps'])
                    next_frame = max(now + interval, time.monotonic())
                if now - measured >= 2:
                    fps = frames / (now - measured)
                    frames = 0
                    measured = now
                time.sleep(.005)
        except Exception as exc:
            error = str(exc)
        finally:
            if self.session:
                try:
                    self.session.stop()
                except Exception as exc:
                    error = error or str(exc)
            self.finished.emit(error)


class Screen(QWidget):
    touch = Signal(bool, int, int)
    keyboard = Signal(int, bool)
    text_input = Signal(str)
    input_notice = Signal(str)

    def __init__(self):
        super().__init__()
        self.image = QImage()
        self.frame_serial = 0
        self.visual_rate = VisualRate()
        self.rotation = 0
        self.down = False
        self.enabled_input = False
        self.last = (540, 1200)
        self.last_move = 0
        self.capture_keyboard = True
        self.held_keys = {}
        self.message = 'Click Start to boot iOS'
        self.setMinimumSize(270, 430)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName('iOS Display')
        # Explicitly no tooltip in the touch area so nothing pops up when hovering/touching
        self.setToolTip('')

    def event(self, event):
        if event.type() == QEvent.Type.ToolTip:
            QToolTip.hideText()
            event.ignore()
            return True
        return super().event(event)

    def frame_rect(self):
        w, h = (FB_WIDTH, FB_HEIGHT) if self.rotation == 0 else (FB_HEIGHT, FB_WIDTH)
        scale = min(self.width() / w, self.height() / h)
        return QRectF((self.width() - w * scale) / 2, (self.height() - h * scale) / 2, w * scale, h * scale)

    def coordinates(self, position, clamp=False):
        r = self.frame_rect()
        return map_pointer(position.x(), position.y(), r.x(), r.y(), r.width(), r.height(), self.rotation, clamp)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.black)
        if self.image.isNull():
            painter.setPen(Qt.GlobalColor.lightGray)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.message)
        else:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            image = self.image if not self.rotation else self.image.transformed(QTransform().rotate(90))
            painter.drawImage(self.frame_rect(), image)
            self.visual_rate.painted(self.frame_serial)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or not self.enabled_input:
            return
        point = self.coordinates(event.position())
        if point is not None:
            self.down = True
            self.last = point
            self.grabMouse()
            self.setFocus()
            self.touch.emit(True, *point)

    def mouseMoveEvent(self, event):
        if self.down and time.monotonic() - self.last_move >= .025:
            self.last = self.coordinates(event.position(), True)
            self.last_move = time.monotonic()
            self.touch.emit(True, *self.last)

    def mouseReleaseEvent(self, event):
        if self.down and event.button() == Qt.MouseButton.LeftButton:
            self.last = self.coordinates(event.position(), True)
            self.release_touch()

    def release_touch(self):
        if self.down:
            self.down = False
            self.releaseMouse()
            self.touch.emit(False, *self.last)

    def release_keys(self):
        for usage in self.held_keys.values(): self.keyboard.emit(usage, False)
        self.held_keys.clear()

    def commit_text(self, text):
        if not text:
            return
        if len(text)>4096 or not ascii_key_strokes(text):
            self.input_notice.emit('Paste supports up to 4096 printable ASCII characters (US keyboard layout).')
            return
        held=self.held_keys.copy()
        self.release_keys()
        self.text_input.emit(text)
        # A physically held modifier must still receive its eventual release.
        for token,usage in held.items():
            self.held_keys[token]=usage
            self.keyboard.emit(usage,True)

    def inputMethodEvent(self, event):
        if self.enabled_input and self.capture_keyboard and event.commitString():
            self.commit_text(event.commitString());event.accept();return
        super().inputMethodEvent(event)

    def keyPressEvent(self, event):
        if self.enabled_input and self.capture_keyboard:
            if event.matches(QKeySequence.StandardKey.Paste):
                self.commit_text(QApplication.clipboard().text())
                event.accept()
                return
            # Windows SendInput/assistive text uses VK_PACKET, without physical
            # modifier events. Convert supported ASCII into complete HID strokes.
            if event.nativeVirtualKey() == 0xE7 or event.key() == Qt.Key.Key_unknown:
                strokes = ascii_key_strokes(event.text())
                if strokes:
                    for usage, down in strokes: self.keyboard.emit(usage, down)
                    event.accept()
                    return
            usage = keyboard_usage(event.key(), event.nativeVirtualKey())
            token = event.nativeVirtualKey() or event.key()
            if usage:
                if not event.isAutoRepeat() and token not in self.held_keys:
                    self.held_keys[token] = usage
                    self.keyboard.emit(usage, True)
                event.accept()
                return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        token = event.nativeVirtualKey() or event.key()
        if token in self.held_keys:
            if not event.isAutoRepeat(): self.keyboard.emit(self.held_keys.pop(token), False)
            event.accept()
            return
        super().keyReleaseEvent(event)

    def focusOutEvent(self, event):
        self.release_touch()
        self.release_keys()
        super().focusOutEvent(event)


def ascii_key_strokes(text):
    """US-layout printable ASCII packets; unsupported Unicode is left to Qt."""
    plain = "1234567890-=[]\\;'`,./"
    shifted = '!@#$%^&*()_+{}|:"~<>?'
    usages = (30,31,32,33,34,35,36,37,38,39,45,46,47,48,49,51,52,53,54,55,56)
    strokes = []
    for char in text:
        shift = False
        if char.isascii() and 'a' <= char.lower() <= 'z':
            usage = 4 + ord(char.lower()) - ord('a'); shift = char.isupper()
        elif char == ' ': usage = 44
        elif char in plain: usage = usages[plain.index(char)]
        elif char in shifted: usage = usages[shifted.index(char)]; shift = True
        else: return []
        if shift: strokes.append((225, True))
        strokes.extend(((usage, True), (usage, False)))
        if shift: strokes.append((225, False))
    return strokes


def keyboard_usage(key, native_virtual_key=0):
    # OEM virtual keys identify the physical key even when Qt reports a shifted
    # symbol. Stable native tokens also pair its key-up after Shift is released.
    native = {0xBA:51,0xBB:46,0xBC:54,0xBD:45,0xBE:55,0xBF:56,
              0xC0:53,0xDB:47,0xDC:49,0xDD:48,0xDE:52,
              0xA0:225,0xA1:229,0xA2:224,0xA3:228,0xA4:226,0xA5:230}
    if native_virtual_key in native: return native[native_virtual_key]
    if 0x30 <= native_virtual_key <= 0x39:
        return 39 if native_virtual_key == 0x30 else 30 + native_virtual_key - 0x31
    if Qt.Key.Key_A <= key <= Qt.Key.Key_Z: return 4 + key - Qt.Key.Key_A
    if Qt.Key.Key_1 <= key <= Qt.Key.Key_9: return 30 + key - Qt.Key.Key_1
    return {Qt.Key.Key_0:39, Qt.Key.Key_Return:40, Qt.Key.Key_Enter:40,
        Qt.Key.Key_Escape:41, Qt.Key.Key_Backspace:42, Qt.Key.Key_Tab:43,
        Qt.Key.Key_Space:44, Qt.Key.Key_Minus:45, Qt.Key.Key_Equal:46,
        Qt.Key.Key_BracketLeft:47, Qt.Key.Key_BracketRight:48,
        Qt.Key.Key_Backslash:49, Qt.Key.Key_Semicolon:51, Qt.Key.Key_Apostrophe:52,
        Qt.Key.Key_QuoteLeft:53, Qt.Key.Key_Comma:54, Qt.Key.Key_Period:55,
        Qt.Key.Key_Slash:56, Qt.Key.Key_CapsLock:57, Qt.Key.Key_Delete:76,
        Qt.Key.Key_Home:74, Qt.Key.Key_End:77, Qt.Key.Key_PageUp:75, Qt.Key.Key_PageDown:78,
        Qt.Key.Key_Right:79, Qt.Key.Key_Left:80, Qt.Key.Key_Down:81, Qt.Key.Key_Up:82,
        Qt.Key.Key_Control:224, Qt.Key.Key_Shift:225, Qt.Key.Key_Alt:226}.get(key)


def host_limits():
    total = 8 * 1024
    if os.name == 'nt':
        class Memory(ctypes.Structure):
            _fields_ = [('length',ctypes.c_ulong),('load',ctypes.c_ulong)]+[(n,ctypes.c_ulonglong) for n in
                ('total','available','page','page_available','virtual','virtual_available','extended')]
        memory=Memory();memory.length=ctypes.sizeof(memory)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)): total=memory.total//1048576
    elif hasattr(os, 'sysconf'):
        total=os.sysconf('SC_PAGE_SIZE')*os.sysconf('SC_PHYS_PAGES')//1048576
    # Reserve host RAM and QEMU's low-address region; guest ABI currently validated to 4 GiB.
    budget=max(1024, int(total*.8)-1792)
    cores=max(1,min(4, int((os.cpu_count() or 1)*.8)))
    screen=QApplication.primaryScreen()
    return {'host_mib':total,'budget_mib':budget,'memory_mib':min(4096,budget)//256*256,
            'cpu_count':cores,'fps':max(30,min(240,round(screen.refreshRate()) if screen else 60))}


class Spinner(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent); self.angle=0; self.setFixedSize(16,16)
        self.timer=QTimer(self);self.timer.setInterval(60);self.timer.timeout.connect(self.tick)
        self.setAccessibleName('Loading')
    def tick(self): self.angle=(self.angle+30)%360;self.update()
    def showEvent(self,event): self.timer.start();super().showEvent(event)
    def hideEvent(self,event): self.timer.stop();super().hideEvent(event)
    def paintEvent(self,event):
        painter=QPainter(self);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(getattr(self,'color','#242832')),2,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap))
        painter.drawArc(QRectF(3,3,10,10),self.angle*16,240*16)


class Window(QMainWindow):
    def __init__(self, auto_start=True, kernel=None, overlay=None):
        super().__init__()
        self.setWindowTitle('iOS Emulator')
        self.setWindowIcon(QIcon(str(ROOT / 'assets/app-icon.ico')))
        self.setObjectName('iosEmulatorWindow')
        self.setMinimumSize(540, 600)
        self.resize(650, min(980, QApplication.primaryScreen().availableGeometry().height() - 60))
        self.worker = None
        self.shutting_down = False
        self.startup_timer=QTimer(self)
        self.startup_timer.setInterval(1000)
        self.startup_timer.timeout.connect(self.check_startup)
        self.startup_timer.start()
        self.paused = False
        self.restarting = False
        self.kernel, self.overlay = kernel, overlay
        self.settings_path = ROOT / 'data/gui/settings.json'
        self.limits = host_limits()
        self.settings = {'memory_mib': 2048, 'fps': 15, 'cpu_count': 1, 'theme': 'Auto', 'status_bar': True}
        self.stage = 'stopped'
        self.stopping = False
        self.auto_home_pending = True
        self.startup_display_at = None
        self.startup_seen_image = False
        self.startup_wake_count = 0
        self.startup_last_wake = 0.
        self.startup_unlock_tries = 0
        self.startup_unlock_at = 0.
        self.buttons = []
        if self.settings_path.exists():
            try:
                saved = json.loads(self.settings_path.read_text())
                if saved.get('cpu_count') in range(1, self.limits['cpu_count']+1):
                    self.settings['cpu_count'] = saved['cpu_count']
                if isinstance(saved.get('memory_mib'), int) and 1024 <= saved['memory_mib'] <= self.limits['memory_mib']:
                    self.settings['memory_mib'] = saved['memory_mib']
                if isinstance(saved.get('fps'), int) and 5 <= saved['fps'] <= self.limits['fps']:
                    self.settings['fps'] = saved['fps']
                self.settings['theme'] = saved.get('theme', 'Auto') if saved.get('theme') in ('Auto','Light','Dark') else 'Auto'
                self.settings['status_bar'] = bool(saved.get('status_bar',True))
            except (OSError, ValueError):
                pass

        self.apply_theme()

        self.screen = Screen()
        self.screen.touch.connect(self.touch)
        self.screen.keyboard.connect(self.keyboard)
        self.screen.text_input.connect(self.paste_text)
        self.screen.input_notice.connect(lambda text:self.show_status_message(text,6000))

        center = QWidget()
        layout = QHBoxLayout(center)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)
        layout.addWidget(self.screen, 1)

        # MuMu Player-style sleek right sidebar
        sidebar_frame = QFrame()
        sidebar_frame.setObjectName('mumuSidebar')
        sidebar_frame.setFixedWidth(52)
        rail = QVBoxLayout(sidebar_frame)
        rail.setContentsMargins(6, 10, 6, 10)
        rail.setSpacing(8)
        rail.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        self.input_buttons = []
        self.home = self.side_button(rail, 'Home', 'Home Screen (F1)', self.go_home, QStyle.StandardPixmap.SP_ArrowUp)
        self.apps = self.side_button(rail, 'Apps', 'Recent Apps (App Switcher)', self.app_switcher, QStyle.StandardPixmap.SP_FileDialogListView)
        self.power = self.side_button(rail, 'Power', 'Power Button (F2)', None, QStyle.StandardPixmap.SP_DialogCloseButton)
        self.power.pressed.connect(lambda: self.key(0, True))
        self.power.released.connect(lambda: self.key(0, False))
        self.up = self.side_button(rail, 'Vol+', 'Volume Up (F4)', None, QStyle.StandardPixmap.SP_MediaVolume)
        self.up.pressed.connect(lambda: self.key(1, True))
        self.up.released.connect(lambda: self.key(1, False))
        self.down = self.side_button(rail, 'Vol-', 'Volume Down (F3)', None, QStyle.StandardPixmap.SP_MediaVolumeMuted)
        self.down.pressed.connect(lambda: self.key(2, True))
        self.down.released.connect(lambda: self.key(2, False))

        self.add_sidebar_separator(rail)

        self.screenshot_button = self.side_button(rail, 'Screenshot', 'Save Screenshot (Ctrl+S)', self.screenshot, QStyle.StandardPixmap.SP_DialogSaveButton, False)
        self.side_button(rail, 'Rotate', 'Rotate Screen 90Â° (Ctrl+R)', self.rotate, QStyle.StandardPixmap.SP_BrowserReload, False)
        self.side_button(rail, 'Fullscreen', 'Full Screen (F11)', self.fullscreen, QStyle.StandardPixmap.SP_TitleBarMaxButton, False)

        rail.addStretch(1)

        self.keyboard_action = QAction('Capture Keyboard', self, checkable=True, checked=True)
        self.keyboard_action.toggled.connect(self.capture_keyboard)
        self.keyboard_button = self.side_button(rail, 'Keyboard', 'Capture PC Keyboard (click the iOS display to type)', None, None, False)
        self.keyboard_button.setDefaultAction(self.keyboard_action)
        self.keyboard_button.setText('')
        self.keyboard_button.setToolTip('Capture PC Keyboard (click the iOS display to type)')
        self.log_action = QAction('Logs', self, checkable=True)
        self.log_action.triggered.connect(lambda checked: self.log_dock.setVisible(checked))
        self.log_button = self.side_button(rail, 'Logs', 'Show / Hide Logs', None, None, False)
        self.log_button.setDefaultAction(self.log_action)
        self.log_button.setText('')
        self.log_button.setToolTip('Show / Hide Logs')
        self.settings_button = self.side_button(rail, 'Settings', 'Settings (CPU, Memory & Refresh Rate)', self.preferences, QStyle.StandardPixmap.SP_ComputerIcon, False)
        layout.addWidget(sidebar_frame)
        self.setCentralWidget(center)

        self.start_action = self.action('Start', self.start, None, 'Ctrl+Return')
        self.pause_action = self.action('Pause', self.pause, None, 'Ctrl+P')
        self.shutdown_action = self.action('Shut Down iOS', self.shutdown, None)
        self.shutdown_action.setToolTip('Stop guest processes, sync and unmount before power off (kernel0094+).')
        self.stop_action = self.action('Force Stop', self.stop, None)
        self.restart_action = self.action('Restart', self.restart, None, 'F5')
        menu = self.menuBar().addMenu('&Emulator')
        for a in (self.start_action, self.pause_action, self.shutdown_action, self.stop_action, self.restart_action):
            menu.addAction(a)
        menu.addSeparator()
        self.settings_action=menu.addAction('Settings...', self.preferences)
        menu.addSeparator()
        menu.addAction('Exit', self.close, QKeySequence('Alt+F4'))

        view = self.menuBar().addMenu('&View')
        self.screenshot_action=view.addAction('Save Screenshot...', self.screenshot, QKeySequence('Ctrl+S'))
        view.addAction('Rotate Screen', self.rotate, QKeySequence('Ctrl+R'))
        view.addAction('Full Screen', self.fullscreen, QKeySequence('F11'))
        view.addAction(self.log_action)
        view.addAction(self.keyboard_action)
        self.status_action = QAction('Show Status Bar',self,checkable=True,checked=self.settings['status_bar'])
        self.status_action.toggled.connect(self.show_status_bar)
        view.addAction(self.status_action)
        theme_menu=view.addMenu('Theme')
        self.theme_group=QActionGroup(self);self.theme_group.setExclusive(True)
        for theme in ('Auto','Light','Dark'):
            action=QAction(theme,self,checkable=True,checked=theme==self.settings['theme'])
            action.triggered.connect(lambda checked,t=theme:self.change_theme(t))
            self.theme_group.addAction(action);theme_menu.addAction(action)

        help_menu = self.menuBar().addMenu('&Help')
        help_menu.addAction('System Information...', self.system_info)
        help_menu.addAction('Controls & Shortcuts', self.help)

        self.log_dock = QDockWidget('Emulator Console Log', self)
        self.log_dock.setObjectName('logDock')
        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setMaximumBlockCount(2500)
        self.log_dock.setWidget(self.logs)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.log_dock)
        self.log_dock.hide()
        self.log_dock.visibilityChanged.connect(self.log_action.setChecked)

        self.progress = Spinner()
        self.progress.hide()
        self.status_text=QLabel('')
        self.status_text.setAccessibleName('Emulator status')
        self.status_text.setObjectName('statusText')
        self.status_panel=QWidget()
        status_layout=QHBoxLayout(self.status_panel)
        status_layout.setContentsMargins(7,0,0,0)
        status_layout.setSpacing(6)
        status_layout.addWidget(self.progress)
        status_layout.addWidget(self.status_text,1)
        self.statusBar().addWidget(self.status_panel,1)
        self.status_base_message=''
        self.status_notice_until=0.
        self.fps_label = QLabel('')
        self.fps_label.setObjectName('fpsLabel')
        self.statusBar().addPermanentWidget(self.fps_label)
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().setFixedHeight(22)
        self.statusBar().setVisible(self.settings['status_bar'])
        QApplication.styleHints().colorSchemeChanged.connect(lambda _:self.apply_theme())
        self.apply_theme()
        for key, handler in [('F1', self.go_home), ('F2', lambda: self.key_click(0)),
                             ('F3', lambda: self.key_click(2)), ('F4', lambda: self.key_click(1)),
                             ('F6', lambda: self.key_click(3))]:
            a = QAction(self)
            a.setShortcut(QKeySequence(key))
            a.triggered.connect(handler)
            self.addAction(a)

        self.set_state('stopped', False, 0)
        if auto_start:
            QTimer.singleShot(250, self.start)

    def save_settings(self):
        self.settings_path.parent.mkdir(parents=True,exist_ok=True)
        self.settings_path.write_text(json.dumps(self.settings,indent=2))

    def change_theme(self, theme):
        self.settings['theme']=theme;self.apply_theme();self.save_settings()

    def show_status_bar(self, visible):
        self.statusBar().setVisible(visible);self.settings['status_bar']=visible;self.save_settings()

    def apply_theme(self):
        mode=self.settings['theme']
        dark=mode=='Dark' or (mode=='Auto' and QApplication.styleHints().colorScheme()==Qt.ColorScheme.Dark)
        bg,panel,fg,muted,border,hover=('#121316','#1a1b20','#e2e4ea','#9399a6','#343844','#303747') if dark else ('#f5f5f7','#ffffff','#242832','#8b9099','#d3d7df','#e6ebf4')
        self.foreground=fg
        palette=QPalette()
        for role,value in ((QPalette.ColorRole.Window,bg),(QPalette.ColorRole.WindowText,fg),
            (QPalette.ColorRole.Base,panel),(QPalette.ColorRole.AlternateBase,bg),
            (QPalette.ColorRole.Text,fg),(QPalette.ColorRole.Button,panel),
            (QPalette.ColorRole.ButtonText,fg),(QPalette.ColorRole.ToolTipBase,panel),
            (QPalette.ColorRole.ToolTipText,fg),(QPalette.ColorRole.Highlight,'#438bea'),
            (QPalette.ColorRole.HighlightedText,'#ffffff')):
            palette.setColor(role,QColor(value))
            palette.setColor(QPalette.ColorGroup.Disabled,role,QColor(muted))
        self.setPalette(palette)
        spinner_palette=QPalette(palette)
        spinner_palette.setColor(QPalette.ColorRole.WindowText,QColor('#ffffff' if dark else fg))
        if hasattr(self,'progress'):
            self.progress.color='#ffffff' if dark else fg
            self.progress.setPalette(spinner_palette)
            self.progress.update()
        self.setStyleSheet(f"""
            QWidget {{ color: {fg}; }}
            QMainWindow, QDialog {{ background: {bg}; }}
            QMenuBar, QMenu, QDockWidget, QStatusBar {{ background: {panel}; color: {fg}; }}
            QMenu::item:selected, QMenuBar::item:selected {{ background: {hover}; }}
            QMenu::item:disabled, QWidget:disabled {{ color: {muted}; }}
            QPlainTextEdit, QComboBox, QSpinBox {{ background: {panel}; color: {fg}; border: 1px solid {border}; }}
            QPushButton {{ background: {panel}; color: {fg}; border: 1px solid {border}; border-radius: 4px; padding: 6px 16px; }}
            QPushButton:hover {{ background: {hover}; }}
            QPushButton:default {{ border: 1px solid #438bea; }}
            QComboBox QAbstractItemView {{ background: {panel}; color: {fg}; selection-background-color: #438bea; selection-color: white; }}
            QStatusBar {{ border-top: 1px solid {border}; }}
            QStatusBar::item {{ border: none; }}
            QStatusBar QLabel {{ color: {fg}; padding: 0 4px; }}
            #sidebarSeparator {{ background: {border}; color: {border}; }}
            #mumuSidebar {{ background: {panel}; border: 1px solid {border}; border-radius: 8px; }}
            #mumuSidebar QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 6px; }}
            #mumuSidebar QToolButton:hover:enabled {{ background: {hover}; }}
            #mumuSidebar QToolButton:checked:enabled {{ background: {hover}; border: 1px solid #438bea; }}
            #mumuSidebar QToolButton:pressed {{ background: {border}; }}
            QToolTip {{ background: {panel}; color: {fg}; border: 1px solid {border}; padding: 5px; }}
        """)
        for button in getattr(self,'buttons',[]):
            icon=control_icon(button.accessibleName(),fg)
            disabled=control_icon(button.accessibleName(),muted).pixmap(QSize(24,24))
            icon.addPixmap(disabled,QIcon.Mode.Disabled)
            button.setIcon(icon)
        for action in (getattr(self,'log_action',None),getattr(self,'keyboard_action',None)):
            if action: action.setIcon(control_icon('Logs' if action==getattr(self,'log_action',None) else 'Keyboard',fg))

    def add_sidebar_separator(self, layout):
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        line.setObjectName('sidebarSeparator')
        line.setStyleSheet('max-height: 1px; margin: 2px 2px;')
        layout.addWidget(line)

    def action(self, text, callback, icon, shortcut=None):
        action = QAction(control_icon(text), text, self)
        action.triggered.connect(callback)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        return action

    def side_button(self, layout, text, tooltip, callback, icon, input_button=True):
        button = QToolButton()
        button.setText('')  # MuMu-style icon only
        button.setAccessibleName(text)
        button.setToolTipDuration(10000)
        button.setToolTip(tooltip)  # Popup tooltip on hover
        button.setIcon(control_icon(text))
        button.setIconSize(QSize(22, 22))
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setFixedSize(40, 40)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        if callback:
            button.clicked.connect(callback)
        if input_button:
            self.input_buttons.append(button)
        layout.addWidget(button)
        self.buttons.append(button)
        return button

    def start(self):
        if self.worker:
            return
        self.paused = False
        self.shutting_down = False
        self.stopping = False
        self.auto_home_pending = True
        self.startup_display_at = None
        self.startup_seen_image = False
        self.startup_wake_count = 0
        self.startup_last_wake = 0.
        self.screen.image = QImage()
        self.screen.visual_rate = VisualRate()
        self.startup_unlock_tries = 0
        self.startup_unlock_at = 0.
        self.screen.message = 'Starting iOS...'
        self.screen.update()
        self.worker = Worker(self.settings, self.kernel, self.overlay)
        self.worker.frame.connect(self.new_frame)
        self.worker.state.connect(self.set_state)
        self.worker.log.connect(self.append_log)
        self.worker.finished.connect(self.finished)
        self.set_state('starting', False, 0)
        self.worker.thread.start()

    def new_frame(self, image):
        if self.worker and hasattr(self.worker, 'frame_pending'):
            self.worker.frame_pending.clear()
        if self.stopping or not self.worker: return
        self.screen.image = image
        self.screen.frame_serial += 1
        self.screen.update()
        self.check_startup()

    def check_startup(self):
        # Run from a timer too: unchanged-frame suppression must not suppress
        # startup wake attempts when the framebuffer stays black.
        if not self.worker or self.stopping or self.shutting_down or self.screen.image.isNull(): return
        image=self.screen.image
        if (not self.auto_home_pending and self.stage=='display' and not self.paused and
                0 < self.startup_unlock_tries < 3 and time.monotonic()-self.startup_unlock_at>=8 and
                self.lock_clock_visible(image)):
            self.startup_unlock()
        if self.auto_home_pending and self.stage=='display' and not self.paused:
            now=time.monotonic()
            if self.startup_display_at is None:self.startup_display_at=now
            bright=top_bright=colorful=0
            for y in range(20,image.height(),35):
                for x in range(20,image.width(),35):
                    c=image.pixelColor(x,y)
                    lit=max(c.red(),c.green(),c.blue())>40
                    bright+=lit
                    if y<image.height()//3:
                        top_bright+=lit
                        colorful+=max(c.red(),c.green(),c.blue())-min(c.red(),c.green(),c.blue())>30
            # Dense monochrome boot-console text is not the lock screen.
            if colorful>=8 or (top_bright>=8 and bright<250):
                self.auto_home_pending=False
                self.append_log('Startup: lock/home frame detected; scheduling unlock swipe.')
                QTimer.singleShot(2500,self.startup_unlock)
            elif bright>=8:
                self.startup_seen_image=True
            elif self.startup_seen_image and self.startup_wake_count<12 and now-self.startup_last_wake>=30:
                self.startup_wake_count+=1;self.startup_last_wake=now
                self.append_log(f'Startup: display asleep; waking it ({self.startup_wake_count}/12).')
                self.key_click(0)

    @staticmethod
    def lock_clock_visible(image):
        # Conservative check for the large clock on the current dark lock
        # screen. Ignore bright/full-photo backgrounds and home icon tiles.
        bright=warm=colored=total=0
        for y in range(int(image.height()*.12),int(image.height()*.27),25):
            for x in range(int(image.width()*.2),int(image.width()*.8),25):
                c=image.pixelColor(x,y);total+=1
                lit=max(c.red(),c.green(),c.blue())>60
                bright+=lit
                warm+=c.red()>100 and c.red()>c.green()*1.5 and c.red()>c.blue()*1.5
                colored+=max(c.red(),c.green(),c.blue())-min(c.red(),c.green(),c.blue())>30
        return 25<=bright<total*.55 and (warm>=20 or colored<8)

    def startup_unlock(self):
        if not self.worker or self.stopping or self.shutting_down or self.paused or self.stage!='display':return
        if self.startup_unlock_tries>=3:return
        self.startup_unlock_tries+=1;self.startup_unlock_at=time.monotonic()
        self.append_log(f'Startup: unlock swipe {self.startup_unlock_tries}/3.')
        self.go_home()

    def append_log(self, text):
        self.logs.appendPlainText(text.rstrip())

    def show_status_message(self, text, timeout=0):
        if timeout:
            self.status_notice_until=time.monotonic()+timeout/1000
            self.status_text.setText(text)
            QTimer.singleShot(timeout,lambda:self.status_text.setText(self.status_base_message)
                if time.monotonic()>=self.status_notice_until else None)
        else:
            self.status_base_message=text
            if time.monotonic()>=self.status_notice_until:self.status_text.setText(text)

    def set_state(self, stage, input_ready, fps):
        if self.stopping and stage != 'stopped': return
        self.stage=stage
        active = stage != 'stopped'
        self.start_action.setEnabled(not active)
        self.pause_action.setEnabled(active and stage in ('display','paused'))
        self.stop_action.setEnabled(active)
        self.restart_action.setEnabled(active and stage not in ('shutting-down','shutdown-stalled'))
        shutdown_ready = bool(self.worker and self.worker.session and self.worker.session.header and self.worker.session.header[7]&4)
        self.shutdown_action.setEnabled(stage=='display' and shutdown_ready)
        self.settings_button.setEnabled(not self.shutting_down)
        self.settings_action.setEnabled(not self.shutting_down)
        self.screen.enabled_input = active and input_ready and stage == 'display'
        self.screenshot_button.setEnabled(active and not self.screen.image.isNull())
        self.screenshot_action.setEnabled(active and not self.screen.image.isNull())
        keyboard_ready = bool(self.worker and self.worker.session and self.worker.session.header and self.worker.session.header[7]&1)
        self.keyboard_action.setEnabled(self.screen.enabled_input and keyboard_ready)
        self.keyboard_button.setEnabled(self.screen.enabled_input and keyboard_ready)
        self.screen.capture_keyboard = self.keyboard_action.isChecked() and keyboard_ready
        for b in self.input_buttons:
            b.setEnabled(self.screen.enabled_input)
        messages = {
            'stopped': 'Ready',
            'starting': 'Starting emulator...',
            'booting': 'Booting iOS...',
            'services': 'Starting iOS services...',
            'springboard': 'Launching SpringBoard...',
            'display': 'Preparing iOS display...' if self.auto_home_pending else 'iOS running',
            'paused': 'Paused',
            'shutting-down': 'Shutting down iOS...',
            'shutdown-stalled': 'Shutdown is taking longer; Force Stop is available.',
            'panic': 'iOS stopped due to a kernel panic. See logs.'
        }
        self.show_status_message(messages.get(stage, stage))
        self.progress.setVisible(stage in ('starting', 'booting', 'services', 'springboard', 'shutting-down') or (stage=='display' and self.auto_home_pending))
        self.capture_fps = fps
        visual_fps = self.screen.visual_rate.fps() if active and not self.paused else 0.
        self.fps_label.setText(f'Visual: {visual_fps:.1f} fps' if active else '')
        session=self.worker.session if self.worker else None
        if session:
            guest_rate=getattr(session,'guest_present_fps',None)
            guest_text=f'{guest_rate:.1f} fps' if guest_rate is not None else 'unavailable'
            self.fps_label.setToolTip(
                f"Visual changes painted: {visual_fps:.1f} fps\n"
                f"Capture target: {self.settings['fps']} fps\nChanged frames captured: {fps:.1f} fps\n"
                f"iOS framebuffer presentations: {guest_text} (may repeat pixels)\n"
                f"Frame export: {getattr(session,'frame_export_ms',0.):.1f} ms\n"
                'Unchanged frames are skipped; a still screen may show 0 fps.')

    def pause(self):
        if self.worker:
            self.screen.release_touch()
            self.screen.release_keys()
            self.paused = not self.paused
            self.worker.submit('pause', self.paused)
            self.pause_action.setText('Resume' if self.paused else 'Pause')

    def shutdown(self):
        if self.worker and self.screen.enabled_input:
            self.screen.release_touch();self.screen.release_keys()
            self.shutting_down = True
            self.worker.submit('shutdown')
            self.set_state('shutting-down',False,0)

    def stop(self):
        if self.worker:
            self.screen.release_touch()
            self.screen.release_keys()
            self.stopping=True
            self.screen.enabled_input=False
            self.screen.image=QImage();self.screen.message='';self.screen.update()
            for button in self.input_buttons+[self.keyboard_button,self.screenshot_button]: button.setEnabled(False)
            for action in (self.start_action,self.pause_action,self.stop_action,self.restart_action,self.keyboard_action,self.screenshot_action): action.setEnabled(False)
            self.worker.stopping.set()
            self.show_status_message('Stopping emulator...')

    def restart(self):
        if self.worker:
            self.restarting = True
            self.stop()

    def finished(self, error):
        shutdown_completed = bool(self.worker and self.worker.session and self.worker.session.stage=='shutdown')
        self.worker = None
        self.shutting_down = False
        self.stopping = False
        self.screen.image=QImage();self.screen.message='';self.screen.update()
        self.paused = False
        self.pause_action.setText('Pause')
        self.set_state('stopped', False, 0)
        if shutdown_completed and not error:
            self.show_status_message('iOS shut down',6000)
        if error:
            self.append_log(error)
            self.log_dock.show()
            QMessageBox.warning(self, 'Emulator Error', error)
        if self.restarting:
            self.restarting = False
            QTimer.singleShot(100, self.start)

    def touch(self, down, x, y):
        if self.worker:
            self.worker.submit('input', 1, 0, down, x, y)

    def capture_keyboard(self, enabled):
        self.screen.release_keys();self.screen.capture_keyboard=enabled
        if enabled:self.screen.setFocus()

    def keyboard(self, usage, down):
        if self.worker and not self.stopping:
            self.worker.submit('input',3,usage,down,0,0)

    def paste_text(self, text):
        if self.worker and not self.stopping:
            self.worker.submit('text',text)

    def key(self, code, down):
        if self.worker and self.screen.enabled_input:
            self.worker.submit('input', 2, code, down, 0, 0)

    def key_click(self, code):
        self.key(code, True)
        QTimer.singleShot(110, lambda: self.key(code, False))

    def go_home(self):
        if self.worker and self.screen.enabled_input:
            # D22AP is a Face ID phone. Mirror the actual edge swipe observed
            # unlocking this guest; consumer Menu events can be ignored at lock.
            self.worker.submit('gesture', 540, 2380, 540, 1365, .40, 0.)

    def app_switcher(self):
        if self.worker and self.screen.enabled_input:
            self.worker.submit('gesture', 540, 2390, 540, 1450, .4, .65)

    def rotate(self):
        self.screen.release_touch()
        self.screen.rotation = 90 if not self.screen.rotation else 0
        self.screen.update()

    def fullscreen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def screenshot(self):
        if self.screen.image.isNull():
            return
        folder = ROOT / 'data/screenshots'
        folder.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(self, 'Save Screenshot', str(folder / time.strftime('iOS-%Y%m%d-%H%M%S.png')), 'PNG Images (*.png)')
        if path:
            if self.screen.image.save(path):
                self.show_status_message('Screenshot saved', 5000)
            else:
                QMessageBox.warning(self, 'Screenshot', 'Failed to save screenshot image.')

    def preferences(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('Emulator Settings')
        form = QFormLayout(dialog)
        limits=host_limits()
        def choices(values, current, suffix=''):
            box=QComboBox()
            for value in sorted(set(values) | {current}):
                box.addItem(f'{value}{suffix}',value)
            box.setCurrentIndex(box.findData(current))
            return box
        ram=choices(range(1024,limits['memory_mib']+1,256),self.settings['memory_mib'],' MiB')
        rate=choices([n for n in (5,10,15,20,24,30,45,60,90,120) if n<=limits['fps']],self.settings['fps'],' fps')
        cores=choices(range(1,limits['cpu_count']+1),self.settings['cpu_count'])
        ram.setEnabled(not bool(self.worker))
        cores.setEnabled(not bool(self.worker))
        form.addRow('CPU cores:',cores)
        form.addRow('iOS memory:',ram)
        form.addRow('Display refresh target:',rate)
        note=QLabel(f"Host: {limits['host_mib']/1024:.1f} GiB RAM, {os.cpu_count()} logical CPUs.\n"
            f"Host RAM budget: 80% (QEMU overhead reserved).\n"
            f"Current QEMU guest limit: 4 GiB RAM / 4 CPUs.\n"
            "A higher refresh target does not guarantee faster guest rendering.\n"
            "Refresh target can change live; stop iOS to change CPU or memory.\n"
            "Graphics: Software. Vulkan / OpenGL guest acceleration is under development.")
        note.setWordWrap(True);form.addRow(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.settings.update(memory_mib=ram.currentData(),fps=rate.currentData(),cpu_count=cores.currentData())
            if self.worker:
                self.worker.submit('refresh', rate.currentData())
            self.save_settings()

    def system_info(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('System Information')
        dialog.resize(650, 700)
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setAccessibleName('System information and display measurements')
        layout.addWidget(text)
        def refresh():
            session = self.worker.session if self.worker else None
            value = system_information(ROOT, self.settings, host_limits(), session,
                self.screen.visual_rate.fps() if not self.paused and self.worker else 0.,
                getattr(self, 'capture_fps', 0.))
            scroll = text.verticalScrollBar().value()
            text.setPlainText(value)
            text.verticalScrollBar().setValue(scroll)
        refresh()
        timer = QTimer(dialog)
        timer.timeout.connect(refresh)
        timer.start(1000)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def help(self):
        msg = (
            "Mouse Controls:\n"
            " â€¢ Click: Touch screen\n"
            " â€¢ Drag: Swipe gestures\n\n"
            "Shortcuts:\n"
            " â€¢ Home / F1: Return to Home Screen\n"
            " â€¢ Apps: Open App Switcher\n"
            " â€¢ F2: Power Button (Lock/Unlock)\n"
            " â€¢ F4: Volume Up\n"
            " â€¢ F3: Volume Down\n"
            " â€¢ Ctrl+P: Pause / Resume\n"
            " â€¢ Ctrl+S: Save Screenshot\n"
            " â€¢ Ctrl+R: Rotate Screen\n"
            " â€¢ F11: Toggle Full Screen\n\n"
            "Click the iOS display to capture the PC keyboard (kernel 0091+).\nCtrl+V pastes printable ASCII from the host clipboard (US layout)."
        )
        QMessageBox.information(self, "Emulator Controls", msg)

    def closeEvent(self, event):
        if self.worker:
            self.worker.stopping.set()
            self.worker.thread.join(timeout=8)
            if self.worker.thread.is_alive() and self.worker.session and self.worker.session.process:
                self.worker.session.process.kill()
        event.accept()


def main(auto_start=True, kernel=None, overlay=None):
    if sys.platform == 'win32':
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('MRHRTZ.iOSEmulator')
    app = QApplication([sys.argv[0]])
    app.setWindowIcon(QIcon(str(ROOT / 'assets/app-icon.ico')))
    app.setApplicationName('iOS Emulator')
    app.setOrganizationName('MRHRTZ')
    for style in ('windowsvista', 'Windows'):
        if style.lower() in [s.lower() for s in QStyleFactory.keys()]:
            app.setStyle(style)
            break
    window = Window(auto_start, kernel, overlay)
    window.show()
    return app.exec()


if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-start',action='store_true')
    parser.add_argument('--kernel',type=Path,help='Matching kernel for a controlled comparison')
    parser.add_argument('--overlay',type=Path,help='Writable qcow2 overlay (never a raw base image)')
    args=parser.parse_args()
    raise SystemExit(main(auto_start=not args.no_start,kernel=args.kernel,overlay=args.overlay))
