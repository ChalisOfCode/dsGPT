"""Owner-initiated, recoverable installation of the reviewed local Docker toolchain."""

import asyncio
import hashlib
import io
import json
import tarfile
from pathlib import Path

from fastapi import HTTPException

from .sandbox import DockerSandbox, SandboxError, docker_binary
from .storage import utcnow
from .tool_image import DOCKERFILE

BASE_IMAGE = "python@sha256:2ed6491b93cd49272ee6de2b5a38440c3448360322c089fc23e370722d74179d"


def recipe_files():
    directory = Path(__file__).parent
    return {
        "Dockerfile": DOCKERFILE.encode(),
        **{
            name: (directory / name).read_bytes()
            for name in (
                "toolchain_install.py",
                "app_builder.py",
                "app_build_worker.py",
                "asset_install.py",
                "asset_worker.py",
                "transcript_merge.py",
                "ExportFunctions.java",
            )
        },
    }


def recipe_digest():
    return hashlib.sha256(
        b"".join(name.encode() + b"\0" + data for name, data in sorted(recipe_files().items()))
    ).hexdigest()


class ToolSetup:
    def __init__(self, store, builds):
        self.store, self.builds = store, builds
        self.worker = None
        self.checked_image = None
        self.owner = store.one("SELECT owner_id FROM sandbox_identity WHERE id=1")["owner_id"]

    def recover(self):
        with self.store.transaction() as db:
            db.execute(
                "UPDATE tool_setup_jobs SET status='interrupted',error_code='setup_interrupted',"
                "updated_at=? WHERE status='running'",
                (utcnow(),),
            )

    async def stop(self):
        if self.worker:
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)
        self.recover()

    def status(self):
        try:
            docker_binary()
            available = True
        except (SandboxError, OSError):
            available = False
        return {
            "docker_installed": available,
            "sandbox": self.builds.status(),
            "job": self.store.one("SELECT * FROM tool_setup_jobs ORDER BY created_at DESC LIMIT 1"),
            "help": "Docker Desktop must be running with Linux containers. Setup downloads "
            "public tools, builds the reviewed image and verifies isolation. "
            "It does not send chats, documents or credentials to the build.",
        }

    async def ensure_current(self):
        """A Work app request authorizes setup of the bundled public build dependencies."""
        from .inference import InferenceError
        from .storage import uid

        if self.checked_image == self.builds.image and self.builds.ready:
            return
        if self.worker and not self.worker.done():
            await asyncio.shield(self.worker)
        if self.builds.sandbox and self.builds.image:
            try:
                image = json.loads(
                    await self.builds.sandbox.checked(["image", "inspect", self.builds.image])
                )[0]
                labels = image.get("Config", {}).get("Labels", {})
                if labels.get("org.dsgpt.recipe") == recipe_digest():
                    if not self.builds.ready:
                        await self.builds.probe()
                    self.checked_image = self.builds.image
                    return
            except (SandboxError, OSError, ValueError, KeyError):
                pass
        identifier = uid()
        try:
            self.start(identifier)
            await asyncio.shield(self.worker)
        except HTTPException as exc:
            code = (
                exc.detail.get("code", "tool_setup_failed")
                if isinstance(exc.detail, dict)
                else "tool_setup_failed"
            )
            raise InferenceError(code) from exc
        job = self.store.one("SELECT * FROM tool_setup_jobs WHERE id=?", (identifier,))
        if not job or job["status"] != "completed" or not self.builds.ready:
            raise InferenceError(job["error_code"] if job else "tool_setup_failed")
        self.checked_image = self.builds.image

    def start(self, identifier):
        previous = self.store.one("SELECT * FROM tool_setup_jobs WHERE id=?", (identifier,))
        if previous:
            return previous
        if self.worker and not self.worker.done() or self.builds.lock.locked():
            raise HTTPException(409, "An isolated operation or setup is active")
        try:
            transport = DockerSandbox(self.store.directory, "sha256:" + "0" * 64, self.owner)
        except (SandboxError, OSError) as exc:
            raise HTTPException(
                409,
                {
                    "code": "docker_required",
                    "help": "Start Docker Desktop with Linux containers, then retry Setup.",
                },
            ) from exc
        now = utcnow()
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO tool_setup_jobs(id,status,created_at,updated_at) VALUES(?,?,?,?)",
                (identifier, "running", now, now),
            )
        self.worker = asyncio.create_task(self._run(identifier, transport))
        return self.store.one("SELECT * FROM tool_setup_jobs WHERE id=?", (identifier,))

    async def _run(self, identifier, transport):
        try:
            async with self.builds.lock:
                self.builds.ready = False
                tag = "dsgpt-tools-" + self.owner[:12]
                code, out, _, _ = await transport.cli(["image", "inspect", tag])
                if code == 0:
                    existing = json.loads(out)[0]
                    if (
                        existing.get("Config", {}).get("Labels", {}).get("org.dsgpt.owner")
                        != self.owner
                    ):
                        raise SandboxError("unowned_tool_image")
                context = io.BytesIO()
                with tarfile.open(fileobj=context, mode="w") as archive:
                    for name, data in recipe_files().items():
                        entry = tarfile.TarInfo(name)
                        entry.size = len(data)
                        entry.mode = 0o600
                        archive.addfile(entry, io.BytesIO(data))
                code, out, err, omitted = await transport.cli(
                    [
                        "build",
                        "--pull",
                        "--build-arg",
                        "DSGPT_BASE_IMAGE=" + BASE_IMAGE,
                        "--label",
                        "org.dsgpt.owner=" + self.owner,
                        "--label",
                        "org.dsgpt.recipe=" + recipe_digest(),
                        "--tag",
                        tag,
                        "-",
                    ],
                    data=context.getvalue(),
                    timeout=3600,
                )
                log = (out + err).decode("utf-8", errors="replace")[:60000]
                with self.store.transaction() as db:
                    db.execute(
                        "UPDATE tool_setup_jobs SET log=?,updated_at=? WHERE id=?",
                        (log, utcnow(), identifier),
                    )
                if code != 0:
                    raise SandboxError("tool_image_build_failed")
                inspected = json.loads(await transport.checked(["image", "inspect", tag]))[0]
                image = inspected["Id"]
                if (
                    inspected.get("Config", {}).get("Labels", {}).get("org.dsgpt.owner")
                    != self.owner
                    or inspected.get("Config", {}).get("Labels", {}).get("org.dsgpt.recipe")
                    != recipe_digest()
                ):
                    raise SandboxError("tool_image_identity_mismatch")
                self.builds.image = image
                self.builds.sandbox = DockerSandbox(self.store.directory, image, self.owner)
                self.builds.ready = False
                with self.store.transaction() as db:
                    db.execute("UPDATE tool_settings SET image_id=? WHERE id=1", (image,))
            await self.builds.probe()
            with self.store.transaction() as db:
                db.execute(
                    "UPDATE tool_setup_jobs SET status='completed',image_id=?,updated_at=? "
                    "WHERE id=?",
                    (image, utcnow(), identifier),
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            code = str(exc) if isinstance(exc, SandboxError) else "tool_setup_failed"
            with self.store.transaction() as db:
                db.execute(
                    "UPDATE tool_setup_jobs SET status='failed',error_code=?,updated_at=? "
                    "WHERE id=?",
                    (code, utcnow(), identifier),
                )
