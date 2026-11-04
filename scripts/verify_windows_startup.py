"""Exercise real task ownership and a reviewed crash/clean-exit fixture.

This does not claim interactive-logon or actual backend target acceptance.
The disposable CI user must not already have a dsGPT startup task.
"""

import hashlib
import json
import shutil
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from dsgpt.startup import startup  # noqa: E402
from dsgpt.storage import InstanceLock  # noqa: E402
from dsgpt.supervisor import directory, prepare_start, request_stop  # noqa: E402


def verify_lifecycle():
    """Run a reviewed exit-code fixture, never generated Work code or a model."""
    with tempfile.TemporaryDirectory(prefix="dsGPT lifecycle ") as temp:
        root = Path(temp)
        (root / "python").mkdir()
        repo = Path(__file__).resolve().parents[1]
        record = json.loads((repo / "requirements-windows.lock.json").read_text())["python"]
        archive = root / record["file"]
        with urllib.request.urlopen(record["url"], timeout=60) as response:
            payload = response.read(record["bytes"] + 1)
        assert len(payload) == record["bytes"]
        assert hashlib.sha256(payload).hexdigest() == record["sha256"]
        archive.write_bytes(payload)
        with zipfile.ZipFile(archive) as package:
            assert all(
                not Path(n).is_absolute() and ".." not in Path(n).parts for n in package.namelist()
            )
            package.extractall(root / "python")
        modules = root / "python/dsgpt"
        modules.mkdir()
        for name in [
            "__init__.py",
            "supervisor.py",
            "windows_security.py",
            "storage.py",
            "migrations.py",
        ]:
            shutil.copy2(repo / "src/dsgpt" / name, modules / name)
        # The production supervisor and private Python are real; only the backend
        # is a reviewed exit-code fixture, with no network, model or Work command.
        (modules / "managed.py").write_text(
            "from pathlib import Path\n"
            "from datetime import datetime, timezone\n"
            "mode = Path('mode.txt').read_text().strip()\n"
            "with Path('attempts.txt').open('a') as stream:\n"
            "    stream.write(datetime.now(timezone.utc).isoformat() + '\\n')\n"
            "raise SystemExit(1 if mode == 'crash' else 0)\n",
            encoding="utf-8",
        )
        data_dir = directory()
        prepare_start(data_dir)
        (root / "mode.txt").write_text("crash", encoding="utf-8")
        attempts = root / "attempts.txt"

        def count():
            return len(attempts.read_text().splitlines()) if attempts.exists() else 0

        def wait_count(expected, seconds):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                if count() >= expected:
                    assert count() == expected
                    return
                time.sleep(0.5)
            raise AssertionError(f"Expected {expected} scheduled attempts; observed {count()}")

        assert not startup(root)["installed"]
        try:
            startup(root, "enable", confirm=True)
            startup(root, "run")
            wait_count(1, 30)
            wait_count(4, 240)
            # Three retries after the initial failed launch, then no fifth attempt.
            time.sleep(75)
            assert count() == 4, "Crash retries exceeded the configured limit"
            (root / "mode.txt").write_text("clean", encoding="utf-8")
            startup(root, "run")
            wait_count(5, 30)
            time.sleep(75)
            assert count() == 5, "A clean process exit was incorrectly restarted"
            (root / "mode.txt").write_text("crash", encoding="utf-8")
            startup(root, "run")
            wait_count(6, 30)
            request_stop(data_dir)
            time.sleep(75)
            assert count() == 6, "Explicit stop during backoff was incorrectly restarted"
            stamps = attempts.read_text().splitlines()
        finally:
            request_stop(data_dir)
            deadline = time.monotonic() + 30
            while True:
                lock = InstanceLock(data_dir, "managed-supervisor.lock")
                try:
                    lock.acquire()
                    break
                except RuntimeError:
                    if time.monotonic() >= deadline:
                        raise AssertionError("Supervisor fixture did not stop") from None
                    time.sleep(0.2)
                finally:
                    lock.release()
            startup(root, "disable", confirm=True)
            prepare_start(data_dir)
        assert not startup(root)["installed"]
        return {
            "initial_launch_plus_three_crash_retries": True,
            "retry_limit_enforced": True,
            "clean_exit_not_restarted": True,
            "stop_during_backoff_prevents_restart": True,
            "production_supervisor_and_embedded_python": True,
            "fixture_attempt_timestamps": stamps,
            "task_removed": True,
            "actual_backend_or_logon_tested": False,
        }


def main():
    checks = {}
    with tempfile.TemporaryDirectory(prefix="dsGPT startup & quoted '") as temp:
        root = Path(temp)
        (root / "python").mkdir()
        (root / "python/pythonw.exe").write_bytes(b"not executable; never run")
        assert not startup(root)["installed"], "Preserve preexisting task; fixture cannot proceed"
        try:
            checks["registered_current_user_task"] = startup(root, "enable", confirm=True)[
                "enabled"
            ]
            checks["idempotent_enable"] = startup(root, "enable", confirm=True)["enabled"]
            other = root / "other"
            (other / "python").mkdir(parents=True)
            (other / "python/pythonw.exe").write_bytes(b"not executable")
            for operation in ("status", "enable", "disable", "run"):
                try:
                    startup(other, operation, confirm=True)
                except RuntimeError as exc:
                    assert "preserved" in str(exc)
                    checks["foreign_install_" + operation + "_refused"] = True
                else:
                    raise AssertionError("Foreign install task operation was accepted")
            checks["original_task_preserved"] = startup(root)["enabled"]
            checks["removed_only_owned_task"] = not startup(root, "disable", confirm=True)[
                "installed"
            ]
            checks["idempotent_disable"] = not startup(root, "disable", confirm=True)["installed"]
        finally:
            startup(root, "disable", confirm=True)
        checks["no_task_remains"] = not startup(root)["installed"]
    assert all(checks.values())
    lifecycle = verify_lifecycle()
    report = {
        "passed": True,
        "checks": checks,
        "actual_task_scheduler": True,
        "registration_fixture_executed": False,
        "reviewed_lifecycle_fixture_executed": True,
        "lifecycle": lifecycle,
        "actual_logon_tested": False,
    }
    out = Path("reports/stage4b-windows-startup.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
