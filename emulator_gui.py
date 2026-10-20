"""Native Windows controls around the live iOS framebuffer; MuMu-style sidebar and English UI."""
import heapq
import json
from pathlib import Path
import queue
import sys
import threading
import time

from PySide6.QtCore import Qt, QEvent, QPointF, QRectF, QSize, Signal, QObject, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QImage, QKeySequence, QPainter, QPen, QPixmap, QPolygonF, QTransform
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QDialogButtonBox,
    QDockWidget, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
    QPlainTextEdit, QProgressBar, QSizePolicy, QStyle, QStyleFactory, QToolBar,
    QToolButton, QToolTip, QVBoxLayout, QWidget)

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'data/python-deps'))
from pc_session import PcSession, FB_WIDTH, FB_HEIGHT, map_pointer


def control_icon(name):
    """Clear monochrome control glyphs on the dark native Qt button surfaces."""
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor('#d9dce5'), 1.7, Qt.PenStyle.SolidLine,
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
        painter.drawArc(QRectF(4, 4, 16, 16), 55 * 16, 250 * 16)
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
        scheduled = []
        order = 0
        next_frame = next_poll = 0
        frames, fps, measured = 0, 0., time.monotonic()
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
                    if command[0] == 'pause':
                        scheduled.clear()
                        paused = bool(command[1])
                        self.session.pause(paused)
                    elif command[0] == 'input' and not paused and self.session.input_ready:
                        order += 1
                        heapq.heappush(scheduled, (now, order, command[1:]))
                    elif command[0] == 'gesture' and not paused and self.session.input_ready:
                        _, x0, y0, x1, y1, duration, hold = command
                        for step in range(17):
                            x, y = round(x0 + (x1 - x0) * step / 16), round(y0 + (y1 - y0) * step / 16)
                            order += 1
                            heapq.heappush(scheduled, (now + duration * step / 16, order, (1, 0, True, x, y)))
                        order += 1
                        heapq.heappush(scheduled, (now + duration + hold + .03, order, (1, 0, False, x1, y1)))
                while scheduled and scheduled[0][0] <= time.monotonic() and not paused:
                    due, sequence, event = scheduled[0]
                    if not self.session.input(*event):
                        break
                    heapq.heappop(scheduled)
                if now >= next_poll:
                    delta = self.session.poll()
                    if delta:
                        self.log.emit(delta)
                    self.state.emit('paused' if paused else self.session.stage, self.session.input_ready, fps)
                    next_poll = now + .25
                if now >= next_frame:
                    data = self.session.frame()
                    image = QImage(data, FB_WIDTH, FB_HEIGHT, FB_WIDTH * 4, QImage.Format.Format_RGB32).copy()
                    self.frame.emit(image)
                    frames += 1
                    interval = 2. if self.session.stage == 'booting' else (.5 if self.session.stage in ('services', 'springboard') else 1 / self.settings['fps'])
                    next_frame = time.monotonic() + interval
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

    def __init__(self):
        super().__init__()
        self.image = QImage()
        self.rotation = 0
        self.down = False
        self.enabled_input = False
        self.last = (540, 1200)
        self.last_move = 0
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

    def focusOutEvent(self, event):
        self.release_touch()
        super().focusOutEvent(event)


