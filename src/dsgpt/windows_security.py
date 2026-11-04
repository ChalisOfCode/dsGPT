"""Per-user protected directories. Windows-only; no inherited-permission fallback."""

import ctypes
import os
from ctypes import wintypes
from pathlib import Path


def logon_session_key():
    """Identify this interactive logon, including its time to distinguish reboots."""
    if os.name != "nt":
        raise RuntimeError("Windows logon identity requires Windows")

    class Luid(ctypes.Structure):
        _fields_ = [("low", wintypes.DWORD), ("high", wintypes.LONG)]

    class UnicodeString(ctypes.Structure):
        _fields_ = [
            ("length", wintypes.USHORT),
            ("maximum", wintypes.USHORT),
            ("buffer", ctypes.c_void_p),
        ]

    class LogonData(ctypes.Structure):
        _fields_ = [
            ("size", wintypes.ULONG),
            ("id", Luid),
            ("user", UnicodeString),
            ("domain", UnicodeString),
            ("package", UnicodeString),
            ("type", wintypes.ULONG),
            ("session", wintypes.ULONG),
            ("sid", ctypes.c_void_p),
            ("time", ctypes.c_longlong),
        ]

    kernel = ctypes.WinDLL("kernel32.dll", use_last_error=True)
    api = ctypes.WinDLL("advapi32.dll", use_last_error=True)
    lsa = ctypes.WinDLL("secur32.dll", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    api.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    api.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    lsa.LsaGetLogonSessionData.argtypes = [
        ctypes.POINTER(Luid),
        ctypes.POINTER(ctypes.POINTER(LogonData)),
    ]
    lsa.LsaFreeReturnBuffer.argtypes = [ctypes.c_void_p]
    token = wintypes.HANDLE()
    if not api.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        raise RuntimeError("Windows logon identity unavailable")
    try:
        size = wintypes.DWORD()
        api.GetTokenInformation(token, 10, None, 0, ctypes.byref(size))
        if size.value < 16:
            raise RuntimeError("Windows logon identity unavailable")
        buffer = ctypes.create_string_buffer(size.value)
        if not api.GetTokenInformation(token, 10, buffer, size, ctypes.byref(size)):
            raise RuntimeError("Windows logon identity unavailable")
        authentication = Luid.from_buffer_copy(buffer.raw[8:16])
        record = ctypes.POINTER(LogonData)()
        if lsa.LsaGetLogonSessionData(ctypes.byref(authentication), ctypes.byref(record)) != 0:
            raise RuntimeError("Windows logon session unavailable")
        try:
            if not record or record.contents.time <= 0:
                raise RuntimeError("Windows logon session unavailable")
            return f"{authentication.high}:{authentication.low}:{record.contents.time}"
        finally:
            if record:
                lsa.LsaFreeReturnBuffer(record)
    finally:
        kernel.CloseHandle(token)


def private_directory(path):
    if os.name != "nt":
        raise RuntimeError("Managed installation requires Windows")
    path = Path(path).absolute()
    kernel = ctypes.WinDLL("kernel32.dll", use_last_error=True)
    api = ctypes.WinDLL("advapi32.dll", use_last_error=True)
    kernel.GetFileAttributesW.argtypes = [wintypes.LPCWSTR]
    kernel.GetFileAttributesW.restype = wintypes.DWORD
    # Reject junctions/symlinks before and after creation. Never recursively change
    # arbitrary existing application trees or accept a user-controlled data path.
    for ancestor in [*reversed(path.parents), path]:
        attrs = kernel.GetFileAttributesW(str(ancestor))
        if attrs != 0xFFFFFFFF and attrs & 0x400:
            raise RuntimeError("Managed storage cannot use reparse points")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    attrs = kernel.GetFileAttributesW(str(path))
    if attrs == 0xFFFFFFFF or attrs & 0x400:
        raise RuntimeError("Managed storage validation failed")
    token = wintypes.HANDLE()
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    api.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    api.OpenProcessToken.restype = wintypes.BOOL
    api.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    api.GetTokenInformation.restype = wintypes.BOOL
    api.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    api.ConvertSidToStringSidW.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not api.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        raise RuntimeError("Current Windows identity unavailable")
    sid_text = wintypes.LPWSTR()
    try:
        size = wintypes.DWORD()
        api.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        if not size.value:
            raise RuntimeError("Current Windows identity unavailable")
        buffer = ctypes.create_string_buffer(size.value)
        if not api.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)):
            raise RuntimeError("Current Windows identity unavailable")
        sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p)).contents
        if not api.ConvertSidToStringSidW(sid, ctypes.byref(sid_text)):
            raise RuntimeError("Current Windows identity unavailable")
        # Full control for current user and SYSTEM; protected inheritable DACL.
        sddl = f"D:P(A;OICI;FA;;;{sid_text.value})(A;OICI;FA;;;SY)"
    finally:
        if sid_text:
            kernel.LocalFree(sid_text)
        kernel.CloseHandle(token)
    descriptor, dacl = ctypes.c_void_p(), ctypes.c_void_p()
    api.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p,
    ]
    api.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
    api.GetSecurityDescriptorDacl.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.BOOL),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.BOOL),
    ]
    api.GetSecurityDescriptorDacl.restype = wintypes.BOOL
    api.SetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR,
        ctypes.c_int,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    api.SetNamedSecurityInfoW.restype = wintypes.DWORD
    if not api.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        sddl, 1, ctypes.byref(descriptor), None
    ):
        raise RuntimeError("Private directory descriptor failed")
    try:
        present, defaulted = wintypes.BOOL(), wintypes.BOOL()
        if not api.GetSecurityDescriptorDacl(
            descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)
        ):
            raise RuntimeError("Private directory descriptor failed")
        if not present.value or not dacl:
            raise RuntimeError("Private directory DACL missing")
        result = api.SetNamedSecurityInfoW(str(path), 1, 0x80000004, None, None, dacl, None)
        if result != 0:
            raise RuntimeError("Could not protect managed storage")
    finally:
        kernel.LocalFree(descriptor)
    return path
