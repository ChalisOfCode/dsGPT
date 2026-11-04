import asyncio
from types import SimpleNamespace

import psutil
import pytest

from dsgpt.config import Model
from dsgpt.downloads import DownloadError, DownloadManager
from dsgpt.models import ModelRegistry
from dsgpt.runtime import ManagedInference
from dsgpt.storage import Store


class Child:
    pid = 12345

    def __init__(self):
        self.killed = self.closed = False

    def poll(self):
        return 0 if self.killed else None

    def kill(self):
        self.killed = True

    def close(self):
        self.closed = True


def runtime(tmp_path):
    store = Store(tmp_path)
    return ManagedInference(store, DownloadManager(store), ModelRegistry(store, {}))


async def test_cancelling_turn_kills_owned_generation_and_releases_management_lock(tmp_path):
    r = runtime(tmp_path)
    r.socket_path = None
    child = r.child = Child()
    entered = asyncio.Event()

    class Inference:
        async def stream(self, *args):
            entered.set()
            await asyncio.Event().wait()
            yield {}

    model = Model("a", "A", "llama.cpp", "http://127.0.0.1:1234", "a")

    async def ensure(*args):
        return Inference(), model

    r.attached, r.ensure = lambda _: {"model_id": "a"}, ensure

    async def run():
        async for _ in r.stream(model, []):
            pass

    task = asyncio.create_task(run())
    await entered.wait()
    assert r.lock.locked()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert child.killed and child.closed and r.child is None and not r.lock.locked()


async def test_existing_runtime_is_called_only_after_owned_child_stops(tmp_path, monkeypatch):
    r = runtime(tmp_path)
    child = r.child = Child()
    external = Child()
    calls = []

    class ExternalInference:
        async def stream(self, model, messages, schema):
            assert child.killed and r.child is None
            calls.append(model.id)
            yield {"kind": "delta", "data": {"text": "external"}}

    r.external = ExternalInference()
    model = Model("external", "External", "ollama", "http://127.0.0.1:11434", "model")
    events = [event async for event in r.stream(model, [])]
    assert events[0]["data"]["text"] == "external"
    assert calls == ["external"] and external.poll() is None


def test_windows_tcp_ownership_check_is_exact_and_fails_closed(tmp_path, monkeypatch):
    r = runtime(tmp_path)
    r.socket_path, r.active_port, r.child = None, 1234, Child()

    def process(pid):
        assert pid == r.child.pid
        return SimpleNamespace(
            net_connections=lambda **kwargs: [
                SimpleNamespace(
                    status=psutil.CONN_LISTEN, laddr=SimpleNamespace(ip="127.0.0.1", port=1234)
                ),
            ]
        )

    monkeypatch.setattr("dsgpt.runtime.psutil.Process", process)
    assert r.owns_listener()
    r.active_port = 1235
    assert not r.owns_listener()

    def denied(pid):
        raise psutil.AccessDenied(pid)

    monkeypatch.setattr("dsgpt.runtime.psutil.Process", denied)
    assert not r.owns_listener()


def test_private_socket_path_will_not_replace_files_or_links(tmp_path):
    r = runtime(tmp_path)
    r.socket_path.write_bytes(b"must preserve")
    with pytest.raises(DownloadError):
        r.prepare_socket()
    assert r.socket_path.read_bytes() == b"must preserve"
    r.socket_path.unlink()
    outside = tmp_path / "outside"
    outside.write_bytes(b"keep")
    r.socket_path.symlink_to(outside)
    with pytest.raises(DownloadError):
        r.prepare_socket()
    assert outside.read_bytes() == b"keep"
