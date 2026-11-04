"""Durable, bounded and digest-pinned downloads into dsGPT-owned storage.

No arbitrary source URLs, automatic execution, inference service registration,
or changes to existing Ollama/Prometheus files. Proxy environment is ignored.
"""

import asyncio
import hashlib
import ipaddress
import json
import os
import re
import shutil
import socket
import stat
import time
from dataclasses import asdict

import httpx
from fastapi import HTTPException

from .catalog import CATALOG, DOWNLOAD_HOSTS, Asset
from .storage import canonical, uid, utcnow


class DownloadError(Exception):
    pass


def validate_source_url(url):
    if (
        url.scheme != "https"
        or url.host not in DOWNLOAD_HOSTS
        or url.port not in (None, 443)
        or url.userinfo
        or url.fragment
    ):
        raise DownloadError("source_not_allowed")


class PublicHTTPS(httpx.AsyncBaseTransport):
    """Resolve each connection once, then connect to that exact public address.

    TLS verifies the original hostname, not the address. No DNS check/connect gap,
    proxy inheritance, or cross-host connection pool sharing. httpcore 1.0.9's
    sni_hostname extension is pinned by requirements-runtime.lock.
    """

    def __init__(self, validator=validate_source_url):
        self.validator = validator
        self.pool = httpx.AsyncHTTPTransport(
            retries=0, limits=httpx.Limits(max_connections=1, max_keepalive_connections=0)
        )

    async def handle_async_request(self, request):
        url = request.url
        self.validator(url)
        addresses = await asyncio.get_running_loop().getaddrinfo(
            url.host, 443, type=socket.SOCK_STREAM
        )
        ips = [ipaddress.ip_address(item[4][0]) for item in addresses]
        if not ips or any(not ip.is_global or ip.is_multicast for ip in ips):
            raise DownloadError("source_not_public")
        # IPv4 preferred where available; remaining public addresses are retry candidates
        # on the next durable user retry, not an unvalidated second DNS lookup.
        ip = next((ip for ip in ips if ip.version == 4), ips[0])
        pinned = httpx.Request(
            request.method,
            url.copy_with(host=str(ip)),
            headers={**dict(request.headers), "host": url.host},
            stream=request.stream,
            extensions={**request.extensions, "sni_hostname": url.host},
        )
        return await self.pool.handle_async_request(pinned)

    async def aclose(self):
        await self.pool.aclose()


def secure_file(path, flags):
    if path.is_symlink():
        raise DownloadError("unsafe_storage")
    fd = os.open(path, flags | getattr(os, "O_NOFOLLOW", 0), 0o600)
    info = os.fstat(fd)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or getattr(info, "st_file_attributes", 0) & 0x400
    ):
        os.close(fd)
        raise DownloadError("unsafe_storage")
    return os.fdopen(fd, "r+b" if flags & os.O_RDWR else "rb", buffering=0)


