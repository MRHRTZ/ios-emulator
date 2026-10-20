"""Create the iOS HFS+ disk using a temporary QEMU Linux helper on Windows."""
import base64
import ctypes
import hashlib
import io
import json
import os
from pathlib import Path
import re
import socket
import struct
import subprocess
import sys
import time
from urllib.request import urlopen

import firmware

IMAGE_NAME = 'jammy-server-cloudimg-amd64.img'
IMAGE_BASE = 'https://cloud-images.ubuntu.com/jammy/current/'
DISK_BYTES = 16 * 1024**3


def hfs_header(path):
    path = Path(path)
    with path.open('rb') as source:
        source.seek(1024)
        header = source.read(512)
    if len(header) != 512 or header[:2] not in (b'H+', b'HX'):
        raise ValueError('Output does not contain an HFS+/HFSX volume')
    attributes = struct.unpack_from('>I', header, 4)[0]
    block_size, blocks, free = struct.unpack_from('>3I', header, 40)
    if block_size < 512 or block_size & (block_size - 1) or free > blocks or block_size * blocks > path.stat().st_size:
        raise ValueError('HFS+ volume geometry is invalid')
    return {'signature': header[:2].decode(), 'volume_bytes': block_size * blocks,
            'used_bytes': block_size * (blocks - free), 'clean': bool(attributes & 0x100)}


def pid_running(pid):
    if os.name != 'nt':
        return Path(f'/proc/{pid}').exists()
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        status = ctypes.c_ulong()
        return bool(kernel.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(status))) and status.value == 259
    finally:
        kernel.CloseHandle(ctypes.c_void_p(handle))


def sparse_file(path, size):
    with Path(path).open('xb') as output:
        if os.name == 'nt':
            import msvcrt
            returned = ctypes.c_ulong()
            handle = ctypes.c_void_p(msvcrt.get_osfhandle(output.fileno()))
            if not ctypes.windll.kernel32.DeviceIoControl(handle, 0x900c4, None, 0, None, 0, ctypes.byref(returned), None):
                raise ctypes.WinError()
        output.truncate(size)


def helper_image(base):
    image = base / IMAGE_NAME
    metadata = base / 'source.json'
    if image.exists() and metadata.exists():
        source = json.loads(metadata.read_text())
        with image.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != source['sha256']:
            raise ValueError('Cached helper image checksum mismatch')
        return image
    checksums = urlopen(IMAGE_BASE + 'SHA256SUMS', timeout=30).read().decode()
    expected = next(line.split()[0] for line in checksums.splitlines() if line.split()[-1].lstrip('*') == IMAGE_NAME)
    partial = image.with_suffix('.part')
    with urlopen(IMAGE_BASE + IMAGE_NAME, timeout=45) as response, partial.open('wb') as output:
        total = int(response.headers['Content-Length'])
        done, last = 0, 0
        while block := response.read(firmware.CHUNK):
            output.write(block)
            done += len(block)
            if time.monotonic() - last >= 1:
                print(f'\rHelper download: {done * 100 / total:.1f}%    ', end='', flush=True)
                last = time.monotonic()
    firmware.verify(partial, expected)
    partial.replace(image)
    firmware.write_json(metadata, {'url': IMAGE_BASE + IMAGE_NAME, 'sha256': expected})
    print('\nHelper image SHA-256 verified')
    return image


def promote(root, log):
    base = root / 'data/root'
    staging, output = base / 'ios-root-build.img', base / 'ios-root.img'
    if not re.search(r'(?m)^ROOT_BUILD_OK\s*$', log.replace('\r', '')):
        raise ValueError('Helper did not report a completed filesystem check; inspect data/root-helper/serial.log')
    geometry = hfs_header(staging)
    if not geometry['clean'] or geometry['volume_bytes'] != DISK_BYTES:
        raise ValueError('Root filesystem is not clean or does not have the expected size')
    if output.exists():
        raise ValueError('Refusing to replace an existing prepared root image')
    staging.rename(output)
    result = dict(geometry, path=str(output), build='20H392', version='16.7.16',
                  prepared_at=time.time(), full_ios_boot_verified=False)
    firmware.write_json(base / 'ready.json', result)
    print(f'Root disk ready: {output} ({geometry["used_bytes"] / 1024**3:.2f} GiB used)')
    return output


