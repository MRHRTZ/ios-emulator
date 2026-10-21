"""Optional GPU presentation of the software-rendered iOS framebuffer."""
from functools import lru_cache

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QOffscreenSurface, QOpenGLContext, QPainter
from PySide6.QtOpenGLWidgets import QOpenGLWidget


@lru_cache(maxsize=1)
def opengl_capability():
    if QGuiApplication.platformName() in ('offscreen', 'minimal'):
        return {'available': False, 'reason': 'This Qt platform has no OpenGL widget support.'}
    surface = QOffscreenSurface()
    surface.create()
    context = QOpenGLContext()
    try:
        if not surface.isValid() or not context.create() or not context.makeCurrent(surface):
            return {'available': False, 'reason': 'An OpenGL context could not be created.'}
        functions = context.functions()
        renderer = functions.glGetString(0x1f01) or 'Unknown renderer'
        vendor = functions.glGetString(0x1f00) or 'Unknown vendor'
        version = functions.glGetString(0x1f02) or 'Unknown version'
        software = any(s in renderer.lower() for s in ('llvmpipe', 'softpipe', 'software', 'gdi generic', 'swiftshader', 'basic render'))
        return dict(available=True, renderer=renderer, vendor=vendor, version=version,
                    hardware=not software and renderer != 'Unknown renderer' and vendor != 'Unknown vendor', reason='')
    finally:
        context.doneCurrent()
        surface.destroy()


def resolve_renderer(mode, capability):
    if mode not in ('Auto', 'Software', 'OpenGL'):
        raise ValueError('Vulkan presentation is not implemented; use Auto, Software or OpenGL.')
    if mode == 'Software':
        return 'Software'
    if capability.get('available') and (mode == 'OpenGL' or capability.get('hardware')):
        return 'OpenGL'
    return 'Software'


class GLViewport(QOpenGLWidget):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.drawn_serial = 0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.frameSwapped.connect(self.presented)

    def initializeGL(self):
        renderer = self.context().functions().glGetString(0x1f01)
        self.owner.renderer_description = f'OpenGL / {renderer or "Unknown renderer"}'

    def paintGL(self):
        painter = QPainter(self)
        self.owner.paint_frame(painter, count=False)
        painter.end()
        if not self.owner.image.isNull():
            self.drawn_serial = self.owner.frame_serial
        else:
            self.drawn_serial = 0

    def presented(self):
        if self.drawn_serial:
            self.owner.visual_rate.painted(self.drawn_serial)
