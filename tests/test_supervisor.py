from types import SimpleNamespace

import pytest

from dsgpt import supervisor
from dsgpt.storage import InstanceLock


def test_crash_retries_are_bounded_and_delayed(tmp_path):
    launches, now = [], [0.0]

    def launch():
        launches.append(now[0])
        return SimpleNamespace(poll=lambda: 1, returncode=1)

    def sleep(seconds):
        now[0] += seconds

    result = supervisor.supervise(
        tmp_path, tmp_path, launch=launch, session="login", clock=lambda: now[0], sleep=sleep
    )
    assert result == 1 and len(launches) == 4
    assert launches == pytest.approx([0, 60, 120, 180])


def test_clean_exit_never_restarts(tmp_path):
    launches = []

    def launch():
        launches.append(1)
        return SimpleNamespace(poll=lambda: 0, returncode=0)

    assert supervisor.supervise(tmp_path, tmp_path, launch=launch, session="login") == 0
    assert launches == [1]


def test_stop_during_retry_delay_prevents_another_launch(tmp_path, monkeypatch):
    monkeypatch.setattr(supervisor, "logon_session_key", lambda: "login")
    launches = []

    def launch():
        launches.append(1)
        return SimpleNamespace(poll=lambda: 1, returncode=1)

    assert (
        supervisor.supervise(
            tmp_path,
            tmp_path,
            launch=launch,
            session="login",
            sleep=lambda seconds: supervisor.request_stop(tmp_path),
        )
        == 0
    )
    assert launches == [1]


def test_old_login_stop_does_not_block_new_login_and_manual_start_clears(tmp_path, monkeypatch):
    monkeypatch.setattr(supervisor, "logon_session_key", lambda: "old-login")
    supervisor.request_stop(tmp_path)
    assert supervisor.stop_requested(tmp_path, "old-login")
    assert not supervisor.stop_requested(tmp_path, "new-login")
    supervisor.prepare_start(tmp_path)
    assert not supervisor.stop_requested(tmp_path, "old-login")


def test_one_supervisor_per_private_directory(tmp_path):
    lock = InstanceLock(tmp_path, "managed-supervisor.lock")
    lock.acquire()
    try:
        with pytest.raises(RuntimeError, match="owns"):
            supervisor.supervise(tmp_path, tmp_path, session="login")
    finally:
        lock.release()


def test_local_history_cli_refuses_a_live_supervisor(tmp_path, capsys):
    from dsgpt.history_import import main
    from dsgpt.storage import Store

    Store(tmp_path)
    lock = InstanceLock(tmp_path, "managed-supervisor.lock")
    lock.acquire()
    try:
        assert main(["list", "--data-dir", str(tmp_path)]) == 1
        assert "owns" in capsys.readouterr().err
    finally:
        lock.release()
    assert main(["list", "--data-dir", str(tmp_path)]) == 0


def test_disabling_retries_preserves_running_child_then_prevents_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(supervisor, "logon_session_key", lambda: "login")
    child = SimpleNamespace(returncode=None)
    child.poll = lambda: child.returncode
    launches = []

    def launch():
        launches.append(1)
        return child

    def sleep(seconds):
        supervisor.disable_retries(tmp_path)
        assert child.returncode is None
        child.returncode = 1

    assert (
        supervisor.supervise(
            tmp_path,
            tmp_path,
            launch=launch,
            session="login",
            sleep=sleep,
            stop_backend=lambda directory: pytest.fail("Running backend was stopped"),
        )
        == 0
    )
    assert launches == [1]


def test_stop_while_running_uses_graceful_backend_stop_and_never_kills(tmp_path, monkeypatch):
    monkeypatch.setattr(supervisor, "logon_session_key", lambda: "login")
    child = SimpleNamespace(returncode=None)
    child.poll = lambda: child.returncode
    stopped = []

    def launch():
        supervisor.request_stop(tmp_path)
        return child

    def stop_backend(directory):
        stopped.append(directory)
        child.returncode = 0

    assert (
        supervisor.supervise(
            tmp_path,
            tmp_path,
            launch=launch,
            session="login",
            stop_backend=stop_backend,
            sleep=lambda seconds: None,
        )
        == 0
    )
    assert stopped == [tmp_path]
