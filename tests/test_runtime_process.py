import ctypes
import os
from types import SimpleNamespace

import pytest

from dsgpt.runtime_process import (
    BasicLimits,
    ExtendedLimits,
    ProcessInfo,
    StartupInfo,
    WindowsChild,
    environment,
)


def test_child_environment_does_not_inherit_loader_proxy_or_agent_overrides(tmp_path, monkeypatch):
    for key in (
        "LLAMA_ARG_TOOLS",
        "LLAMA_ARG_HOST",
        "LLAMA_API_KEY",
        "LD_PRELOAD",
        "HTTPS_PROXY",
        "OPENAI_API_KEY",
        "HF_TOKEN",
        "PYTHONPATH",
    ):
        monkeypatch.setenv(key, "must-not-reach-child")
    env = environment(tmp_path, "private-runtime-token")
    assert "must-not-reach-child" not in env.values()
    assert env["LLAMA_API_KEY"] == "private-runtime-token"
    if os.name != "nt":
        assert env["LD_LIBRARY_PATH"] == str(tmp_path)


def test_windows_x64_structure_layout():
    assert ctypes.sizeof(ctypes.c_void_p) == 8
    assert ctypes.sizeof(BasicLimits) == 64
    assert ctypes.sizeof(ExtendedLimits) == 144
    assert ctypes.sizeof(StartupInfo) == 104
    assert ctypes.sizeof(ProcessInfo) == 24
    assert ExtendedLimits.IOCounters.offset == 64


@pytest.mark.parametrize("failure", [None, "job", "configure", "create", "assign", "resume"])
def test_windows_launch_assigns_job_before_resume_and_cleans_failure_handles(monkeypatch, failure):
    calls = []

    class Function:
        def __init__(self, name):
            self.name = name

        def __call__(self, *args):
            calls.append((self.name, args))
            if self.name == "CreateJobObjectW":
                return 0 if failure == "job" else 11
            if self.name == "SetInformationJobObject":
                assert args[1] == 9 and args[2]._obj.Basic.Flags == 0x2000
                return failure != "configure"
            if self.name == "CreateProcessW":
                assert args[0] == "C:\\private\\llama-server.exe"
                assert args[4] is False  # Job handle must never be inherited.
                assert args[5] & 0x4 and args[5] & 0x400 and args[5] & 0x08000000
                if failure == "create":
                    return False
                info = args[9]._obj
                info.process, info.thread, info.pid = 22, 33, 44
                return True
            if self.name == "AssignProcessToJobObject":
                assert args == (11, 22)
                return failure != "assign"
            if self.name == "ResumeThread":
                assert any(name == "AssignProcessToJobObject" for name, _ in calls)
                return 0xFFFFFFFF if failure == "resume" else 1
            if self.name == "WaitForSingleObject":
                return 258
            return True

    api = SimpleNamespace(
        **{
            name: Function(name)
            for name in [
                "CreateJobObjectW",
                "SetInformationJobObject",
                "CreateProcessW",
                "AssignProcessToJobObject",
                "ResumeThread",
                "TerminateProcess",
                "TerminateJobObject",
                "CloseHandle",
                "WaitForSingleObject",
                "GetExitCodeProcess",
            ]
        }
    )
    monkeypatch.setattr(ctypes, "WinDLL", lambda *a, **k: api, raising=False)
    args = ["C:\\private\\llama-server.exe", "--model", "C:\\private\\model.gguf"]
    if failure:
        with pytest.raises(OSError):
            WindowsChild(args, "C:\\private", {"LLAMA_API_KEY": "private"})
        names = [n for n, _ in calls]
        if failure in {"assign", "resume"}:
            assert "TerminateProcess" in names
            assert ("CloseHandle", (33,)) in calls
            assert ("CloseHandle", (22,)) in calls
        if failure != "job":
            assert ("CloseHandle", (11,)) in calls
        if failure == "assign":
            assert "ResumeThread" not in names
    else:
        child = WindowsChild(args, "C:\\private", {"LLAMA_API_KEY": "private"})
        assert child.pid == 44 and child.poll() is None
        child.kill()
        child.close()
        assert ("TerminateJobObject", (11, 1)) in calls
        assert ("CloseHandle", (11,)) in calls
