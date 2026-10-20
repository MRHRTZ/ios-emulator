"""Probe native Windows UDIF/APFS reading; this does not build an iOS root disk."""
import hashlib
from pathlib import Path
import shutil
import struct
import subprocess
import time

import firmware


def probe(root, info):
    root = Path(root)
    directory = root / 'data/extracted' / info['build']
    dmg = directory / Path(info['components']['OS']['path']).name
    if not dmg.is_file():
        raise ValueError('Extract firmware components first: python emulator.py extract')
    local = root / 'data/tools/7zip/7z.exe'
    sevenzip = str(local) if local.is_file() else shutil.which('7z')
    if not sevenzip:
        raise ValueError('7-Zip with APFS support is required for this optional probe')
    flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
    listing = subprocess.run([sevenzip, 'l', '-slt', '-tDmg', str(dmg)], capture_output=True, check=True,
                             creationflags=flags).stdout.decode('utf-8', errors='replace')
    entries = []
    for section in listing.replace('\r', '').split('\n\n'):
        fields = dict(line.split(' = ', 1) for line in section.splitlines() if ' = ' in line)
        if 'Apple_APFS' in (fields.get('Path', '') + fields.get('Comment', '')) and fields.get('Size', '').isdigit():
            entries.append(fields)
    if len(entries) != 1:
        raise ValueError('Expected one Apple_APFS partition inside the OS DMG')
    member, size = entries[0]['Path'], int(entries[0]['Size'])
    target = directory / 'os-partition.apfs'
    if not target.exists():
        if shutil.disk_usage(directory).free < size + 64 * 1024**2:
            raise OSError('Insufficient space for decoded APFS partition')
        partial = target.with_suffix('.apfs.part')
        done, last = 0, 0
        with (directory / 'udif-probe-errors.txt').open('wb') as errors:
            process = subprocess.Popen([sevenzip, 'x', '-so', '-tDmg', str(dmg), member],
                                       stdout=subprocess.PIPE, stderr=errors, creationflags=flags)
            try:
                with partial.open('wb') as output:
                    while block := process.stdout.read(firmware.CHUNK):
                        output.write(block)
                        done += len(block)
                        if time.monotonic() - last >= 1:
                            print(f'\rDecode UDIF: {done * 100 / size:.2f}%    ', end='', flush=True)
                            last = time.monotonic()
                if process.wait() != 0 or done != size:
                    raise ValueError('UDIF decode failed; inspect udif-probe-errors.txt')
                partial.replace(target)
                print('\rDecode UDIF: 100.00%')
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                process.stdout.close()
    if target.stat().st_size != size:
        raise ValueError('Existing APFS partition has an unexpected size')
    with target.open('rb') as source:
        if source.read(36)[32:36] != b'NXSB':
            raise ValueError('Decoded partition lacks APFS NXSB signature')
    samples = directory / 'samples'
    samples.mkdir(exist_ok=True)
    result = {'sevenzip': sevenzip, 'partition': str(target), 'samples': {},
              'root_image_ready': False, 'full_ios_boot_verified': False}
    for member, filetype in (('sbin/launchd', 2), ('usr/lib/dyld', 7)):
        process = subprocess.run([sevenzip, 'x', '-so', str(target), member], capture_output=True,
                                 creationflags=flags)
        data = process.stdout
        if process.returncode or len(data) < 32:
            raise ValueError(f'APFS extraction failed for {member}: use a recent 7-Zip build')
        magic, cpu, _, actual_type = struct.unpack_from('<4I', data)
        if (magic, cpu, actual_type) != (0xfeedfacf, 0x0100000c, filetype):
            raise ValueError(f'{member} is not the expected ARM64 Mach-O binary')
        (samples / Path(member).name).write_bytes(data)
        result['samples'][member] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        print(f'{member}: ARM64 Mach-O verified ({len(data)} bytes)')
    firmware.write_json(directory / 'root-probe.json', result)
    print('Native APFS read probe passed. HFS+ root creation and guest storage are still required.')
    return 0
