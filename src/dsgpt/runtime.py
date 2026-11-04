"""One dsGPT-owned llama.cpp process, shared by scheduled Chat and Work turns."""

import asyncio
import errno
import os
import re
import secrets
import socket
import stat
import time
from dataclasses import asdict, replace

import httpx
import psutil
from fastapi import HTTPException

from .config import Model
from .downloads import DownloadError
from .inference import InferenceError, LocalInference
from .runtime_packages import RuntimePackages, safe_directory
from .runtime_process import environment, launch
from .storage import canonical, utcnow


class ManagedInference:
    def __init__(self, store, downloads, registry, port=0, packages=None):
        self.store, self.downloads, self.registry = store, downloads, registry
        self.packages = packages or RuntimePackages(store, downloads)
        self.port = port
        self.active_port = None
        self.lock = asyncio.Lock()
        self.child = self.model_id = self.local = None
        self.external = LocalInference()
        self.error_code = None
        self.socket_path = None
        if os.name != "nt":
            directory = store.directory / "runtime-sockets"
            directory.mkdir(mode=0o700, exist_ok=True)
            safe_directory(directory)
            if directory.stat().st_uid != os.getuid() or directory.stat().st_mode & 0o077:
                raise DownloadError("unsafe_storage")
            self.socket_path = directory / "llama.sock"

    def attached(self, identifier):
        return self.store.one("SELECT * FROM managed_models WHERE model_id=?", (identifier,))

    def status(self):
        alive = self.child is not None and self.child.poll() is None
        return {
            "model_id": self.model_id if alive else None,
            "process_id": self.child.pid if alive else None,
            "port": self.active_port if alive and not self.socket_path else None,
            "state": "loaded" if alive else "unloaded",
            "busy": self.lock.locked(),
            "error_code": self.error_code,
            "ownership": "dsGPT-managed-process-only",
            "transport": "private_unix_socket" if self.socket_path else "owned_loopback_tcp",
            "models": self.store.all("SELECT * FROM managed_models ORDER BY model_id"),
        }

    def require_idle(self):
        if self.lock.locked():
            raise HTTPException(409, "An inference turn or runtime operation is active")

    async def install(self, identifier):
        self.require_idle()
        async with self.lock:
            return await self.packages.install(identifier)

    async def remove(self, identifier):
        self.require_idle()
        async with self.lock:
            return await self.packages.remove(identifier)

    async def attach(
        self, identifier, name, asset_id, runtime_id, context=4096, output_tokens=1024, gpu_layers=0
    ):
        self.require_idle()
        if (
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", identifier)
            or not 0 <= gpu_layers <= 999
            or not 1 <= len(name) <= 200
        ):
            raise HTTPException(422, "Invalid managed model configuration")
        try:
            model = Model(
                identifier,
                name,
                "llama.cpp",
                f"http://127.0.0.1:{self.port or 18766}",
                identifier,
                context=context,
                output_tokens=output_tokens,
            )
        except ValueError as exc:
            raise HTTPException(422, "Invalid model context/output budget") from exc
        async with self.lock:
            spec = self.packages.spec(runtime_id)
            if gpu_layers and not spec.id.endswith("windows-cuda12"):
                raise HTTPException(422, "This runtime supports CPU inference only")
            self.downloads.busy_assets.add(asset_id)
            try:
                asset, path = self.packages.downloaded(asset_id, "model")
                await self.downloads.verify(path, asset)
                await self.packages.verify(runtime_id)
                with self.store.transaction() as db:
                    if identifier in self.registry.models:
                        raise HTTPException(409, "Model ID already configured")
                    db.execute(
                        "INSERT INTO model_records VALUES(?,?,?)",
                        (
                            identifier,
                            canonical(asdict(model)),
                            utcnow(),
                        ),
                    )
                    db.execute(
                        "INSERT INTO managed_models VALUES(?,?,?,?)",
                        (
                            identifier,
                            asset_id,
                            runtime_id,
                            gpu_layers,
                        ),
                    )
                self.registry.models[identifier] = model
            finally:
                self.downloads.busy_assets.discard(asset_id)
        return {
            "id": identifier,
            "label": model.label,
            "inference_ready": True,
            "verification": "runtime_and_model_sha256",
            "load_check": "on_first_use",
        }

    async def forget(self, identifier):
        self.require_idle()
        async with self.lock:
            # The registry refuses queued/running requests before altering the registration.
            result = self.registry.forget(identifier)
            if self.model_id == identifier:
                await self._stop()
            return result

    async def unload(self):
        self.require_idle()
        async with self.lock:
            await self._stop()
        return {"unloaded": True, "external_processes_modified": False}

    async def stop(self):
        async with self.lock:
            await self._stop()

    async def _stop(self):
        child = self.child
        if child:
            if child.poll() is None:
                child.kill()
            deadline = time.monotonic() + 10
            while child.poll() is None:
                if time.monotonic() >= deadline:
                    raise InferenceError("managed_runtime_stop_failed")
                await asyncio.sleep(0.025)
            if hasattr(child, "close"):
                child.close()
        self.child = self.model_id = self.local = None
        if child:
            self.store.log("model_unloaded")
        if child and self.socket_path and self.socket_path.exists():
            if not stat.S_ISSOCK(self.socket_path.lstat().st_mode):
                raise DownloadError("unsafe_storage")
            self.socket_path.unlink()

    def owns_listener(self):
        if not self.child or self.child.poll() is not None:
            return False
        if self.socket_path:
            safe_directory(self.socket_path.parent)
            return self.socket_path.exists() and stat.S_ISSOCK(self.socket_path.lstat().st_mode)
        try:
            return any(
                c.status == psutil.CONN_LISTEN
                and c.laddr.ip == "127.0.0.1"
                and c.laddr.port == self.active_port
                for c in psutil.Process(self.child.pid).net_connections(kind="tcp")
            )
        except (psutil.Error, OSError):
            return False  # Never send a secret/prompt to an unverified listener.

    async def ensure(self, model, attachment):
        if self.child and self.child.poll() is None and self.model_id == model.id:
            if not self.owns_listener():
                raise InferenceError("managed_runtime_unavailable")
            return self.local, self.connection_model(model)
        await self._stop()
        self.store.log("model_loading")
        executable = await self.packages.verify(attachment["runtime_id"])
        asset, weights = self.packages.downloaded(attachment["asset_id"], "model")
        await self.downloads.verify(weights, asset)
        if self.socket_path:
            self.prepare_socket()
            self.active_port = 18766  # HTTP base URL only; transport uses the private socket.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                if not self.socket_path:
                    if os.name == "nt":
                        probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                    probe.bind(("127.0.0.1", self.port))
                    self.active_port = probe.getsockname()[1]
            except OSError as exc:
                raise InferenceError("managed_runtime_port_in_use") from exc
        token = secrets.token_urlsafe(48)
        args = [
            str(executable),
            "--model",
            str(weights),
            "--alias",
            model.id,
            "--host",
            str(self.socket_path) if self.socket_path else "127.0.0.1",
            "--port",
            str(self.active_port),
            "--ctx-size",
            str(model.context),
            "--parallel",
            "1",
            "--gpu-layers",
            str(attachment["gpu_layers"]),
            "--fit",
            "off",
            "--offline",
            "--no-webui",
            "--no-agent",
            "--no-webui-mcp-proxy",
            "--no-slots",
            "--cache-ram",
            "0",
            "--log-disable",
            "--threads",
            str(min(8, os.cpu_count() or 1)),
            "--threads-http",
            "2",
            "--cors-origins",
            "http://127.0.0.1",
        ]
        if attachment["gpu_layers"] == 0:
            args += ["--device", "none"]
        self.child = launch(args, executable.parent, environment(executable.parent, token))
        self.model_id, self.local = (
            model.id,
            LocalInference(local_token=token, local_socket=self.socket_path),
        )
        connection = self.connection_model(model)
        deadline = time.monotonic() + 180
        async with httpx.AsyncClient(
            trust_env=False,
            follow_redirects=False,
            timeout=1,
            transport=httpx.AsyncHTTPTransport(uds=str(self.socket_path))
            if self.socket_path
            else None,
        ) as probe:
            while time.monotonic() < deadline:
                if self.child.poll() is not None:
                    raise InferenceError("managed_runtime_start_failed")
                try:
                    # Public health endpoint only, until socket ownership has been established.
                    health = await probe.get(connection.endpoint + "/health")
                    if health.status_code == 200 and self.owns_listener():
                        async with self.local.client(connection) as client:
                            await self.local.validate_local_model(client, connection)
                        self.error_code = None
                        self.store.log("model_loaded")
                        return self.local, connection
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.1)
        raise InferenceError("managed_runtime_start_timeout")

    def connection_model(self, model):
        return replace(model, endpoint=f"http://127.0.0.1:{self.active_port}")

    def prepare_socket(self):
        safe_directory(self.socket_path.parent)
        if len(os.fsencode(self.socket_path)) > 100:
            raise InferenceError("managed_runtime_socket_path_too_long")
        if not self.socket_path.exists() and not self.socket_path.is_symlink():
            return
        if not stat.S_ISSOCK(self.socket_path.lstat().st_mode):
            raise DownloadError("unsafe_storage")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(1)
            try:
                probe.connect(str(self.socket_path))
            except OSError as exc:
                if exc.errno != errno.ECONNREFUSED:
                    raise InferenceError("managed_runtime_port_in_use") from exc
            else:
                raise InferenceError("managed_runtime_port_in_use")
        self.socket_path.unlink()  # Private stale socket left by a terminated backend.

    async def stream(self, model, messages, response_schema=None):
        # Caller already holds the fair Chat/Work scheduler grant; this lock also
        # prevents owner install/unload/forget operations from interrupting that turn.
        async with self.lock:
            try:
                attachment = self.attached(model.id)
                if attachment:
                    await self.external.release_resident()
                    inference, model = await self.ensure(model, attachment)
                else:
                    # Release only our own allocation before handing off to existing runtimes.
                    await self._stop()
                    inference = self.external
                async for event in inference.stream(model, messages, response_schema):
                    yield event
            except (DownloadError, OSError, HTTPException) as exc:
                self.error_code = (
                    "managed_runtime_integrity_failed"
                    if isinstance(exc, DownloadError)
                    else "managed_runtime_unavailable"
                )
                await self._stop()
                raise InferenceError(self.error_code) from exc
            except BaseException as exc:
                if isinstance(exc, InferenceError):
                    self.error_code = exc.code
                # Disconnect/cancel must not leave a generation consuming resources.
                await self._stop()
                raise
