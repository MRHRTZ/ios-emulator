#!/usr/bin/env python3
"""Boot a SWEETXNU payload (tools/mkpayload.py) in QEMU's virt board.

  qemu-sweet.py PAYLOAD OUTDIR [--secs N] [--gdb] [--live-serial]

Does what shim/loader.c does on the phone, but on the host: places the
kernel segments, ADT and boot_args at their physical addresses and starts
the CPU at a 6-instruction stub that jumps to the entry with x0 = boot_args.
virt RAM starts at 0x40000000; with 4G it covers the phone's framebuffer
(0x9c000000) and the kernel's phys_base (0xb0000000) as plain memory.

After N seconds (or when the guest stops) it writes into OUTDIR:
  fb.png     the 1080x2400 framebuffer (what the phone screen would show)
  regs.txt   QEMU's view of CPU state
  qemu.log   exceptions with ESR/FAR/ELR (-d int,guest_errors)

With --kernel KERNEL (the matching unstripped Mach-O), also decode the
framebuffer using its iso_font into fb.txt and write result.json. This is a
snapshot of the circular screen, not a complete boot log. --fail-on-panic
returns 2 when a panic is visible; absence of a panic does not prove boot.
An undecodable or blank screen returns 3 with --fail-on-panic.
"""
import argparse, json, os, shutil, socket, struct, subprocess, sys, time, zlib
from pathlib import Path

FB_BASE, FB_W, FB_H = 0x9c000000, 1080, 2400
FB_STRIDE = FB_W * 4
PAGE = 0x4000
STUB_PA = 0x40200000	# above the dtb QEMU places at RAM base
BOOT_LINE_LENGTH = 608


def find_qemu(explicit=None):
    """Find an explicit executable, PATH entry, or Windows installer location."""
    selected = explicit or os.environ.get('QEMU_AARCH64')
    if selected:
        return shutil.which(selected) or (selected if os.path.isfile(selected) else None)
    found = shutil.which('qemu-system-aarch64')
    if found or os.name != 'nt':
        return found
    import winreg
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for prefix in (r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall',
                       r'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'):
            try:
                with winreg.OpenKey(hive, prefix) as parent:
                    for index in range(winreg.QueryInfoKey(parent)[0]):
                        try:
                            with winreg.OpenKey(parent, winreg.EnumKey(parent, index)) as key:
                                name = winreg.QueryValueEx(key, 'DisplayName')[0]
                                if not name.lower().startswith('qemu'):
                                    continue
                                try:
                                    location = winreg.QueryValueEx(key, 'InstallLocation')[0]
                                except OSError:
                                    location = ''
                                if not location:
                                    uninstall = winreg.QueryValueEx(key, 'UninstallString')[0]
                                    exe = uninstall.split('"')[1] if uninstall.startswith('"') else uninstall.split()[0]
                                    location = os.path.dirname(exe)
                                candidate = os.path.join(location, 'qemu-system-aarch64.exe')
                                if os.path.isfile(candidate):
                                    return candidate
                        except OSError:
                            continue
            except OSError:
                continue
    return None


def qemu_path(path):
    """QEMU option strings require forward slashes and doubled literal commas."""
    return Path(path).resolve().as_posix().replace(',', ',,')


def monitor_endpoint(out):
    if os.name == 'nt':
        # Pick an available loopback port immediately before launch.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
        return ('127.0.0.1', port), f'tcp:127.0.0.1:{port},server=on,wait=off'
    path = str(Path(out) / 'mon.sock')
    if os.path.exists(path):
        os.unlink(path)
    return path, f'unix:{qemu_path(path)},server=on,wait=off'


