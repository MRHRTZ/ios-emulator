#!/usr/bin/env python3
"""Small Python CLI for the Windows XNU/iOS emulator development workflow."""
import argparse
import importlib.util
import json
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parent
TOOLS = ROOT / 'tools'
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(ROOT / 'data/python-deps'))
import firmware


def load_runner():
    spec = importlib.util.spec_from_file_location('qemu_runner', TOOLS / 'qemu-sweet.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    return runner


def run_tool(*args):
    subprocess.run([sys.executable, *map(str, args)], cwd=ROOT, check=True)


def find_clang():
    return shutil.which('clang') or next((str(path) for path in
        [Path(r'C:\Program Files\LLVM\bin\clang.exe')] if path.is_file()), None)


def doctor():
    runner = load_runner()
    good = runner.check_qemu_dependency(qemu_bin=runner.find_qemu())
    for label, value in [('Python', sys.version.split()[0]), ('Clang', find_clang()),
                         ('llvm-nm', shutil.which('llvm-nm')),
                         ('Kernel', str(ROOT / 'xnu/out/kernel.development.sweet')
                          if (ROOT / 'xnu/out/kernel.development.sweet').is_file() else None)]:
        print(f'{label}: {value or "MISSING"}')
        good = good and bool(value)
    print(f'Free space: {shutil.disk_usage(ROOT).free / 1024**3:.1f} GiB')
    return 0 if good else 1


def choose_ipsw(value=None):
    if value:
        path = Path(value).resolve()
        if not path.is_file():
            raise ValueError(f'IPSW not found: {path}')
        return path
    paths = sorted((ROOT / 'data/firmware').glob('*.ipsw'), key=lambda item: item.stat().st_mtime, reverse=True)
    if not paths:
        raise ValueError('No complete IPSW found. Run: python emulator.py download')
    return paths[0]


def manifest_info(ipsw):
    with zipfile.ZipFile(ipsw) as archive:
        manifest = plistlib.loads(archive.read('BuildManifest.plist'))
        identities = manifest.get('BuildIdentities', [])
        identity = next((item for item in identities
                         if item.get('Info', {}).get('DeviceClass') == 'd22ap'), None)
        if identity is None:
            raise ValueError('BuildManifest has no D22AP identity for the configured target')
        components = {}
        for role in ('OS', 'Cryptex1,SystemOS', 'Cryptex1,AppOS', 'DeviceTree'):
            entry = identity.get('Manifest', {}).get(role)
            if entry and entry.get('Info', {}).get('Path'):
                path = entry['Info']['Path']
                components[role] = {'path': path, 'size': archive.getinfo(path).file_size}
        return {'ipsw': str(ipsw), 'version': manifest.get('ProductVersion'),
                'build': manifest.get('ProductBuildVersion'),
                'devices': manifest.get('SupportedProductTypes'),
                'board': identity.get('Info', {}).get('DeviceClass'), 'components': components}


def extract(ipsw):
    info = manifest_info(ipsw)
    if 'iPhone10,3' not in (info['devices'] or []):
        raise ValueError('Firmware does not target the iPhone X used by this project')
    destination = ROOT / 'data/extracted' / info['build']
    destination.mkdir(parents=True, exist_ok=True)
    components = info['components']
    if len(components) != 4:
        raise ValueError('Expected OS, both cryptexes and DeviceTree in BuildManifest')
    remaining = sum(value['size'] for value in components.values()
                    if not (destination / Path(value['path']).name).exists())
    if shutil.disk_usage(destination).free < remaining + 64 * 1024**2:
        raise OSError('Not enough free disk space for extracted components')
    with zipfile.ZipFile(ipsw) as archive:
        (destination / 'BuildManifest.plist').write_bytes(archive.read('BuildManifest.plist'))
        for role, component in components.items():
            target = destination / Path(component['path']).name
            if target.exists():
                # Reading the ZIP member validates its CRC even when a local copy exists.
                import zlib
                crc = 0
                with target.open('rb') as existing:
                    while block := existing.read(firmware.CHUNK):
                        crc = zlib.crc32(block, crc)
                if target.stat().st_size == component['size'] and crc == archive.getinfo(component['path']).CRC:
                    print(f'{role}: already extracted and CRC verified', flush=True)
                    continue
                raise ValueError(f'Existing component differs from IPSW: {target}')
            partial = target.with_suffix(target.suffix + '.part')
            done = 0
            last = 0
            with archive.open(component['path']) as source, partial.open('wb') as output:
                while block := source.read(firmware.CHUNK):
                    output.write(block)
                    done += len(block)
                    now = time.monotonic()
                    if now - last >= 1:
                        print(f'\rExtract {role}: {done * 100 / component["size"]:6.2f}%    ', end='', flush=True)
                        last = now
            if done != component['size']:
                raise ValueError(f'Extracted component size mismatch: {role}')
            partial.replace(target)
            print(f'\rExtract {role}: 100.00% CRC OK -> {target.name}', flush=True)
    firmware.write_json(destination / 'manifest.json', info)
    print(f'Components ready: {destination}')
    print('APFS DMGs still require conversion to a bootable root image; they are not QEMU disks.')
    return 0


def prepare_device_tree(ipsw):
    import adt
    info = manifest_info(ipsw)
    component = info['components'].get('DeviceTree')
    if not component:
        raise ValueError('DeviceTree is missing from BuildManifest')
    with zipfile.ZipFile(ipsw) as archive:
        payload, properties = adt.im4p_payload(archive.read(component['path']))
    if properties['encrypted']:
        raise ValueError('Encrypted device tree cannot be used')
    tree, consumed = adt.parse(payload)
    if consumed != len(payload) or not any(child.name == 'product' for child in tree.children):
        raise ValueError('Decoded device tree is incomplete or lacks /product')
    output = ROOT / 'research/ipsw-x/d22ap.adt'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)
    print(f'Device tree verified: {output} ({len(payload)} bytes, /product present)')
    return 0


