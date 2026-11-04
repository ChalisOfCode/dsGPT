import asyncio
import hashlib
import socket
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest

from dsgpt.catalog import Asset
from dsgpt.downloads import DownloadError, DownloadManager, PublicHTTPS
from dsgpt.storage import Store

DATA = b"GGUF" + bytes(range(256)) * 4096


def asset(data=DATA):
    return Asset(
        "fixture",
        "Fixture-NA",
        "https://huggingface.co/owner/model/resolve/" + "a" * 40 + "/fixture.gguf",
        hashlib.sha256(data).hexdigest(),
        len(data),
        "test",
        "https://huggingface.co/owner/model",
        "test fixture",
    )


class Stream(httpx.AsyncByteStream):
    def __init__(self, data, gate=None, fail=False):
        self.data, self.gate, self.fail = data, gate, fail

    async def __aiter__(self):
        yield self.data[:262144]
        if self.gate:
            await self.gate.wait()
        if self.fail:
            raise httpx.ReadError("secret remote URL must never be exposed")
        yield self.data[262144:]


async def settled(manager, identifier, statuses=("downloaded", "failed")):
    async with asyncio.timeout(5):
        while True:
            row = manager.get(identifier)
            if row["status"] in statuses:
                return row
            await asyncio.sleep(0.005)


def manager(tmp_path, handler, spec=None):
    spec = spec or asset()
    return DownloadManager(
        Store(tmp_path), {spec.id: spec}, lambda: httpx.MockTransport(handler), reserve=0
    )


async def test_download_digest_progress_idempotency_and_owned_file_removal(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, headers={"Content-Length": str(len(DATA))}, stream=Stream(DATA))

    m = manager(tmp_path, handler)
    first = m.submit("fixture")
    assert first == m.submit("fixture")
    await m.start()
    try:
        row = await settled(m, first["id"])
        assert row["status"] == "downloaded" and row["downloaded"] == len(DATA)
        assert not row["inference_ready"]
        assert m.paths(asset())[1].read_bytes() == DATA
        assert len(calls) == 1 and "authorization" not in calls[0].headers
    finally:
        await m.stop()
    assert m.remove(first["id"])["removed"]
    assert list(m.directory.iterdir()) == []


@pytest.mark.parametrize("supports_range", [True, False])
async def test_restart_resumes_actual_bytes_and_handles_ignored_range(tmp_path, supports_range):
    ranges = []
    start = 310000

    def handler(request):
        ranges.append(request.headers["range"])
        if supports_range:
            return httpx.Response(
                206,
                headers={"Content-Range": f"bytes {start}-{len(DATA) - 1}/{len(DATA)}"},
                stream=Stream(DATA[start:]),
            )
        return httpx.Response(200, stream=Stream(DATA))

    m = manager(tmp_path, handler)
    job = m.submit("fixture")
    m.paths(asset())[0].write_bytes(DATA[:start])
    m.update(job["id"], "downloading", 1)  # Simulate stale DB progress at crash.
    m = manager(tmp_path, handler)
    await m.start()
    try:
        assert (await settled(m, job["id"]))["status"] == "downloaded"
        assert ranges == [f"bytes={start}-"]
        assert m.paths(asset())[1].read_bytes() == DATA
    finally:
        await m.stop()


async def test_pause_cancel_and_resume_preserve_partial_and_do_not_stop_other_jobs(tmp_path):
    gate = asyncio.Event()
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, stream=Stream(DATA, gate))
        start = int(request.headers["range"][6:-1])
        return httpx.Response(
            206,
            headers={"Content-Range": f"bytes {start}-{len(DATA) - 1}/{len(DATA)}"},
            stream=Stream(DATA[start:]),
        )

    m = manager(tmp_path, handler)
    job = m.submit("fixture")
    await m.start()
    try:
        async with asyncio.timeout(5):
            while m.get(job["id"])["downloaded"] == 0:
                await asyncio.sleep(0.005)
        assert (await m.action(job["id"], "pause"))["status"] == "paused"
        assert m.paths(asset())[0].stat().st_size == 262144
        assert (await m.action(job["id"], "cancel"))["status"] == "cancelled"
        await m.action(job["id"], "resume")
        assert (await settled(m, job["id"]))["status"] == "downloaded"
    finally:
        await m.stop()


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("hash", "checksum_mismatch_remove_and_retry"),
        ("range", "invalid_content_range"),
        ("oversize", "download_exceeds_expected_size"),
        ("short", "download_incomplete"),
        ("compressed", "encoded_download_rejected"),
        ("network", "download_io_failed"),
        ("redirect", "too_many_redirects"),
    ],
)
async def test_bad_downloads_never_publish_final_files(tmp_path, kind, expected):
    def handler(request):
        if kind == "hash":
            return httpx.Response(200, stream=Stream(b"X" * len(DATA)))
        if kind == "range":
            return httpx.Response(
                206, headers={"Content-Range": "bytes 1-2/3"}, stream=Stream(DATA)
            )
        if kind == "oversize":
            return httpx.Response(200, stream=Stream(DATA + b"X"))
        if kind == "short":
            return httpx.Response(200, stream=Stream(DATA[:-3]))
        if kind == "compressed":
            return httpx.Response(200, headers={"Content-Encoding": "gzip"}, stream=Stream(b""))
        if kind == "network":
            return httpx.Response(200, stream=Stream(DATA, fail=True))
        return httpx.Response(302, headers={"Location": "/loop"}, stream=Stream(b""))

    m = manager(tmp_path, handler)
    job = m.submit("fixture")
    await m.start()
    try:
        row = await settled(m, job["id"])
        assert row["status"] == "failed" and row["error_code"] == expected
        assert not m.paths(asset())[1].exists()
        assert "secret" not in str(row)
    finally:
        await m.stop()