class DownloadManager:
    def __init__(self, store, catalog=None, transport_factory=None, reserve=1024**3):
        self.store = store
        self.catalog = CATALOG if catalog is None else catalog
        self.transport_factory = transport_factory or PublicHTTPS
        self.reserve = reserve
        self.directory = store.directory / "managed-models"
        if self.directory.is_symlink():
            raise DownloadError("unsafe_storage")
        self.directory.mkdir(mode=0o700, exist_ok=True)
        self.worker = self.active = None
        self.active_id = None
        self.wake = asyncio.Event()
        self.busy_assets = set()

    def paths(self, asset):
        if self.directory.is_symlink():
            raise DownloadError("unsafe_storage")
        return (
            self.directory / (asset.sha256 + ".part"),
            self.directory / (asset.sha256 + asset.suffix),
        )

    def row(self, identifier):
        row = self.store.one("SELECT * FROM downloads WHERE id=?", (identifier,))
        if not row:
            raise HTTPException(404, "Download not found")
        return row

    def get(self, identifier):
        row = self.row(identifier)
        asset = Asset(**json.loads(row.pop("definition")))
        return {
            **row,
            "total": asset.size,
            "sha256": asset.sha256,
            "name": asset.name,
            "kind": asset.kind,
            "inference_ready": bool(
                self.store.one("SELECT model_id FROM managed_models WHERE asset_id=?", (asset.id,))
            ),
        }

    def list(self):
        return [
            self.get(r["id"])
            for r in self.store.all("SELECT id FROM downloads ORDER BY created_at,id")
        ]

    def submit(self, asset_id):
        asset = self.catalog.get(asset_id)
        if not asset:
            raise HTTPException(404, "Asset not in the reviewed catalog")
        with self.store.transaction() as db:
            row = db.execute("SELECT id FROM downloads WHERE asset_id=?", (asset_id,)).fetchone()
            if row:
                return self.get(row["id"])
            identifier, now = uid(), utcnow()
            db.execute(
                "INSERT INTO downloads VALUES(?,?,?,?,?,?,?,?)",
                (identifier, asset.id, canonical(asdict(asset)), "queued", 0, None, now, now),
            )
        self.wake.set()
        return self.get(identifier)

    def update(self, identifier, status, downloaded, error=None):
        with self.store.transaction() as db:
            db.execute(
                "UPDATE downloads SET status=?,downloaded=?,error_code=?,updated_at=? WHERE id=?",
                (status, downloaded, error, utcnow(), identifier),
            )

    async def action(self, identifier, action):
        row = self.row(identifier)
        if action == "resume":
            if row["status"] not in {"paused", "cancelled", "failed"}:
                raise HTTPException(409, "Download is not resumable in its current state")
            self.update(identifier, "queued", row["downloaded"])
            self.wake.set()
        elif action in {"pause", "cancel"}:
            if row["status"] not in {"queued", "downloading", "verifying", "paused", "failed"}:
                raise HTTPException(409, "Download is not active")
            self.update(
                identifier, "paused" if action == "pause" else "cancelled", row["downloaded"]
            )
            if self.active_id == identifier and self.active:
                self.active.cancel()
                await asyncio.gather(self.active, return_exceptions=True)
        else:
            raise HTTPException(422, "Unknown download action")
        return self.get(identifier)

    def remove(self, identifier):
        row = self.row(identifier)
        if row["asset_id"] in self.busy_assets:
            raise HTTPException(409, "Asset is being verified or installed")
        if row["status"] not in {"paused", "cancelled", "failed", "downloaded"}:
            raise HTTPException(409, "Pause the download before removing its files")
        if self.active_id == identifier:
            raise HTTPException(409, "Download is settling; retry removal")
        if row["asset_id"].startswith("bge-small-en-v1-5-") and self.store.one(
            "SELECT id FROM semantic_settings WHERE enabled=1"
        ):
            raise HTTPException(409, "Disable semantic retrieval before removing its assets")
        if self.store.one(
            "SELECT model_id FROM managed_models WHERE asset_id=?", (row["asset_id"],)
        ) or self.store.one(
            "SELECT runtime_id FROM runtime_sources WHERE asset_id=?", (row["asset_id"],)
        ):
            raise HTTPException(409, "Detach models and remove runtime installations first")
        asset = Asset(**json.loads(row["definition"]))
        for path in self.paths(asset):
            if path.is_symlink():
                raise HTTPException(409, "Unsafe storage path; manual recovery required")
            if path.exists():
                with secure_file(path, os.O_RDONLY):
                    pass
                path.unlink()
        with self.store.transaction() as db:
            db.execute("DELETE FROM downloads WHERE id=?", (identifier,))
        return {"removed": True, "existing_runtime_files_modified": False}

    async def start(self):
        with self.store.transaction() as db:
            db.execute(
                "UPDATE downloads SET status='queued',error_code=NULL "
                "WHERE status IN ('downloading','verifying')"
            )
        self.worker = asyncio.create_task(self.loop())

    async def stop(self):
        if self.worker:
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)
            self.worker = None

    async def loop(self):
        while True:
            self.wake.clear()
            row = self.store.one(
                "SELECT * FROM downloads WHERE status='queued' ORDER BY created_at,id LIMIT 1"
            )
            if not row:
                await self.wake.wait()
                continue
            self.active_id = row["id"]
            self.active = asyncio.create_task(self.run(row))
            try:
                await asyncio.shield(self.active)
            except asyncio.CancelledError:
                if asyncio.current_task().cancelling():
                    self.active.cancel()
                    await asyncio.gather(self.active, return_exceptions=True)
                    latest = self.row(row["id"])
                    if latest["status"] in {"downloading", "verifying"}:
                        self.update(row["id"], "queued", latest["downloaded"])
                    raise
            finally:
                self.active = self.active_id = None

    async def run(self, row):
        count = row["downloaded"]
        try:
            asset = Asset(**json.loads(row["definition"]))
            # A removed/changed catalog entry must be explicitly reviewed on upgrade.
            if self.catalog.get(asset.id) != asset:
                raise DownloadError("catalog_changed")
            partial, final = self.paths(asset)
            if final.exists() or final.is_symlink():
                self.update(row["id"], "verifying", asset.size)
                await self.verify(final, asset)
                self.update(row["id"], "downloaded", asset.size)
                return
            with secure_file(partial, os.O_CREAT | os.O_RDWR) as file:
                count = file.seek(0, os.SEEK_END)
                if count > asset.size:
                    file.truncate(0)
                    count = 0
                self.update(row["id"], "downloading", count)
                if shutil.disk_usage(self.directory).free < asset.size - count + self.reserve:
                    raise DownloadError("insufficient_disk_space")
                if count < asset.size:
                    await self.receive(row["id"], asset, file, count)
                os.fsync(file.fileno())
            self.update(row["id"], "verifying", asset.size)
            await self.verify(partial, asset)
            # Manager serializes all writes. Never replace a pre-existing final artifact.
            if final.exists() or final.is_symlink():
                raise DownloadError("destination_exists")
            os.rename(partial, final)
            self.update(row["id"], "downloaded", asset.size)
        except asyncio.CancelledError:
            raise
        except (DownloadError, httpx.HTTPError, OSError, ValueError) as exc:
            code = str(exc) if isinstance(exc, DownloadError) else "download_io_failed"
            latest = self.row(row["id"])
            self.update(row["id"], "failed", latest["downloaded"], code)

    async def verify(self, path, asset):
        digest, count = hashlib.sha256(), 0
        with secure_file(path, os.O_RDONLY) as file:
            while block := file.read(1024**2):
                digest.update(block)
                count += len(block)
                await asyncio.sleep(0)
        if count != asset.size or digest.hexdigest() != asset.sha256:
            # Retain evidence until the owner explicitly removes the failed download.
            raise DownloadError("checksum_mismatch_remove_and_retry")

    async def receive(self, identifier, asset, file, count):
        async with httpx.AsyncClient(
            transport=self.transport_factory(),
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(30, connect=15),
            headers={"Accept-Encoding": "identity", "User-Agent": "dsGPT-model-download/0.3"},
        ) as client:
            url = asset.url
            headers = {"Range": f"bytes={count}-"} if count else {}
            for _ in range(6):
                request = client.build_request("GET", url, headers=headers)
                response = await client.send(request, stream=True)
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    await response.aclose()
                    if not location:
                        raise DownloadError("invalid_redirect")
                    url = str(httpx.URL(url).join(location))
                    # Every hop is checked independently by PublicHTTPS.
                    continue
                break
            else:
                raise DownloadError("too_many_redirects")
            try:
                if response.headers.get("content-encoding", "identity") != "identity":
                    raise DownloadError("encoded_download_rejected")
                if response.status_code == 200:
                    if count:
                        if (
                            shutil.disk_usage(self.directory).free + count
                            < asset.size + self.reserve
                        ):
                            raise DownloadError("insufficient_disk_space")
                        file.seek(0)
                        file.truncate(0)
                        count = 0  # Origin ignored Range: restart, never append a second copy.
                elif response.status_code == 206:
                    match = re.fullmatch(
                        r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("content-range", "")
                    )
                    if not match or tuple(map(int, match.groups())) != (
                        count,
                        asset.size - 1,
                        asset.size,
                    ):
                        raise DownloadError("invalid_content_range")
                else:
                    raise DownloadError("source_http_error")
                length = response.headers.get("content-length")
                if length is not None and int(length) != asset.size - count:
                    raise DownloadError("unexpected_content_length")
                last = 0.0
                async for block in response.aiter_raw(256 * 1024):
                    if count + len(block) > asset.size:
                        raise DownloadError("download_exceeds_expected_size")
                    file.write(block)
                    count += len(block)
                    if time.monotonic() - last >= 0.25 or count == asset.size:
                        self.update(identifier, "downloading", count)
                        last = time.monotonic()
                    await asyncio.sleep(0)
                self.update(identifier, "downloading", count)
                if count != asset.size:
                    raise DownloadError("download_incomplete")
            finally:
                await response.aclose()
