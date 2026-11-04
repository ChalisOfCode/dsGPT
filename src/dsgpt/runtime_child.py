"""Linux parent-death exec helper for a trusted, verified inference executable."""

import ctypes
import os
import signal
import sys


def main():
    parent = int(sys.argv[1])
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl.argtypes = [
        ctypes.c_int,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
    ]
    libc.prctl.restype = ctypes.c_int
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
        return 1
    if os.getppid() != parent:  # Parent may have died before prctl was installed.
        return 1
    os.execve(sys.argv[2], sys.argv[2:], os.environ)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