def check_qemu_dependency(cpu='cortex-a76', qemu_bin=None):
    """Verify qemu-system-aarch64 binary and CPU model support."""
    qemu_bin = qemu_bin or find_qemu()
    if not qemu_bin:
        print('[!] Error: qemu-system-aarch64 not found in PATH.', file=sys.stderr)
        print('    Use --qemu PATH or set QEMU_AARCH64 to the executable.', file=sys.stderr)
        print('    Windows installer: https://qemu.weilnetz.de/w64/', file=sys.stderr)
        print('    Install instructions:', file=sys.stderr)
        print('      Arch Linux:    sudo pacman -S qemu-system-aarch64', file=sys.stderr)
        print('      Ubuntu/Debian: sudo apt install qemu-system-arm', file=sys.stderr)
        print('      Fedora:         sudo dnf install qemu-system-aarch64', file=sys.stderr)
        print('      macOS:          brew install qemu', file=sys.stderr)
        return False
    try:
        ver = subprocess.check_output([qemu_bin, '--version'], text=True).splitlines()[0]
        print(f'[*] Found QEMU: {ver}', file=sys.stderr)
    except Exception as e:
        print(f'[!] Warning: Failed to query QEMU version: {e}', file=sys.stderr)
        return False

    try:
        cpu_list = subprocess.check_output([qemu_bin, '-M', 'virt', '-cpu', 'help'], text=True)
        if cpu in cpu_list:
            print(f'[*] CPU model {cpu} supported', file=sys.stderr)
        else:
            print(f'[!] Warning: CPU model {cpu} not explicitly listed in qemu-system-aarch64 -cpu help', file=sys.stderr)
    except Exception:
        pass
    return True


def check_kernel_tools(kernel_path):
    """Verify llvm-nm is available when --kernel is specified."""
    if not shutil.which('llvm-nm'):
        print('[!] Error: llvm-nm not found in PATH, required for --kernel font extraction.', file=sys.stderr)
        print('    Install instructions:', file=sys.stderr)
        print('      Arch Linux:    sudo pacman -S llvm', file=sys.stderr)
        print('      Ubuntu/Debian: sudo apt install llvm', file=sys.stderr)
        print('      Fedora:         sudo dnf install llvm', file=sys.stderr)
        print('      macOS:          brew install llvm', file=sys.stderr)
        return False
    if not os.path.isfile(kernel_path):
        print(f'[!] Error: kernel file does not exist: {kernel_path}', file=sys.stderr)
        return False
    return True


def build_image(payload):
    """Return (phys_base, ram_image, boot_args_pa, entry_pa)."""
    magic, ver, nsegs = struct.unpack_from('<8sII', payload, 0)
    assert magic == b'SWEETXNU' and ver == 1, 'not a SWEETXNU v1 payload'
    virt_base, entry_va, adt_off, adt_size, kernel_end, phys_base, mem_size = \
        struct.unpack_from('<7Q', payload, 0x10)
    cmdline = payload[0x48:0x48 + BOOT_LINE_LENGTH]
    delta = phys_base - virt_base
    adt_pa = kernel_end + delta
    ba_pa = (adt_pa + adt_size + PAGE - 1) & ~(PAGE - 1)
    top = ba_pa + PAGE
    img = bytearray(top - phys_base)
    for i in range(nsegs):
        vmaddr, vmsize, foff, fsize = struct.unpack_from('<4Q', payload, 0x2a8 + 32 * i)
        o = vmaddr + delta - phys_base
        img[o:o + fsize] = payload[foff:foff + fsize]
    img[adt_pa - phys_base:adt_pa - phys_base + adt_size] = payload[adt_off:adt_off + adt_size]
    ba = struct.pack('<HH4x4Q6QI4xQI', 2, 2, virt_base, phys_base, mem_size, top,
                     FB_BASE, 1, FB_STRIDE, FB_W, FB_H, 32, 0, adt_pa - delta, adt_size)
    ba += cmdline + b'\0' * 4 + struct.pack('<QQ', 0, mem_size)
    assert len(ba) == 736
    img[ba_pa - phys_base:ba_pa - phys_base + len(ba)] = ba
    return phys_base, bytes(img), ba_pa, entry_va + delta