async def test_disk_check_catalog_drift_and_symlink_are_fail_closed(tmp_path, monkeypatch):
    def handler(request):
        raise AssertionError("Must not connect")

    m = manager(tmp_path, handler)
    job = m.submit("fixture")
    monkeypatch.setattr("dsgpt.downloads.shutil.disk_usage", lambda _: SimpleNamespace(free=0))
    await m.run(m.row(job["id"]))
    assert m.get(job["id"])["error_code"] == "insufficient_disk_space"
    m.catalog = {}
    await m.run(m.row(job["id"]))
    assert m.get(job["id"])["error_code"] == "catalog_changed"
    m.catalog = {"fixture": asset()}
    partial, _ = m.paths(asset())
    partial.unlink()
    other = tmp_path / "keep.gguf"
    other.write_bytes(b"existing model")
    partial.symlink_to(other)
    await m.run(m.row(job["id"]))
    assert m.get(job["id"])["error_code"] == "unsafe_storage"
    assert other.read_bytes() == b"existing model"


async def test_public_transport_pins_connection_address_and_keeps_tls_hostname(monkeypatch):
    loop = asyncio.get_running_loop()

    async def resolve(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]

    monkeypatch.setattr(loop, "getaddrinfo", resolve)
    t = PublicHTTPS()
    observed = []

    async def handle(request):
        observed.append(request)
        return httpx.Response(200, stream=Stream(b"ok"))

    monkeypatch.setattr(t.pool, "handle_async_request", handle)
    response = await t.handle_async_request(httpx.Request("GET", asset().url))
    assert observed[0].url.host == "8.8.8.8"
    assert observed[0].headers["host"] == "huggingface.co"
    assert observed[0].extensions["sni_hostname"] == "huggingface.co"
    await response.aclose()
    await t.aclose()


@pytest.mark.parametrize(
    "url",
    [
        "http://huggingface.co/x",
        "https://127.0.0.1/",
        "https://huggingface.co.evil.test/",
        "https://huggingface.co:8443/",
        "https://user:secret@huggingface.co/",
        "https://metadata.google.internal/",
    ],
)
async def test_redirect_targets_cannot_reach_private_or_unreviewed_services(url):
    t = PublicHTTPS()
    try:
        with pytest.raises(DownloadError, match="source_not_allowed"):
            await t.handle_async_request(httpx.Request("GET", url))
    finally:
        await t.aclose()


@pytest.mark.parametrize("address", ["127.0.0.1", "169.254.169.254", "10.0.0.1", "::1"])
async def test_private_dns_is_rejected(monkeypatch, address):
    async def resolve(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    t = PublicHTTPS()
    try:
        with pytest.raises(DownloadError, match="source_not_public"):
            await t.handle_async_request(httpx.Request("GET", asset().url))
    finally:
        await t.aclose()


def test_model_downloads_are_owner_only_and_reject_arbitrary_urls(backend):
    from conftest import pair

    phone, _ = pair(backend)
    headers = {"Authorization": "Bearer " + phone["token"]}
    assert backend.client.get("/v1/model-catalog", headers=headers).status_code == 403
    assert (
        backend.client.post(
            "/v1/downloads", json={"asset_id": "fixture"}, headers=headers
        ).status_code
        == 403
    )
    assert backend.client.post("/v1/downloads", json={"asset_id": "unknown"}).status_code == 404
    assert (
        backend.client.post(
            "/v1/downloads", json={"asset_id": "unknown", "url": "http://127.0.0.1"}
        ).status_code
        == 422
    )
    assert backend.client.get("/v1/downloads").json() == []


def test_asset_spec_cannot_target_cloud_inference_or_mutable_revisions():
    with pytest.raises(ValueError):
        replace(asset(), url=asset().url.replace("a" * 40, "main"))
    with pytest.raises(ValueError):
        replace(asset(), suffix=".exe")


async def test_completed_file_after_rename_crash_is_reverified_without_network(tmp_path):
    m = manager(tmp_path, lambda _: pytest.fail("Unexpected network request"))
    job = m.submit("fixture")
    m.paths(asset())[1].write_bytes(DATA)
    m.update(job["id"], "verifying", len(DATA))
    await m.start()
    try:
        assert (await settled(m, job["id"]))["status"] == "downloaded"
    finally:
        await m.stop()