class Window(QMainWindow):
    def __init__(self, auto_start=True, kernel=None, overlay=None):
        super().__init__()
        self.setWindowTitle('iOS Emulator')
        self.setObjectName('iosEmulatorWindow')
        self.setMinimumSize(540, 600)
        self.resize(650, min(980, QApplication.primaryScreen().availableGeometry().height() - 60))
        self.worker = None
        self.paused = False
        self.restarting = False
        self.kernel, self.overlay = kernel, overlay
        self.settings_path = ROOT / 'data/gui/settings.json'
        self.settings = {'memory_mib': 2048, 'fps': 15, 'cpu_count': 1}
        if self.settings_path.exists():
            try:
                saved = json.loads(self.settings_path.read_text())
                if saved.get('cpu_count') in (1, 2, 4):
                    self.settings['cpu_count'] = saved['cpu_count']
                if saved.get('memory_mib') in (1024, 2048, 3072, 4096):
                    self.settings['memory_mib'] = saved['memory_mib']
                if saved.get('fps') in (5, 10, 15, 20, 30):
                    self.settings['fps'] = saved['fps']
            except (OSError, ValueError):
                pass

        self.apply_theme()

        self.screen = Screen()
        self.screen.touch.connect(self.touch)

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
        self.home = self.side_button(rail, 'Home', 'Home Screen (F1 / Esc)', self.go_home, QStyle.StandardPixmap.SP_ArrowUp)
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

        self.side_button(rail, 'Screenshot', 'Save Screenshot (Ctrl+S)', self.screenshot, QStyle.StandardPixmap.SP_DialogSaveButton, False)
        self.side_button(rail, 'Rotate', 'Rotate Screen 90° (Ctrl+R)', self.rotate, QStyle.StandardPixmap.SP_BrowserReload, False)
        self.side_button(rail, 'Fullscreen', 'Full Screen (F11)', self.fullscreen, QStyle.StandardPixmap.SP_TitleBarMaxButton, False)

        rail.addStretch(1)

        self.settings_button = self.side_button(rail, 'Settings', 'Settings (CPU, Memory & Refresh Rate)', self.preferences, QStyle.StandardPixmap.SP_ComputerIcon, False)
        layout.addWidget(sidebar_frame)
        self.setCentralWidget(center)

        toolbar = QToolBar('Controls')
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(toolbar)

        self.start_action = self.action('Start', self.start, QStyle.StandardPixmap.SP_MediaPlay, 'Ctrl+Return')
        self.pause_action = self.action('Pause', self.pause, QStyle.StandardPixmap.SP_MediaPause, 'Ctrl+P')
        self.stop_action = self.action('Stop', self.stop, QStyle.StandardPixmap.SP_MediaStop)
        self.restart_action = self.action('Restart', self.restart, QStyle.StandardPixmap.SP_BrowserReload, 'F5')
        for action in (self.start_action, self.pause_action, self.stop_action, self.restart_action):
            toolbar.addAction(action)

        self.log_action = QAction('Logs', self, checkable=True)
        self.log_action.triggered.connect(lambda checked: self.log_dock.setVisible(checked))
        toolbar.addSeparator()
        toolbar.addAction(self.log_action)

        menu = self.menuBar().addMenu('&Emulator')
        for a in (self.start_action, self.pause_action, self.stop_action, self.restart_action):
            menu.addAction(a)
        menu.addSeparator()
        menu.addAction('Settings...', self.preferences)
        menu.addSeparator()
        menu.addAction('Exit', self.close, QKeySequence('Alt+F4'))

        view = self.menuBar().addMenu('&View')
        view.addAction('Save Screenshot...', self.screenshot, QKeySequence('Ctrl+S'))
        view.addAction('Rotate Screen', self.rotate, QKeySequence('Ctrl+R'))
        view.addAction('Full Screen', self.fullscreen, QKeySequence('F11'))
        view.addAction(self.log_action)

        help_menu = self.menuBar().addMenu('&Help')
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

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedWidth(85)
        self.progress.hide()
        self.statusBar().addPermanentWidget(self.progress)

        self.fps_label = QLabel('')
        self.statusBar().addPermanentWidget(self.fps_label)

        for key, handler in [('F1', self.go_home), ('Escape', self.go_home), ('F2', lambda: self.key_click(0)),
                             ('F3', lambda: self.key_click(2)), ('F4', lambda: self.key_click(1))]:
            a = QAction(self)
            a.setShortcut(QKeySequence(key))
            a.triggered.connect(handler)
            self.addAction(a)

        self.set_state('stopped', False, 0)
        if auto_start:
            QTimer.singleShot(250, self.start)

    def apply_theme(self):
        self.setStyleSheet("""
            QMainWindow {
                background-color: #121316;
            }
            QToolBar {
                background-color: #1a1b20;
                border-bottom: 1px solid #2a2d36;
                spacing: 6px;
                padding: 3px 8px;
            }
            QToolBar QToolButton {
                color: #e2e4ea;
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 12px;
            }
            QToolBar QToolButton:hover {
                background-color: #2b2e38;
                border-color: #3d414e;
            }
            QToolBar QToolButton:pressed {
                background-color: #3b3e4a;
            }
            QMenuBar {
                background-color: #1a1b20;
                color: #d1d4dc;
                border-bottom: 1px solid #25272e;
            }
            QMenuBar::item:selected {
                background-color: #2b2e38;
            }
            QMenu {
                background-color: #1f2026;
                color: #e2e4ea;
                border: 1px solid #333642;
                padding: 4px;
            }
            QMenu::item:selected {
                background-color: #2e313c;
                border-radius: 4px;
            }
            QStatusBar {
                background-color: #16171b;
                color: #9ba0ad;
                border-top: 1px solid #23252c;
            }
            #mumuSidebar {
                background-color: #1a1b20;
                border: 1px solid #2a2d36;
                border-radius: 8px;
            }
            #mumuSidebar QToolButton {
                background-color: transparent;
                border: none;
                border-radius: 6px;
            }
            #mumuSidebar QToolButton:hover {
                background-color: #2f323e;
            }
            #mumuSidebar QToolButton:pressed {
                background-color: #404452;
            }
            #mumuSidebar QToolButton:disabled {
                background-color: #16171b;
            }
            QToolTip {
                background-color: #22242c;
                color: #ffffff;
                border: 1px solid #3d414f;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 11px;
            }
        """)

    def add_sidebar_separator(self, layout):
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        line.setStyleSheet('background-color: #2a2d36; max-height: 1px; margin: 2px 2px;')
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
        return button

    def start(self):
        if self.worker:
            return
        self.paused = False
        self.worker = Worker(self.settings, self.kernel, self.overlay)
        self.worker.frame.connect(self.new_frame)
        self.worker.state.connect(self.set_state)
        self.worker.log.connect(self.append_log)
        self.worker.finished.connect(self.finished)
        self.set_state('starting', False, 0)
        self.worker.thread.start()

    def new_frame(self, image):
        self.screen.image = image
        self.screen.update()

    def append_log(self, text):
        self.logs.appendPlainText(text.rstrip())

    def set_state(self, stage, input_ready, fps):
        active = stage != 'stopped'
        self.start_action.setEnabled(not active)
        self.pause_action.setEnabled(active and stage != 'starting')
        self.stop_action.setEnabled(active)
        self.restart_action.setEnabled(active)
        self.settings_button.setEnabled(not active)
        self.screen.enabled_input = active and input_ready and stage not in ('paused', 'panic')
        for b in self.input_buttons:
            b.setEnabled(self.screen.enabled_input)
        messages = {
            'stopped': 'Ready',
            'starting': 'Starting emulator...',
            'booting': 'Booting iOS...',
            'services': 'Starting iOS services...',
            'springboard': 'Launching SpringBoard...',
            'display': 'iOS running',
            'paused': 'Paused',
            'panic': 'iOS stopped due to a kernel panic. See logs.'
        }
        self.statusBar().showMessage(messages.get(stage, stage))
        self.progress.setVisible(stage in ('starting', 'booting', 'services', 'springboard'))
        self.fps_label.setText(f'{fps:.1f} fps' if active else '')

    def pause(self):
        if self.worker:
            self.screen.release_touch()
            self.paused = not self.paused
            self.worker.submit('pause', self.paused)
            self.pause_action.setText('Resume' if self.paused else 'Pause')

    def stop(self):
        if self.worker:
            self.screen.release_touch()
            self.worker.stopping.set()
            self.statusBar().showMessage('Stopping emulator...')

    def restart(self):
        if self.worker:
            self.restarting = True
            self.stop()

    def finished(self, error):
        self.worker = None
        self.paused = False
        self.pause_action.setText('Pause')
        self.set_state('stopped', False, 0)
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

    def key(self, code, down):
        if self.worker and self.screen.enabled_input:
            self.worker.submit('input', 2, code, down, 0, 0)

    def key_click(self, code):
        self.key(code, True)
        QTimer.singleShot(110, lambda: self.key(code, False))

    def go_home(self):
        if self.worker and self.screen.enabled_input:
            self.worker.submit('gesture', 540, 2390, 540, 1450, .35, 0.)

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
                self.statusBar().showMessage('Screenshot saved', 5000)
            else:
                QMessageBox.warning(self, 'Screenshot', 'Failed to save screenshot image.')

    def preferences(self):
        if self.worker:
            QMessageBox.information(self, 'Settings', 'Please stop the emulator before changing settings.')
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('Emulator Settings')
        form = QFormLayout(dialog)
        ram = QComboBox()
        for value in (1024, 2048, 3072, 4096):
            ram.addItem(f'{value // 1024} GB', value)
        ram.setCurrentIndex(ram.findData(self.settings['memory_mib']))
        rate = QComboBox()
        for value in (5, 10, 15, 20, 30):
            rate.addItem(f'{value} fps', value)
        rate.setCurrentIndex(rate.findData(self.settings['fps']))
        cores = QComboBox()
        for value in (1, 2, 4):
            cores.addItem(f'{value} core' if value == 1 else f'{value} cores', value)
        cores.setCurrentIndex(cores.findData(self.settings['cpu_count']))
        form.addRow('CPU cores:', cores)
        form.addRow('iOS Memory (RAM):', ram)
        form.addRow('Screen Refresh Rate:', rate)
        note = QLabel('Note: Guest changes are stored on the session overlay disk.\nThe base iOS firmware remains clean and untouched.')
        note.setStyleSheet('color: #8c909c; font-size: 11px; margin-top: 6px;')
        form.addRow(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.settings = {'memory_mib': ram.currentData(), 'fps': rate.currentData(), 'cpu_count': cores.currentData()}
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            self.settings_path.write_text(json.dumps(self.settings, indent=2))

    def help(self):
        msg = (
            "Mouse Controls:\n"
            " • Click: Touch screen\n"
            " • Drag: Swipe gestures\n\n"
            "Shortcuts:\n"
            " • Home / F1 / Esc: Return to Home Screen\n"
            " • Apps: Open App Switcher\n"
            " • F2: Power Button (Lock/Unlock)\n"
            " • F4: Volume Up\n"
            " • F3: Volume Down\n"
            " • Ctrl+P: Pause / Resume\n"
            " • Ctrl+S: Save Screenshot\n"
            " • Ctrl+R: Rotate Screen\n"
            " • F11: Toggle Full Screen\n\n"
            "Type using the on-screen iOS keyboard."
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
    app = QApplication([sys.argv[0]])
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
    raise SystemExit(main(auto_start='--no-start' not in sys.argv))