def stub(ba_pa, entry_pa):
    # ldr x0, =ba ; ldr x1, =entry ; br x1 ; nop ; .quad ba ; .quad entry
    return struct.pack('<4I2Q', 0x58000080, 0x580000a1, 0xd61f0020, 0xd503201f, ba_pa, entry_pa)


def write_png(path, raw):
    rows = []
    for y in range(FB_H):
        line = raw[y * FB_STRIDE:(y + 1) * FB_STRIDE]
        rgb = bytearray(FB_W * 3)	# a8r8g8b8 little endian = B G R A in memory
        rgb[0::3], rgb[1::3], rgb[2::3] = line[2::4], line[1::4], line[0::4]
        rows.append(b'\0' + bytes(rgb))
    chunk = lambda t, d: struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d))
    png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', FB_W, FB_H, 8, 2, 0, 0, 0))
    png += chunk(b'IDAT', zlib.compress(b''.join(rows), 6)) + chunk(b'IEND', b'')
    open(path, 'wb').write(png)


def payload_data(payload, va, size):
    """Read initialized segment bytes by VA (the payload has no slide)."""
    nsegs = struct.unpack_from('<I', payload, 12)[0]
    for i in range(nsegs):
        vmaddr, _, foff, fsize = struct.unpack_from('<4Q', payload, 0x2a8 + 32 * i)
        if vmaddr <= va and va + size <= vmaddr + fsize:
            offset = foff + va - vmaddr
            return payload[offset:offset + size]
    raise ValueError(f'VA {va:#x}+{size:#x} not in initialized payload segments')


