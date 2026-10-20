"""Live QEMU framebuffer and bounded HID input for the Windows desktop GUI."""
import base64
import importlib.util
import json
import math
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import time

FB_ADDRESS, FB_WIDTH, FB_HEIGHT = 0x9c000000, 1080, 2400
INPUT_ADDRESS, INPUT_MAGIC, INPUT_SLOTS = 0x9e000000, 0x4e495753, 64


class QTest:
    def __init__(self, port):
        self.socket = socket.create_connection(('127.0.0.1', port), timeout=5)
        self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.stream = self.socket.makefile('rwb')

    def command(self, text):
        self.stream.write(text.encode('ascii') + b'\n')
        self.stream.flush()
        while True:
            response = self.stream.readline(24 * 1024**2)
            if response.startswith(b'IRQ '):
                continue
            if not response.startswith(b'OK'):
                raise RuntimeError('QEMU memory channel failed: ' + repr(response[:120]))
            return response[2:].strip()

    def read(self, address, size):
        data = base64.b64decode(self.command(f'b64read {address:#x} {size}'), validate=True)
        if len(data) != size:
            raise RuntimeError('Incomplete QEMU framebuffer/memory response')
        return data

    def write(self, address, data):
        self.command(f'write {address:#x} {len(data)} 0x{data.hex()}')

    def write32(self, address, value):
        self.command(f'writel {address:#x} {value:#x}')

    def close(self):
        self.stream.close()
        self.socket.close()


class QMP:
    def __init__(self, port):
        self.socket = socket.create_connection(('127.0.0.1', port), timeout=5)
        self.stream = self.socket.makefile('rwb')
        greeting = json.loads(self.stream.readline())
        if 'QMP' not in greeting:
            raise RuntimeError('Invalid QMP greeting')
        self.call('qmp_capabilities')

    def call(self, command, **arguments):
        self.stream.write(json.dumps({'execute': command, 'arguments': arguments}).encode() + b'\n')
        self.stream.flush()
        while True:
            item = json.loads(self.stream.readline())
            if 'error' in item:
                raise RuntimeError(str(item['error']))
            if 'return' in item:
                return item['return']

    def close(self):
        self.stream.close()
        self.socket.close()


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def map_pointer(px, py, left, top, width, height, rotation=0, clamp=False):
    if width <= 0 or height <= 0:
        return None
    if not clamp and not (left <= px <= left+width and top <= py <= top+height):
        return None
    u = max(0., min(1., (px-left)/width))
    v = max(0., min(1., (py-top)/height))
    x, y = (u*FB_WIDTH, v*FB_HEIGHT) if rotation == 0 else (v*FB_WIDTH, (1-u)*FB_HEIGHT)
    return min(FB_WIDTH-1, int(x)), min(FB_HEIGHT-1, int(y))


