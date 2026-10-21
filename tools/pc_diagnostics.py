"""Small, explicit display measurements and shareable system information."""
from collections import deque
import json
import os
from pathlib import Path
import platform
import time


class VisualRate:
    """Count distinct images actually painted in a trailing two-second window.

    A repaint of the same image (resize, expose, cursor) is not an animation
    frame. Idle windows correctly decay to zero instead of reporting a target.
    """
    def __init__(self, window=2.):
        self.window = window
        self.times = deque()
        self.serial = 0

    def painted(self, serial, now=None):
        if serial != self.serial:
            self.serial = serial
            self.times.append(time.monotonic() if now is None else now)

    def fps(self, now=None):
        now = time.monotonic() if now is None else now
        while self.times and self.times[0] <= now-self.window:
            self.times.popleft()
        return len(self.times)/self.window


def system_information(root, settings, limits, session=None, visual_fps=0., capture_fps=0.):
    """No account names, paths, network identifiers or hardware serials."""
    cpu = platform.processor() or platform.machine()
    if os.name == 'nt':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                    r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as key:
                cpu = winreg.QueryValueEx(key, 'ProcessorNameString')[0].strip()
        except OSError:
            pass
    try:
        root_info = json.loads((Path(root)/'data/root/ready.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        root_info = {}
    def metric(value, suffix=''):
        return 'Unavailable' if value is None else f'{value:.1f}{suffix}'
    metadata = getattr(session, 'video_metadata', None) or {}
    return '\n'.join([
        'WINDOWS HOST',
        f'OS: {platform.system()} {platform.release()} (build {platform.version()})',
        f'CPU: {cpu}',
        f'Logical CPUs: {os.cpu_count()}    RAM: {limits["host_mib"]/1024:.1f} GiB',
        f'Python: {platform.python_version()} ({platform.machine()})',
        '',
        'EMULATED iOS',
        f'iOS root metadata: {root_info.get("version", "Unavailable")} ({root_info.get("build", "Unavailable")})',
        'Device baseline: iPhone X / iPhone10,3',
        f'CPU: Cortex-A76 / ARM64, {settings["cpu_count"]} vCPUs',
        f'Memory: {settings["memory_mib"]} MiB',
        'CPU execution: QEMU TCG (software translation)',
        'Graphics: software framebuffer; iOS GPU acceleration unavailable',
        'Output framebuffer: 1080 x 2400, BGRA, 9.89 MiB/frame',
        '',
        'DISPLAY MEASUREMENTS (trailing ~2 seconds)',
        f'Visual changes painted: {visual_fps:.1f} fps',
        f'Changed frames captured: {capture_fps:.1f} fps',
        f'iOS framebuffer presentations: {metric(getattr(session, "guest_present_fps", None), " /s")}',
        f'Capture target: {settings["fps"]} fps (not animation speed)',
        f'Transport: {getattr(session, "frame_transport", "Not running")}',
        f'Last frame export: {getattr(session, "frame_export_ms", 0.):.1f} ms',
        f'Last iOS panel copy: {metric(metadata.get("copy_us", 0)/1000, " ms")}',
        f'Identical captures skipped: {getattr(session, "duplicate_frames", 0)}',
        'Static screens may show 0 fps. Presentations may repeat pixels.',
        '',
        'Host = Windows. Guest = the iOS system running inside QEMU.',
    ])