def decode_screen(raw, font):
    """Exact glyph matching for pe_serial.c's 2x, white-on-black fbcon."""
    glyphs = {font[c * 16:(c + 1) * 16]: chr(c) for c in range(32, 127)}
    rows, unknown = [], 0
    for row in range(FB_H // 32):
        chars = []
        for col in range(FB_W // 16):
            glyph = bytearray(16)
            for y in range(16):
                offset = (row * 32 + y * 2) * FB_STRIDE + col * 16 * 4
                for x in range(8):
                    if raw[offset + x * 8:offset + x * 8 + 4] == b'\xff' * 4:
                        glyph[y] |= 1 << x
            key = bytes(glyph)
            char = glyphs.get(key, '?')
            unknown += key not in glyphs
            chars.append(char)
        rows.append(''.join(chars).rstrip())
    return '\n'.join(rows).rstrip() + '\n', unknown


def screen_result(screen, unknown):
    if 'panic(cpu ' in screen or 'SWEET EARLY PANIC:' in screen:
        status = 'panic'
    elif unknown:
        status = 'incomplete_decode'
    elif screen.strip():
        status = 'no_panic_observed'
    else:
        status = 'blank_screen'
    return {'status': status, 'unknown_glyphs': unknown, 'snapshot_only': True}


def qmp(endpoint, *cmds, pmemsave=None):
    """Execute QMP on a Windows loopback TCP endpoint or a Unix socket."""
    deadline = time.monotonic() + 10
    while True:
        s = socket.socket(socket.AF_INET if isinstance(endpoint, tuple) else socket.AF_UNIX,
                          socket.SOCK_STREAM)
        s.settimeout(5)
        try:
            s.connect(endpoint)
            break
        except OSError:
            s.close()
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.05)
    with s, s.makefile('rw', encoding='utf-8', newline='\n') as f:
        greeting = f.readline()
        if not greeting or 'QMP' not in json.loads(greeting):
            raise RuntimeError('Missing QMP greeting')

        def call(execute, **args):
            f.write(json.dumps({'execute': execute, 'arguments': args}) + '\n')
            f.flush()
            while True:
                line = f.readline()
                if not line:
                    raise RuntimeError('QEMU closed the QMP connection')
                response = json.loads(line)
                if 'error' in response:
                    raise RuntimeError(f'QMP {execute}: {response["error"]}')
                if 'return' in response:
                    return response['return']

        call('qmp_capabilities')
        out = [call('human-monitor-command', **{'command-line': c}) for c in cmds]
        if pmemsave:
            # JSON paths are literal, unlike comma-separated command-line options.
            call('pmemsave', val=pmemsave[0], size=pmemsave[1],
                 filename=Path(pmemsave[2]).resolve().as_posix())
        return out



def stream_serial_file(serial_path, file_pos, out_stream=sys.stdout):
    """Read newly appended content from serial.txt and write directly to stream."""
    if not os.path.exists(serial_path):
        return file_pos
    try:
        with open(serial_path, 'r', errors='replace') as f:
            f.seek(file_pos)
            data = f.read()
            if data:
                out_stream.write(data)
                out_stream.flush()
                return f.tell()
    except Exception:
        pass
    return file_pos


def main():
    ap = argparse.ArgumentParser(
        description="Boot a SWEETXNU payload in QEMU's virt board.",
        epilog="Examples:\n"
               "  qemu-sweet.py payload.bin out/\n"
               "  qemu-sweet.py payload.bin out/ --live-serial\n"
               "  qemu-sweet.py payload.bin out/ --kernel kernel.macho --fail-on-panic\n"
               "  qemu-sweet.py --check-env\n",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument('payload', nargs='?', help='SWEETXNU payload binary (from mkpayload.py)')
    ap.add_argument('outdir', nargs='?', help='Output directory for fb.png, regs.txt, and logs')
    ap.add_argument('--secs', type=float, default=20, help='Duration to run QEMU in seconds (default: 20)')
    ap.add_argument('--gdb', action='store_true', help='start halted, gdb stub on :1234, no timeout')
    ap.add_argument('--hmp', action='append', default=[], help='extra monitor command run after stop (repeatable), e.g. "x /8gx 0xfffffe..."')
    ap.add_argument('--cpu', default='cortex-a76', help='QEMU CPU model (default: cortex-a76)')
    ap.add_argument('--kernel', help='matching unstripped kernel, for exact framebuffer text decoding (uses llvm-nm)')
    ap.add_argument('--fail-on-panic', action='store_true', help='exit 2 for a visible panic, 3 for incomplete/blank decoding; requires --kernel')
    ap.add_argument('--live-serial', action='store_true', help='stream serial console output to stdout in real time')
    ap.add_argument('--qemu', help='Path to qemu-system-aarch64 executable')
    ap.add_argument('--check-env', action='store_true', help='check QEMU installation and dependencies without running a payload')
    a = ap.parse_args()
    qemu_bin = find_qemu(a.qemu)
    if a.qemu and not qemu_bin:
        ap.error('--qemu executable does not exist')
    if a.secs <= 0:
        ap.error('--secs must be positive')

    if a.check_env:
        ok = check_qemu_dependency(a.cpu, qemu_bin)
        if shutil.which('llvm-nm'):
            print('[*] llvm-nm found in PATH', file=sys.stderr)
        else:
            print('[!] Optional: llvm-nm not found (needed only when using --kernel for text decoding)', file=sys.stderr)
        return 0 if ok else 1

    if not a.payload or not a.outdir:
        ap.error('payload and outdir are required unless --check-env is specified')

    if a.fail_on_panic and not a.kernel:
        ap.error('--fail-on-panic requires --kernel')

    if not check_qemu_dependency(a.cpu, qemu_bin):
        return 1

    if a.kernel and not check_kernel_tools(a.kernel):
        return 1

    payload = open(a.payload, 'rb').read()
    font = None
    if a.kernel:
        symbols = subprocess.check_output(['llvm-nm', '--defined-only', a.kernel], text=True)
        fonts = [int(line.split()[0], 16) for line in symbols.splitlines()
                 if line.split()[-1:] == ['_iso_font']]
        if len(fonts) != 1:
            ap.error('kernel must contain exactly one _iso_font symbol')
        font = payload_data(payload, fonts[0], 256 * 16)
    os.makedirs(a.outdir, exist_ok=True)
    out = Path(a.outdir).resolve().as_posix()

    phys_base, img, ba_pa, entry_pa = build_image(payload)
    open(f'{out}/ram.bin', 'wb').write(img)
    open(f'{out}/stub.bin', 'wb').write(stub(ba_pa, entry_pa))
    print(f'phys_base={phys_base:#x} boot_args={ba_pa:#x} entry={entry_pa:#x}', file=sys.stderr)

    mon, mon_option = monitor_endpoint(out)
    # virt RAM starts at 0x40000000: cover the payload's RAM (mkadt.py --highmem needs 8G).
    mem_size = struct.unpack_from('<Q', payload, 0x40)[0]
    ram_gib = max(4, -(-(phys_base + mem_size - 0x40000000) // (1 << 30)))
    cmd = [qemu_bin, '-accel', 'tcg', '-M', 'virt,gic-version=3', '-cpu', a.cpu, '-smp', '1', '-m', f'{ram_gib}G',
           '-nographic', '-serial', f'file:{qemu_path(out + "/serial.txt")}', '-qmp', mon_option,
           '-d', 'int,guest_errors,unimp', '-D', f'{out}/qemu.log', '-no-reboot',
           '-device', f'loader,file={qemu_path(out + "/ram.bin")},addr={phys_base:#x},force-raw=on',
           '-device', f'loader,file={qemu_path(out + "/stub.bin")},addr={STUB_PA:#x},force-raw=on',
           '-device', f'loader,addr={STUB_PA:#x},cpu-num=0']
    if a.gdb:
        cmd += ['-S', '-gdb', 'tcp:127.0.0.1:1234']

    p = None
    serial_file = f'{out}/serial.txt'
    serial_pos = 0

    try:
        p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if a.gdb:
            print('gdb stub on :1234; QMP socket:', mon, file=sys.stderr)
            p.wait()
            return 0

        t0 = time.time()
        while p.poll() is None and time.time() - t0 < a.secs:
            if a.live_serial:
                serial_pos = stream_serial_file(serial_file, serial_pos)
            time.sleep(0.2)

        if a.live_serial:
            stream_serial_file(serial_file, serial_pos)

        result = {'status': 'qemu_exited', 'qemu_returncode': p.returncode}
        if p.poll() is None:
            _, regs, *extra = qmp(mon, 'stop', 'info registers', *a.hmp, pmemsave=(FB_BASE, FB_STRIDE * FB_H, f'{out}/fb.raw'))
            open(f'{out}/regs.txt', 'w').write(regs + ''.join(f'\n(qemu) {c}\n{r}' for c, r in zip(a.hmp, extra)))
            p.kill()
            p.wait()
            raw = open(f'{out}/fb.raw', 'rb').read()
            write_png(f'{out}/fb.png', raw)
            result = {'status': 'not_decoded'}
            if font is not None:
                screen, unknown = decode_screen(raw, font)
                open(f'{out}/fb.txt', 'w').write(screen)
                result = screen_result(screen, unknown)
            os.unlink(f'{out}/fb.raw')
        else:
            print(f'qemu exited early: {p.returncode}', file=sys.stderr)

        open(f'{out}/result.json', 'w').write(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result), file=sys.stderr)
        print(f'{out}/fb.png  {out}/regs.txt  {out}/qemu.log', file=sys.stderr)
        if a.fail_on_panic and result['status'] == 'panic':
            return 2
        if a.fail_on_panic and result['status'] in ('incomplete_decode', 'blank_screen'):
            return 3
        if result['status'] == 'qemu_exited':
            return 1
        return 0

    except KeyboardInterrupt:
        print('\n[!] Interrupted by user, stopping QEMU...', file=sys.stderr)
        if p and p.poll() is None:
            p.kill()
            p.wait()
        return 130
    finally:
        if p and p.poll() is None:
            p.kill()
            p.wait()
        ram_file = f'{out}/ram.bin'
        if os.path.exists(ram_file):
            try:
                os.unlink(ram_file)
            except Exception:
                pass


if __name__ == '__main__':
    sys.exit(main())
