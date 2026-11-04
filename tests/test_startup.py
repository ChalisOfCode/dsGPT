import base64
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from dsgpt import startup as module


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    root = tmp_path / "dsGPT space & 'quoted' $value"
    (root / "python").mkdir(parents=True)
    (root / "python/pythonw.exe").write_bytes(b"fixture, never executed")
    monkeypatch.setattr(module, "powershell_path", lambda: Path("trusted/powershell.exe"))
    return root


def test_opt_in_confirmation_precedes_all_os_operations(monkeypatch):
    monkeypatch.setattr(module, "powershell_path", lambda: pytest.fail("OS touched"))
    for operation in ("enable", "disable"):
        with pytest.raises(RuntimeError, match="Confirm"):
            module.startup("unused", operation)
    with pytest.raises(ValueError):
        module.startup("unused", "arbitrary-command", confirm=True)


def test_fixed_command_transports_paths_as_data_and_no_password(runtime, monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        assert str(runtime) not in " ".join(argv)
        assert base64.b64decode(argv[-1]).decode("utf-16-le") == module.SCRIPT
        assert kwargs["env"]["DSGPT_STARTUP_INSTALL"] == str(runtime)
        assert kwargs["env"]["DSGPT_STARTUP_OPERATION"] == "enable"
        assert kwargs["timeout"] == 30 and not kwargs.get("shell")
        return SimpleNamespace(returncode=0, stdout=b'{"installed":true,"enabled":true}')

    monkeypatch.setattr(module.subprocess, "run", run)
    assert module.startup(runtime, "enable", confirm=True)["enabled"]
    assert len(calls) == 1


@pytest.mark.parametrize(
    "body,code,match",
    [
        ({"error": "task_conflict"}, 2, "preserved"),
        ({"error": "scheduler_operation_failed"}, 1, "permissions"),
        ({"installed": True, "enabled": True}, 1, "permissions"),
        ({"installed": 1, "enabled": True}, 0, "verified"),
        ([], 0, "verified"),
        ("x" * 65537, 0, "verified"),
    ],
)
def test_failure_is_not_silently_treated_as_disabled(runtime, monkeypatch, body, code, match):
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=code, stdout=json.dumps(body).encode()),
    )
    with pytest.raises(RuntimeError, match=match):
        module.startup(runtime)


def test_timeout_does_not_retry_a_potentially_committed_change(runtime, monkeypatch):
    attempts = []

    def run(*a, **k):
        attempts.append(1)
        raise subprocess.TimeoutExpired("fixed-script", 30)

    monkeypatch.setattr(module.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="check startup status before retrying"):
        module.startup(runtime, "enable", confirm=True)
    assert attempts == [1]


def test_missing_runtime_never_registers_a_task(runtime, monkeypatch):
    (runtime / "python/pythonw.exe").unlink()
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **k: pytest.fail("OS touched"))
    with pytest.raises(RuntimeError, match="runtime is missing"):
        module.startup(runtime, "enable", confirm=True)


@pytest.mark.parametrize("enabled", [True, False])
def test_managed_launch_uses_scheduler_only_when_opted_in(runtime, monkeypatch, enabled):
    from dsgpt import managed

    events = []

    class Vault:
        reads = 0

        def __init__(self, directory):
            pass

        def read(self):
            self.reads += 1
            return None if self.reads == 1 else {"token": "private-credential"}

    monkeypatch.setattr(managed, "WindowsVault", Vault)
    monkeypatch.setattr(managed, "verify_running", lambda token: managed.__version__)

    def scheduled(directory, operation):
        assert directory == runtime and operation == "run"
        events.append("scheduler")
        return {"enabled": enabled}

    def spawn(argv, **kwargs):
        assert argv == [str(runtime / "python/pythonw.exe"), "-I", "-m", "dsgpt.managed", "serve"]
        assert "private-credential" not in " ".join(argv)
        events.append("spawn")
        return SimpleNamespace(poll=lambda: None)

    monkeypatch.setattr(managed, "startup", scheduled)
    monkeypatch.setattr(managed.subprocess, "Popen", spawn)
    monkeypatch.setattr(managed.subprocess, "DETACHED_PROCESS", 8, raising=False)
    monkeypatch.setattr(managed.subprocess, "CREATE_NEW_PROCESS_GROUP", 512, raising=False)
    assert isinstance(managed.start(runtime, runtime), Vault)
    assert events == (["scheduler"] if enabled else ["scheduler", "spawn"])
