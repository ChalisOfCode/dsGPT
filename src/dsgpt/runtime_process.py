"""Owned inference process lifetime, not an agent-code execution sandbox.

Windows: suspend, assign to a kill-on-close Job, then resume. Linux: a small
trusted exec helper sets a parent-death signal before replacing itself.
"""

import ctypes as C
import os
import subprocess
import sys
from pathlib import Path

DWORD, WORD, HANDLE, SIZE_T = C.c_uint32, C.c_uint16, C.c_void_p, C.c_size_t


class BasicLimits(C.Structure):
    _fields_ = [
        ("ProcessTime", C.c_int64),
        ("JobTime", C.c_int64),
        ("Flags", DWORD),
        ("MinimumWorkingSet", SIZE_T),
        ("MaximumWorkingSet", SIZE_T),
        ("ActiveProcesses", DWORD),
        ("Affinity", SIZE_T),
        ("Priority", DWORD),
        ("Scheduling", DWORD),
    ]


class ExtendedLimits(C.Structure):
    _fields_ = [
        ("Basic", BasicLimits),
        ("IOCounters", C.c_uint64 * 6),
        ("ProcessMemory", SIZE_T),
        ("JobMemory", SIZE_T),
        ("PeakProcessMemory", SIZE_T),
        ("PeakJobMemory", SIZE_T),
    ]


class StartupInfo(C.Structure):
    _fields_ = [
        ("cb", DWORD),
        ("reserved", C.c_wchar_p),
        ("desktop", C.c_wchar_p),
        ("title", C.c_wchar_p),
        ("x", DWORD),
        ("y", DWORD),
        ("xsize", DWORD),
        ("ysize", DWORD),
        ("xchars", DWORD),
        ("ychars", DWORD),
        ("fill", DWORD),
        ("flags", DWORD),
        ("show", WORD),
        ("reserved_size", WORD),
        ("reserved_bytes", C.c_void_p),
        ("stdin", HANDLE),
        ("stdout", HANDLE),
        ("stderr", HANDLE),
    ]


class ProcessInfo(C.Structure):
    _fields_ = [("process", HANDLE), ("thread", HANDLE), ("pid", DWORD), ("tid", DWORD)]


class WindowsChild:
    def __init__(self, args, cwd, env):
        api = C.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([C.c_void_p, C.c_wchar_p], HANDLE),
            "SetInformationJobObject": ([HANDLE, C.c_int, C.c_void_p, DWORD], C.c_int),
            "CreateProcessW": (
                [
                    C.c_wchar_p,
                    C.c_wchar_p,
                    C.c_void_p,
                    C.c_void_p,
                    C.c_int,
                    DWORD,
                    C.c_void_p,
                    C.c_wchar_p,
                    C.POINTER(StartupInfo),
                    C.POINTER(ProcessInfo),
                ],
                C.c_int,
            ),
            "AssignProcessToJobObject": ([HANDLE, HANDLE], C.c_int),
            "ResumeThread": ([HANDLE], DWORD),
            "TerminateProcess": ([HANDLE, C.c_uint], C.c_int),
            "TerminateJobObject": ([HANDLE, C.c_uint], C.c_int),
            "CloseHandle": ([HANDLE], C.c_int),
            "WaitForSingleObject": ([HANDLE, DWORD], DWORD),
            "GetExitCodeProcess": ([HANDLE, C.POINTER(DWORD)], C.c_int),
        }
        for name, (arguments, result) in signatures.items():
            getattr(api, name).argtypes = arguments
            getattr(api, name).restype = result
        self.api, self.job, self.process = api, None, None
        info = ProcessInfo()
        try:
            self.job = api.CreateJobObjectW(None, None)
            if not self.job:
                raise OSError("runtime_job_create_failed")
            limits = ExtendedLimits()
            limits.Basic.Flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not api.SetInformationJobObject(self.job, 9, C.byref(limits), C.sizeof(limits)):
                raise OSError("runtime_job_configure_failed")
            startup = StartupInfo()
            startup.cb = C.sizeof(startup)
            command = C.create_unicode_buffer(subprocess.list2cmdline(args))
            environment = C.create_unicode_buffer(
                "\0".join(f"{k}={v}" for k, v in sorted(env.items(), key=lambda x: x[0].upper()))
                + "\0\0"
            )
            # Explicit executable; no shell/search-path parsing, handle inheritance or console.
            flags = 0x4 | 0x400 | 0x08000000  # SUSPENDED | UNICODE_ENVIRONMENT | NO_WINDOW
            if not api.CreateProcessW(
                args[0],
                command,
                None,
                None,
                False,
                flags,
                environment,
                str(cwd),
                C.byref(startup),
                C.byref(info),
            ):
                raise OSError("runtime_process_create_failed")
            self.process, self.pid = info.process, info.pid
            if not api.AssignProcessToJobObject(self.job, self.process):
                raise OSError("runtime_job_assignment_failed")
            if api.ResumeThread(info.thread) == 0xFFFFFFFF:
                raise OSError("runtime_process_resume_failed")
        except BaseException:
            if info.process:
                api.TerminateProcess(info.process, 1)  # Includes failed Job assignment.
            self.close()
            raise
        finally:
            if info.thread:
                api.CloseHandle(info.thread)

    def poll(self):
        result = self.api.WaitForSingleObject(self.process, 0)
        if result == 258:  # WAIT_TIMEOUT
            return None
        if result != 0:
            raise OSError("runtime_process_wait_failed")
        code = DWORD()
        if not self.api.GetExitCodeProcess(self.process, C.byref(code)):
            raise OSError("runtime_process_wait_failed")
        return code.value

    def kill(self):
        if self.job and not self.api.TerminateJobObject(self.job, 1):
            raise OSError("runtime_process_stop_failed")

    def close(self):
        # Closing the last non-inherited Job handle also kills every descendant.
        if self.job:
            self.api.CloseHandle(self.job)
            self.job = None
        if self.process:
            self.api.CloseHandle(self.process)
            self.process = None


def launch(args, cwd, env):
    if os.name == "nt":
        return WindowsChild(args, cwd, env)
    if sys.platform != "linux":
        raise OSError("runtime_platform_unsupported")
    return subprocess.Popen(
        [
            sys.executable,
            "-I",
            str(Path(__file__).with_name("runtime_child.py")),
            str(os.getpid()),
            *args,
        ],
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        start_new_session=True,
    )


def environment(directory, token):
    # No inherited provider keys, proxy configuration, LLAMA overrides or loader injection.
    allowed = {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LOCALAPPDATA", "USERPROFILE"}
    env = {k: v for k, v in os.environ.items() if k.upper() in allowed}
    if os.name == "nt":
        env["PATH"] = str(directory) + os.pathsep + str(Path(env["SYSTEMROOT"]) / "System32")
    else:
        env["PATH"], env["LD_LIBRARY_PATH"] = "/usr/bin:/bin", str(directory)
    env["LLAMA_API_KEY"] = token
    return env