def prepare(root, qemu_executable, timeout=3600):
    root = Path(root)
    base = root / 'data/root-helper'
    base.mkdir(parents=True, exist_ok=True)
    output = root / 'data/root/ios-root.img'
    if output.exists() and (output.parent / 'ready.json').exists():
        print(f'Root already prepared: {output}')
        return output
    state_file = base / 'process.json'
    # Attach to a helper already started by this local workflow; never start a second writer.
    if state_file.exists():
        state = json.loads(state_file.read_text())
        if pid_running(state['pid']):
            print(f'Root helper already active (PID {state["pid"]}); following its log.', flush=True)
            return follow(root, state['pid'], timeout)
        if (base / 'serial.log').exists():
            previous = (base / 'serial.log').read_text(errors='replace')
            if re.search(r'(?m)^ROOT_BUILD_OK\s*$', previous.replace('\r', '')):
                return promote(root, previous)
    try:
        import pycdlib
    except ImportError:
        raise ValueError('Install the local helper dependency: python -m pip install --target data/python-deps pycdlib==1.22.0')
    qemu = Path(qemu_executable).parent
    executable = qemu / ('qemu-system-x86_64.exe' if os.name == 'nt' else 'qemu-system-x86_64')
    image_tool = qemu / ('qemu-img.exe' if os.name == 'nt' else 'qemu-img')
    if not executable.is_file() or not image_tool.is_file():
        raise ValueError('The x86_64 system emulator and qemu-img are required for root preparation')
    image = helper_image(base)
    disk = base / 'builder.qcow2'
    if not disk.exists():
        subprocess.run([str(image_tool), 'create', '-f', 'qcow2', '-F', 'qcow2', '-b', str(image), str(disk)], check=True)
        subprocess.run([str(image_tool), 'resize', str(disk), '8G'], check=True)
    staging = output.parent / 'ios-root-build.img'
    staging.parent.mkdir(exist_ok=True)
    if not staging.exists():
        sparse_file(staging, DISK_BYTES)
    if staging.stat().st_size != DISK_BYTES:
        raise ValueError('Existing staging disk has an unexpected size; refusing to format it')
    sources = [('root', staging, 'ios-root-output', False),
               ('os', root / 'data/extracted/20H392/os-partition.apfs', 'ios-os-source', True),
               ('system', root / 'data/extracted/20H392/087-86593-047.dmg', 'ios-system-source', True),
               ('app', root / 'data/extracted/20H392/087-86715-047.dmg', 'ios-app-source', True)]
    if any(not path.is_file() for _, path, _, _ in sources):
        raise ValueError('Run extract and probe-root first; the helper requires all three source images')
    files = [('build-root.sh', root / 'tools/root-helper/build-root.sh'),
             ('sweet-root-tweaks.py', root / 'tools/sweet-root-tweaks.py')]
    config = {'write_files': [dict(path='/root/' + name, encoding='b64', permissions='0700',
                  content=base64.b64encode(path.read_bytes()).decode()) for name, path in files],
              'runcmd': [['bash', '/root/build-root.sh']],
              'power_state': {'mode': 'poweroff', 'timeout': 30, 'condition': True}}
    iso = pycdlib.PyCdlib()
    iso.new(interchange_level=3, joliet=3, rock_ridge='1.09', vol_ident='cidata')
    for name, data in [('user-data', ('#cloud-config\n' + json.dumps(config)).encode()),
                       ('meta-data', json.dumps({'instance-id': f'ios-root-{time.time_ns()}', 'local-hostname': 'ios-root-builder'}).encode())]:
        iso.add_fp(io.BytesIO(data), len(data), iso_path='/' + name.upper().replace('-', '_') + ';1',
                   rr_name=name, joliet_path='/' + name)
    iso.write(str(base / 'seed.iso'))
    iso.close()
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    acceleration = 'whpx' if os.name == 'nt' else 'tcg'
    command = [str(executable), '-accel', acceleration, '-cpu', 'qemu64', '-smp', '2', '-m', '2048',
               '-display', 'none', '-monitor', 'none', '-serial', f'file:{(base / "serial.log").as_posix()}',
               '-qmp', f'tcp:127.0.0.1:{port},server=on,wait=off',
               '-drive', f'file={disk.as_posix()},format=qcow2,if=none,id=boot',
               '-device', 'virtio-blk-pci,drive=boot,bootindex=1', '-boot', 'order=c,strict=on',
               '-drive', f'file={(base / "seed.iso").as_posix()},format=raw,media=cdrom,readonly=on',
               '-netdev', 'user,id=net0', '-device', 'virtio-net-pci,netdev=net0', '-no-reboot']
    for identifier, path, serial, readonly in sources:
        command += ['-drive', f'file={path.as_posix()},format=raw,if=none,id={identifier}' + (',readonly=on' if readonly else ''),
                    '-device', f'virtio-blk-pci,drive={identifier},serial={serial}']
    print('Starting root helper (2 GiB RAM). All firmware sources are read-only.', flush=True)
    with (base / 'qemu-errors.log').open('wb') as errors:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=errors, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        firmware.write_json(state_file, {'pid': process.pid, 'port': port, 'output': str(staging)})
        try:
            return follow(root, process.pid, timeout)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()


def follow(root, pid, timeout):
    base = root / 'data/root-helper'
    started = time.monotonic()
    stage = None
    while pid_running(pid):
        if time.monotonic() - started > timeout:
            raise TimeoutError('Root helper timed out; staging image is not marked ready')
        log = (base / 'serial.log').read_text(errors='replace') if (base / 'serial.log').exists() else ''
        stages = re.findall(r'ROOT_STAGE=([\w-]+)', log)
        current = stages[-1] if stages else 'booting-helper'
        if current != stage:
            stage = current
            print(f'Root preparation: {stage}', flush=True)
            firmware.write_json(base / 'progress.json', {'phase': stage, 'pid': pid, 'updated_at': time.time()})
        time.sleep(2)
    log = (base / 'serial.log').read_text(errors='replace')
    result = promote(root, log)
    firmware.write_json(base / 'progress.json', {'phase': 'ready', 'output': str(result), 'updated_at': time.time()})
    return result
