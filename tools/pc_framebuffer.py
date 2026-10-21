"""Read only the fixed framebuffer of the QEMU process started by this app."""
import ctypes
import re


def mapped_address(qmp, physical):
    text = qmp.call('human-monitor-command', **{'command-line': f'gpa2hva {physical:#x}'})
    match = re.fullmatch(
        rf'Host virtual address for {physical:#x} \([^\r\n]+\) is (?:0x)?([0-9a-fA-F]+)\s*', text)
    if not match:
        raise OSError('QEMU did not expose a framebuffer RAM mapping.')
    return int(match[1], 16)


class WindowsFramebuffer:
    def __init__(self, pid, qmp, physical, size):
        self.size = size
        self.address = mapped_address(qmp, physical)
        end = mapped_address(qmp, physical+size-1)
        if end != self.address+size-1:
            raise OSError('QEMU framebuffer RAM is not contiguous.')
        self.api = ctypes.WinDLL('kernel32', use_last_error=True)
        self.api.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        self.api.OpenProcess.restype = ctypes.c_void_p
        self.api.ReadProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        self.api.ReadProcessMemory.restype = ctypes.c_int
        self.api.CloseHandle.argtypes = [ctypes.c_void_p]
        self.api.CloseHandle.restype = ctypes.c_int
        self.buffer = ctypes.create_string_buffer(size)
        # PROCESS_VM_READ only, for our child QEMU; never write process RAM.
        self.handle = self.api.OpenProcess(0x0010, False, pid)
        if not self.handle:
            raise OSError('Windows framebuffer read access is unavailable.')

    def read(self):
        count = ctypes.c_size_t()
        if (not self.api.ReadProcessMemory(self.handle, self.address, self.buffer,
                self.size, ctypes.byref(count)) or count.value != self.size):
            raise OSError('Windows framebuffer read was incomplete.')
        return self.buffer.raw

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None
