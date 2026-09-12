"""Direct process-memory access -- a fundamentally different trust boundary
than everything else in this app, which only ever runs Lua *inside* the
game via the sandboxed ClaudeBridge (bridge_client.py). No Lua sandbox
protects a raw ReadProcessMemory/WriteProcessMemory call: a bug here can
corrupt arbitrary game memory, not just fail a Lua call. Kept small and
used only where the bridge genuinely can't reach (flipping a live TMap's
raw bytes) -- see game_api.reveal_catalog() for the one current caller,
and dev/TABLET_MOD_INTEGRATION.md for the full background.
"""
import ctypes
import subprocess

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_VM_OPERATION = 0x0008

_kernel32 = None


def _k32():
    global _kernel32
    if _kernel32 is None:
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        k.OpenProcess.restype = ctypes.c_void_p
        k.ReadProcessMemory.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                         ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        k.WriteProcessMemory.argtypes = k.ReadProcessMemory.argtypes
        k.CloseHandle.argtypes = [ctypes.c_void_p]
        _kernel32 = k
    return _kernel32


def find_pid_by_name(process_name):
    """Returns the running process id for an exe name (no .exe suffix), or
    None if it isn't running."""
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-Process -Name '{process_name}' -ErrorAction SilentlyContinue).Id"],
            text=True, timeout=10).strip()
        return int(out.splitlines()[0]) if out else None
    except (subprocess.SubprocessError, ValueError):
        return None


class ProcessHandle:
    """Context manager around an OpenProcess handle. Read-only by default
    (QUERY_INFORMATION + VM_READ); pass write=True for VM_WRITE + VM_OPERATION
    too. Always closes the handle, even if a caller's identity-check assertion
    aborts partway through -- see reveal_catalog()'s use of this."""

    def __init__(self, pid, write=False):
        access = PROCESS_QUERY_INFORMATION | PROCESS_VM_READ
        if write:
            access |= PROCESS_VM_WRITE | PROCESS_VM_OPERATION
        self._k = _k32()
        self.handle = self._k.OpenProcess(access, False, pid)
        if not self.handle:
            raise OSError(f"OpenProcess({pid}) failed (error {ctypes.get_last_error()})")

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self._k.CloseHandle(self.handle)
        return False

    def read_bytes(self, address, size):
        buf = ctypes.create_string_buffer(size)
        got = ctypes.c_size_t()
        ok = self._k.ReadProcessMemory(self.handle, address, buf, size, ctypes.byref(got))
        if not ok or got.value != size:
            raise OSError(f"ReadProcessMemory({address:#x}, {size}) failed")
        return buf.raw

    def write_bytes(self, address, data):
        buf = ctypes.create_string_buffer(data, len(data))
        done = ctypes.c_size_t()
        ok = self._k.WriteProcessMemory(self.handle, address, buf, len(data), ctypes.byref(done))
        if not ok or done.value != len(data):
            raise OSError(f"WriteProcessMemory({address:#x}, {len(data)} bytes) failed")


def demo():
    """No live game required: just proves OpenProcess/Read/Write wiring is
    correct by round-tripping bytes in THIS Python process's own memory."""
    import array
    import os
    buf = array.array("b", b"\x01\x02\x03\x04")
    addr = buf.buffer_info()[0]
    with ProcessHandle(os.getpid(), write=True) as h:
        assert h.read_bytes(addr, 4) == b"\x01\x02\x03\x04"
        h.write_bytes(addr, b"\xAA\xBB")
        assert h.read_bytes(addr, 4) == b"\xAA\xBB\x03\x04"
    print("mem_client self-check OK")


if __name__ == "__main__":
    demo()