def guest_status(serial, is_test=False):
    apple = (not is_test and 'com.apple.xpc.launchd|' in serial
             and 'Early boot complete. Continuing system boot.' in serial)
    springboard = apple and bool(re.search(r'(?m)^exec SpringBoard\r?$', serial))
    display_active = any(m in serial for m in ('SWEET FB: swap ', 'SWEET FB: backboardd sel 55', 'SWEET SURF: backboardd create id'))
    return {
        'apple_userland_started': apple,
        'springboard_exec_observed': springboard,
        'display_pipeline_active': display_active,
        'root_mount_failed': 'cannot mount root' in serial and 'load_init_program:' not in serial,
        'kernel_panic_observed': bool(re.search(r'(?m)^panic\(cpu ', serial)),
    }


def run(args):
    kernel = Path(args.kernel).resolve() if args.kernel else ROOT / 'xnu/out/kernel.development.sweet'
    if not kernel.is_file():
        raise ValueError(f'Kernel missing: {kernel}')
    if args.secs is None:
        args.secs = 45 if args.test else 300
    if args.secs <= 0:
        raise ValueError('--secs must be positive')
    if args.cpus > 1 or args.network:
        symbols = subprocess.check_output(['llvm-nm', '--defined-only', str(kernel)], text=True)
        if args.cpus > 1 and '_sweet_pc_smp_enabled' not in symbols:
            raise ValueError('Multiple QEMU CPUs require kernel patch 0087 or newer')
        if args.network and '_sweet_virtnet_init' not in symbols:
            raise ValueError('Networking requires kernel patch 0088 or newer')
    block_disk = None
    ramdisk = None
    is_test = args.test
    if args.test:
        ramdisk = ROOT / 'data/test-root/test-root.img'
        ramdisk.parent.mkdir(parents=True, exist_ok=True)
        clang = find_clang()
        if not clang:
            raise ValueError('Clang required for the test root; install LLVM')
        subprocess.run([clang, '-target', 'arm64-apple-ios16.0', '-c', str(TOOLS / 'sweet-init.S'),
                        '-o', str(ramdisk.with_suffix('.o'))], check=True)
        run_tool(TOOLS / 'mkinit.py', ramdisk.with_suffix('.o'), ramdisk)
    elif args.root_image:
        ramdisk = Path(args.root_image).resolve()
        if not ramdisk.is_file() or ramdisk.stat().st_size > 1024**3:
            raise ValueError('Prepared RAM root must exist and be at most 1 GiB; use --disk-image for a full root')
    else:
        block_disk = Path(args.disk_image).resolve() if args.disk_image else ROOT / 'data/root/ios-root.img'
        if not block_disk.is_file():
            raise ValueError('Prepared iOS disk missing. Complete prepare-root first, or use run --test explicitly.')
        import root_builder
        geometry = root_builder.hfs_header(block_disk)
        if not geometry['clean']:
            raise ValueError('Root disk is not cleanly unmounted; run its filesystem check first')
        symbols = subprocess.check_output(['llvm-nm', '--defined-only', str(kernel)], text=True)
        if '_sweet_virtio_rootdev' not in symbols:
            raise ValueError('This kernel has no virtio block driver; use the kernel built with patch 0082')
    out = ROOT / 'data/runs' / (time.strftime('%Y%m%d-%H%M%S') + f'-{time.time_ns() % 1000000:06d}')
    out.mkdir(parents=True, exist_ok=False)
    print('Mode: XNU + minimal test PID 1 (NOT full iOS)' if is_test else 'Mode: XNU + supplied root image', flush=True)
    adt, payload = out / 'qemu.adt', out / 'payload.bin'
    adt_args = ['--qemu', '--cpus', str(args.cpus)] + (['--memory-mib', str(args.memory_mib)] if block_disk else [])
    run_tool(TOOLS / 'mkadt.py', adt, *adt_args)
    command_line = (f'debug=0xc serial=3 cpus={args.cpus} keepsyms=1 -enable_kprintf_spam -noprogress '
                    'sweettouch=0 sweetkeys=0 sweetusb=0 sweetlog=0 ')
    if args.cpus > 1:
        from pc_platform import multicore_boot_args
        command_line += multicore_boot_args(args.cpus) + ' '
    if block_disk:
        command_line += ('rd=vioroot0 viorw=1 rootrw=1 unentitled_ios_sim_launch=1 '
                         'ignition_level=1 launchd_unsecure_cache=1 wdt=-1 wdt_test=no_user_checkin')
        run_tool(TOOLS / 'mkpayload.py', kernel, adt, payload, '--cmdline', command_line)
    else:
        command_line += 'rd=md0'
        run_tool(TOOLS / 'mkpayload.py', kernel, adt, payload, '--ramdisk', ramdisk, '--cmdline', command_line)
    command = [sys.executable, str(TOOLS / 'qemu-sweet.py'), str(payload), str(out),
               '--secs', str(args.secs), '--cpus', str(args.cpus), '--kernel', str(kernel), '--fail-on-panic', '--live-serial']
    if block_disk:
        runner = load_runner()
        qemu_bin = runner.find_qemu(args.qemu)
        if not qemu_bin:
            raise ValueError('QEMU not found')
        image_tool = Path(qemu_bin).with_name('qemu-img.exe' if sys.platform == 'win32' else 'qemu-img')
        overlay = out / 'root-overlay.qcow2'
        subprocess.run([str(image_tool), 'create', '-f', 'qcow2', '-F', 'raw', '-b', str(block_disk), str(overlay)], check=True)
        command += ['--disk', str(overlay), '--disk-format', 'qcow2']
    if args.network:
        command += ['--network']
    if args.qemu:
        command += ['--qemu', args.qemu]
    process = subprocess.run(command, cwd=ROOT)
    screen = (out / 'fb.txt').read_text(encoding='utf-8') if (out / 'fb.txt').exists() else ''
    result = json.loads((out / 'result.json').read_text()) if (out / 'result.json').exists() else {'status': 'runner_error'}
    serial = (out / 'serial.txt').read_text(errors='replace') if (out / 'serial.txt').exists() else ''
    milestones = guest_status(serial, is_test)
    marker = 'SWEET userspace: init running as PID 1'
    reached = marker in screen or marker in serial
    boot_verified = (milestones.get('springboard_exec_observed', False)
                     and milestones.get('display_pipeline_active', False)
                     and not milestones.get('kernel_panic_observed', False))
    summary = {'mode': 'test' if is_test else ('virtio-ios-root' if block_disk else 'custom-ram-root'), 'qemu_result': result,
               'test_pid1_observed': reached, **milestones,
               'springboard_display_observed': boot_verified,
               'full_ios_boot_verified': False,
               'runner_exit_code': process.returncode, 'output': str(out)}
    firmware.write_json(out / 'summary.json', summary)
    firmware.write_json(ROOT / 'data/last-run.json', summary)
    print(json.dumps(summary, indent=2))
    if is_test:
        return 0 if reached and result['status'] == 'no_panic_observed' else 1
    if milestones['root_mount_failed'] or milestones['kernel_panic_observed']:
        return 1
    # Graphics cannot be decoded as console glyphs. Serial Apple boot evidence
    # can validate userspace startup without claiming a working home screen.
    if milestones['apple_userland_started'] and result['status'] in ('incomplete_decode', 'blank_screen'):
        return 0
    return process.returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('doctor', help='Check QEMU/Python/LLVM/kernel')
    gui = commands.add_parser('gui', help='Open the native Windows emulator GUI')
    gui.add_argument('--no-start', action='store_true', help='Open the window without starting iOS')
    prepare = commands.add_parser('prepare-root', help='Build the iOS HFS+ disk using a temporary QEMU helper')
    prepare.add_argument('--timeout', type=int, default=3600)
    prepare.add_argument('--check-only', action='store_true', help='Recheck completed staging disk without recopying files')
    download = commands.add_parser('download', help='Download latest iPhone X IPSW with progress/resume/checksum')
    download.add_argument('--version', default='latest', help='Latest for iPhone X, or an exact version')
    for name in ('inspect', 'extract', 'device-tree', 'probe-root'):
        command = commands.add_parser(name, help=f'{name.title()} BuildManifest firmware components')
        command.add_argument('--ipsw')
    boot = commands.add_parser('run', help='Boot prepared iOS root, or explicitly opt in to --test')
    mode = boot.add_mutually_exclusive_group()
    mode.add_argument('--root-image', help='Small prepared RAM root')
    mode.add_argument('--disk-image', help='Prepared HFS+ root block image (per-run overlay)')
    mode.add_argument('--test', action='store_true', help='Run the minimal test PID 1, not Apple iOS')
    boot.add_argument('--cpus', type=int, choices=tuple(range(1, 9)), default=1)
    boot.add_argument('--network', action='store_true', help='Enable outbound virtual Ethernet/NAT')
    boot.add_argument('--kernel')
    boot.add_argument('--qemu')
    boot.add_argument('--memory-mib', type=int, default=2048, help='Kernel RAM for disk boot (256..4096 MiB)')
    boot.add_argument('--secs', type=float, help='Run duration (default: 45 for --test, 300 for iOS)')
    commands.add_parser('status', help='Show saved download and last-run status')
    args = parser.parse_args()
    try:
        if args.command == 'gui':
            try:
                import emulator_gui
            except ImportError as error:
                raise ValueError('GUI dependency missing. Install: python -m pip install PySide6==6.11.1') from error
            return emulator_gui.main(auto_start=not args.no_start)
        if args.command == 'doctor':
            return doctor()
        if args.command == 'prepare-root':
            import root_builder
            qemu = load_runner().find_qemu()
            if not qemu:
                raise ValueError('QEMU not found')
            root_builder.prepare(ROOT, qemu, args.timeout, check_only=args.check_only)
            return 0
        if args.command == 'download':
            firmware.download(ROOT / 'data/firmware', args.version)
            return 0
        if args.command in ('inspect', 'extract', 'device-tree', 'probe-root'):
            ipsw = choose_ipsw(args.ipsw)
            if args.command == 'extract':
                return extract(ipsw)
            if args.command == 'device-tree':
                return prepare_device_tree(ipsw)
            if args.command == 'probe-root':
                import root_probe
                return root_probe.probe(ROOT, manifest_info(ipsw))
            print(json.dumps(manifest_info(ipsw), indent=2))
            return 0
        if args.command == 'run':
            return run(args)
        if args.command == 'status':
            for path in (ROOT / 'data/firmware/progress.json', ROOT / 'data/last-run.json'):
                print(path.name + ':')
                print(path.read_text(encoding='utf-8') if path.exists() else 'No saved status')
            return 0
    except KeyboardInterrupt:
        print('\nStopped. Partial firmware downloads can be resumed.', file=sys.stderr)
        return 130
    except (OSError, ValueError, KeyError, IndexError, zipfile.BadZipFile, subprocess.CalledProcessError) as error:
        print(f'Error: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
