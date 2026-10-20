"""Real QEMU probe: ARM execution, loopback QMP, and memory export on Windows."""
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location('runner', Path(__file__).with_name('qemu-sweet.py'))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
qemu = runner.find_qemu()
assert qemu, 'QEMU installation was not discovered'
with tempfile.TemporaryDirectory(prefix='qemu probe, ') as directory:
    out = Path(directory)
    # mov x0, #42; b .  -- a tiny ARM64 program, not an XNU/iOS kernel.
    program = out / 'arm test.bin'
    program.write_bytes(struct.pack('<II', 0xd2800540, 0x14000000))
    endpoint, monitor = runner.monitor_endpoint(out)
    cmd = [qemu, '-M', 'virt,gic-version=3', '-cpu', 'cortex-a76', '-accel', 'tcg',
           '-m', '128M', '-display', 'none', '-serial', 'none', '-monitor', 'none',
           '-S', '-qmp', monitor, '-device',
           f'loader,file={runner.qemu_path(program)},addr=0x40200000,force-raw=on',
           '-device', 'loader,addr=0x40200000,cpu-num=0']
    process = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        runner.qmp(endpoint, 'cont')
        import time
        time.sleep(0.25)
        dump = out / 'memory test.raw'
        _, registers = runner.qmp(endpoint, 'stop', 'info registers',
                                  pmemsave=(0x40200000, 8, str(dump)))
        assert dump.read_bytes() == program.read_bytes(), 'Memory export differs'
        assert 'X00=000000000000002a' in registers, registers
        result = {'qemu': qemu, 'arm64_execution': 'PASS', 'loopback_qmp': 'PASS',
                  'memory_export': 'PASS', 'space_and_comma_paths': 'PASS',
                  'is_ios_boot': False}
        print(json.dumps(result, indent=2))
    finally:
        process.kill()
        stdout, stderr = process.communicate(timeout=10)
        if stderr:
            print(stderr.decode(errors='replace'))


