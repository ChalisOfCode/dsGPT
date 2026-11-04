"""Bounded managed-backend restarts; Windows Task Scheduler supplies login only."""

import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

from .storage import InstanceLock
from .windows_security import logon_session_key, private_directory

STOP_FILE = "managed-supervisor.stop"
NO_RETRY_FILE = "managed-supervisor.no-retry"


def directory():
    root = private_directory(Path(os.environ["LOCALAPPDATA"]) / "dsGPT/managed")
    return private_directory(root / "data")


def _signal(data_dir, filename):
    temporary = data_dir / ("supervisor-stop-" + uuid4().hex)
    try:
        temporary.write_text(logon_session_key(), encoding="ascii")
        temporary.replace(data_dir / filename)
    finally:
        temporary.unlink(missing_ok=True)


def request_stop(data_dir):
    _signal(data_dir, STOP_FILE)


def disable_retries(data_dir):
    _signal(data_dir, NO_RETRY_FILE)


def prepare_start(data_dir):
    (data_dir / STOP_FILE).unlink(missing_ok=True)
    (data_dir / NO_RETRY_FILE).unlink(missing_ok=True)


def _requested(path, session):
    if path.is_symlink():
        return True
    try:
        with path.open("r", encoding="ascii") as stream:
            value = stream.read(1024)
        return len(value) >= 1024 or value == session
    except FileNotFoundError:
        return False
    except (OSError, UnicodeError):
        return True


def stop_requested(data_dir, session):
    return _requested(data_dir / STOP_FILE, session)


def retries_disabled(data_dir, session):
    return _requested(data_dir / NO_RETRY_FILE, session)


def supervise(
    data_dir,
    install_dir,
    *,
    delay=60,
    launch=None,
    sleep=time.sleep,
    clock=time.monotonic,
    session=None,
    stop_backend=None,
):
    session = session or logon_session_key()
    lock = InstanceLock(data_dir, "managed-supervisor.lock")
    lock.acquire()
    try:
        for attempt in range(4):
            if stop_requested(data_dir, session) or retries_disabled(data_dir, session):
                return 0
            if launch is None:
                child = subprocess.Popen(
                    [str(install_dir / "python/pythonw.exe"), "-I", "-m", "dsgpt.managed", "serve"],
                    cwd=install_dir,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            else:
                child = launch()
            while child.poll() is None:
                if stop_requested(data_dir, session):
                    if stop_backend is None:
                        from .managed import _stop_backend

                        stop_backend = _stop_backend
                    try:
                        stop_backend(data_dir)
                    except Exception:
                        pass  # Never terminate a foreign listener or kill a PID.
                sleep(0.2)
            if (
                child.returncode == 0
                or stop_requested(data_dir, session)
                or retries_disabled(data_dir, session)
            ):
                return 0
            if attempt == 3:
                return 1
            deadline = clock() + delay
            while clock() < deadline:
                if stop_requested(data_dir, session) or retries_disabled(data_dir, session):
                    return 0
                sleep(min(0.2, max(0, deadline - clock())))
        return 1
    finally:
        lock.release()


def main():
    return supervise(directory(), Path(sys.executable).resolve().parent.parent)


if __name__ == "__main__":
    raise SystemExit(main())