class PcSession:
    def __init__(self, root, memory_mib=2048, kernel=None, overlay=None, cpu_count=1):
        self.root = Path(root)
        self.kernel = Path(kernel) if kernel else self.root / 'xnu/out/kernel.development.sweet'
        self.memory_mib = memory_mib
        self.cpu_count = cpu_count
        self.overlay = Path(overlay) if overlay else self.root / 'data/gui/ios-session.qcow2'
        self.process = None
        self.qtest = self.qmp = None
        self.lock_file = self.errors = None
        self.input_ready = False
        self.header = None
        self.serial_position = 0
        self.serial_tail = ''
        self.stage = 'stopped'
        self.last_status = 0
        self.held_inputs = {}

    def start(self):
        import adt
        import mkadt
        import root_builder
        if self.cpu_count not in (1, 2, 4):
            raise ValueError('CPU count must be 1, 2, or 4')
        if not 256 <= self.memory_mib <= 4096:
            raise ValueError('RAM must be between 256 and 4096 MiB')
        base = self.root / 'data/root/ios-root.img'
        if not base.is_file() or not self.kernel.is_file():
            raise ValueError('iOS kernel or base disk missing. Complete prepare-root first.')
        if not root_builder.hfs_header(base)['clean']:
            raise ValueError('iOS base disk is dirty. Please run filesystem check first.')
        self.overlay.parent.mkdir(parents=True, exist_ok=True)
        self.lock_file = self.overlay.with_suffix('.lock').open('a+b')
        self.lock_file.write(b'0'); self.lock_file.flush(); self.lock_file.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lock_file.close(); self.lock_file = None
            raise ValueError('Another iOS session is currently running on this disk. Stop it before starting a new one.')
        spec = importlib.util.spec_from_file_location('pc_qemu_runner', self.root / 'tools/qemu-sweet.py')
        self.runner = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.runner)
        qemu = self.runner.find_qemu()
        if not qemu:
            raise ValueError('QEMU ARM64 binary not found. Please install QEMU.')
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        symbols = subprocess.check_output(['llvm-nm', '--defined-only', str(self.kernel)], text=True, creationflags=flags)
        if self.cpu_count > 1 and '_sweet_pc_smp_enabled' not in symbols:
            raise ValueError('This kernel supports only one QEMU CPU. Install a kernel with patch 0087.')
        if 'pcInputFired' not in symbols or '_sweet_virtio_rootdev' not in symbols:
            raise ValueError('Kernel does not support PC control. Use build with patch 0084 or newer.')

        if not self.overlay.exists():
            image_tool = Path(qemu).with_name('qemu-img.exe' if os.name == 'nt' else 'qemu-img')
            subprocess.run([str(image_tool), 'create', '-f', 'qcow2', '-F', 'raw', '-b', str(base), str(self.overlay)],
                           check=True, creationflags=flags, stdout=subprocess.DEVNULL)
        self.out = self.root / 'data/gui/runs' / (time.strftime('%Y%m%d-%H%M%S') + f'-{time.time_ns() % 1000000:06d}')
        self.out.mkdir(parents=True)
        tree = mkadt.build(qemu=True, memory_mib=self.memory_mib, cpu_count=self.cpu_count)
        tree.children.append(mkadt.node('sweet-pc-input', [('reg', mkadt.u64(INPUT_ADDRESS, 0x4000))]))
        tree_path = self.out / 'pc.adt'; tree_path.write_bytes(adt.serialize(tree))
        payload_path = self.out / 'payload.bin'
        line = (f'debug=0xc serial=3 cpus={self.cpu_count} keepsyms=1 -enable_kprintf_spam -noprogress '
                'sweettouch=0 sweetkeys=0 sweetusb=0 sweetlog=0 rd=vioroot0 viorw=1 rootrw=1 '
                'unentitled_ios_sim_launch=1 ignition_level=1 launchd_unsecure_cache=1 '
                'wdt=-1 wdt_test=no_user_checkin sweetfb_noconsole=1 sweetfb_hz=30')
        subprocess.run([sys.executable, str(self.root/'tools/mkpayload.py'), str(self.kernel), str(tree_path),
                        str(payload_path), '--cmdline', line], check=True, stdout=subprocess.DEVNULL, creationflags=flags)
        payload = payload_path.read_bytes()
        phys, ram, boot_args, entry = self.runner.build_image(payload)
        ram_path, stub_path = self.out/'ram.bin', self.out/'stub.bin'
        ram_path.write_bytes(ram); stub_path.write_bytes(self.runner.stub(boot_args, entry))
        memory = struct.unpack_from('<Q', payload, 0x40)[0]
        ram_gib = max(4, math.ceil((phys + memory - 0x40000000) / 1024**3))
        self.qmp_port, self.input_port = free_port(), free_port()
        while self.qmp_port == self.input_port:
            self.input_port = free_port()
        qp = self.runner.qemu_path
        command = [qemu, '-accel', 'tcg', '-M', 'virt,gic-version=3', '-cpu', 'cortex-a76', '-smp', str(self.cpu_count), '-rtc', 'base=utc,clock=host',
                   '-m', f'{ram_gib}G', '-display', 'none', '-monitor', 'none', '-no-reboot', '-nic', 'none',
                   '-serial', f'file:{qp(self.out/"serial.txt")}',
                   '-qmp', f'tcp:127.0.0.1:{self.qmp_port},server=on,wait=off',
                   '-qtest', f'tcp:127.0.0.1:{self.input_port},server=on,wait=off',
                   '-qtest-log', 'NUL' if os.name == 'nt' else '/dev/null',
                   '-device', f'loader,file={qp(ram_path)},addr={phys:#x},force-raw=on',
                   '-device', f'loader,file={qp(stub_path)},addr={self.runner.STUB_PA:#x},force-raw=on',
                   '-device', f'loader,addr={self.runner.STUB_PA:#x},cpu-num=0',
                   '-global', 'virtio-mmio.force-legacy=false',
                   '-drive', f'file={qp(self.overlay)},format=qcow2,if=none,id=iosroot,cache=writeback',
                   '-device', 'virtio-blk-device,drive=iosroot']
        self.network_enabled = '_sweet_virtnet_init' in symbols
        if self.network_enabled:
            command += ['-netdev', 'user,id=pcnet', '-device',
                        'virtio-net-device,netdev=pcnet,mac=52:54:00:12:34:56']
        self.errors = (self.out/'qemu-errors.log').open('wb')
        self.process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                        stderr=self.errors, creationflags=flags)
        metadata = {'pid': self.process.pid, 'output': str(self.out), 'qmp_port': self.qmp_port,
                    'input_port': self.input_port, 'cpu_count': self.cpu_count,
                    'network': self.network_enabled, 'overlay': str(self.overlay), 'kernel': str(self.kernel)}
        (self.root/'data/gui/active.json').write_text(json.dumps(metadata, indent=2))
        for attempt in range(100):
            try:
                self.qmp = QMP(self.qmp_port); self.qtest = QTest(self.input_port)
                break
            except OSError:
                if self.process.poll() is not None:
                    raise RuntimeError((self.out/'qemu-errors.log').read_text(errors='replace'))
                time.sleep(.05)
        else:
            raise TimeoutError('Could not connect to QEMU control channels.')
        self.stage = 'booting'

    def poll(self):
        if self.process.poll() is not None:
            raise RuntimeError('QEMU process stopped. Check session logs for details.')
        self.header = struct.unpack('<8I', self.qtest.read(INPUT_ADDRESS, 32))
        self.input_ready = self.header[0] == INPUT_MAGIC and self.header[1] == 1
        path = self.out/'serial.txt'
        delta = ''
        if path.exists():
            with path.open('rb') as stream:
                stream.seek(self.serial_position); data = stream.read()
                self.serial_position += len(data)
            delta = data.decode(errors='replace')
            self.serial_tail = (self.serial_tail + delta)[-200000:]
        if 'panic(cpu ' in self.serial_tail or 'SWEET EARLY PANIC:' in self.serial_tail:
            self.stage = 'panic'
        elif any(marker in self.serial_tail for marker in ('SWEET FB: swap ', 'SWEET FB: backboardd sel 55', 'SWEET SURF: backboardd create id 2', 'SWEET SURF: backboardd create id')):
            self.stage = 'display'
        elif 'exec SpringBoard' in self.serial_tail:
            if self.stage != 'display':
                self.stage = 'springboard'
        elif 'Early boot complete. Continuing system boot.' in self.serial_tail:
            if self.stage not in ('display', 'springboard'):
                self.stage = 'services'
        if time.monotonic()-self.last_status >= 1:
            self.last_status = time.monotonic()
            status = {'pid': self.process.pid, 'stage': self.stage, 'input_ready': self.input_ready,
                      'header': self.header, 'updated_at': time.time(), 'output': str(self.out)}
            path = self.out/'live.json'
            temporary = path.with_suffix('.tmp'); temporary.write_text(json.dumps(status, indent=2)); temporary.replace(path)
        return delta

    def frame(self):
        # Binary QMP export is ~3x faster than base64 qtest on this Windows host.
        # The temporary file stays in the Windows cache when memory permits.
        path = self.out/'framebuffer.raw'
        if not path.exists():
            path.touch()
            if os.name == 'nt':
                import ctypes
                ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x100)
        size = FB_WIDTH * FB_HEIGHT * 4
        self.qmp.call('pmemsave', val=FB_ADDRESS, size=size, filename=path.as_posix())
        data = path.read_bytes()
        if len(data) != size:
            raise RuntimeError('QEMU framebuffer could not be read completely.')
        return data

    def input(self, kind, code, down, x=0, y=0):
        if not self.input_ready:
            return False
        if kind not in (1, 2) or not 0 <= code < (10 if kind == 1 else 4):
            raise ValueError('Invalid HID event')
        if not (0 <= x < FB_WIDTH and 0 <= y < FB_HEIGHT):
            raise ValueError('Touch lies outside the iOS screen')
        _, _, head, tail, *_ = struct.unpack('<8I', self.qtest.read(INPUT_ADDRESS, 32))
        if ((head - tail) & 0xffffffff) >= INPUT_SLOTS:
            return False
        record = struct.pack('<8I', (head + 1) & 0xffffffff, kind, code, int(bool(down)), x, y, 0, 0)
        self.qtest.write(INPUT_ADDRESS + 64 + (head & 63) * 32, record)
        self.qtest.write32(INPUT_ADDRESS + 8, (head + 1) & 0xffffffff)
        if down:
            self.held_inputs[(kind, code)] = (x, y)
        else:
            self.held_inputs.pop((kind, code), None)
        return True

    def pause(self, paused):
        if paused and self.input_ready:
            # Release before freezing the guest, and wait until HID acknowledges.
            deadline = time.monotonic() + 1
            while True:
                for (kind, code), (x, y) in list(self.held_inputs.items()):
                    self.input(kind, code, False, x, y)
                header = struct.unpack('<8I', self.qtest.read(INPUT_ADDRESS, 32))
                if not self.held_inputs and header[2] == header[3]:
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError('iOS did not release its input controls before pausing.')
                time.sleep(.01)
        self.qmp.call('stop' if paused else 'cont')

    def stop(self):
        if self.process is not None and self.process.poll() is None:
            try:
                if self.qmp:
                    self.qmp.call('quit')
                self.process.wait(timeout=5)
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
                self.process.kill(); self.process.wait()
        for channel in (self.qtest, self.qmp):
            if channel:
                try: channel.close()
                except OSError: pass
        if self.errors:
            self.errors.close()
        if self.lock_file:
            self.lock_file.close(); self.lock_file = None
        if hasattr(self, 'out'):
            for name in ('ram.bin', 'framebuffer.raw'):
                path = self.out/name
                if path.exists(): path.unlink()
            result = {'stage': self.stage, 'input_ready': self.input_ready, 'last_header': self.header,
                      'stopped_at': time.time(), 'exit_code': self.process.returncode if self.process else None}
            (self.out/'gui-result.json').write_text(json.dumps(result, indent=2))
