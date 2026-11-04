"""Explicit owner-managed loopback-only SearXNG service; no private files mounted."""

import asyncio
import json

import httpx
from fastapi import HTTPException

from .sandbox import DockerSandbox, SandboxError
from .storage import utcnow

IMAGE = (
    "ghcr.io/searxng/searxng@sha256:"
    "aa7270053bc3bf92155e2af83e2b0a7c3833c209cdeb8d396861a00c55ee7110"
)
ORIGIN = "http://127.0.0.1:8888"
PROGRAM = """import json,os,secrets
config={"use_default_settings":True,"server":{"secret_key":secrets.token_hex(32),"limiter":False,"image_proxy":False},"search":{"formats":["html","json"]}}
path="/tmp/dsgpt-settings.json"
with open(path,"w") as file:json.dump(config,file)
os.environ["SEARXNG_SETTINGS_PATH"]=path
os.execv("/usr/local/searxng/.venv/bin/granian",["granian","--interface","wsgi","--host","0.0.0.0","--port","8080","searx.webapp:app"])
"""


class SearchService:
    def __init__(self, store, configuration):
        self.store, self.configuration = store, configuration
        self.owner = store.one("SELECT owner_id FROM sandbox_identity WHERE id=1")["owner_id"]
        self.name = "dsgpt-search-" + self.owner[:12]
        self.worker = None

    def status(self):
        return {
            "origin": ORIGIN,
            "image": IMAGE,
            "job": self.store.one(
                "SELECT * FROM search_service_jobs ORDER BY created_at DESC LIMIT 1"
            ),
            "scope": "Loopback service; public search queries only. No chat/file mounts.",
        }

    def recover(self):
        with self.store.transaction() as db:
            db.execute(
                "UPDATE search_service_jobs SET status='interrupted',"
                "error_code='check_service_state' "
                "WHERE status='running'"
            )

    async def stop_worker(self):
        if self.worker:
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)
        self.recover()

    def request(self, identifier, action):
        previous = self.store.one("SELECT * FROM search_service_jobs WHERE id=?", (identifier,))
        if previous:
            if previous["action"] != action:
                raise HTTPException(409, "Request identifier already used")
            return previous
        if self.worker and not self.worker.done():
            raise HTTPException(409, "Service setup is active")
        if self.configuration.configured_origin:
            raise HTTPException(409, "Search is owned by the PC configuration file")
        try:
            transport = DockerSandbox(self.store.directory, "sha256:" + "0" * 64, self.owner)
        except (SandboxError, OSError) as exc:
            raise HTTPException(409, "Start Docker Desktop with Linux containers first") from exc
        now = utcnow()
        with self.store.transaction() as db:
            db.execute(
                "INSERT INTO search_service_jobs(id,action,status,created_at,updated_at) "
                "VALUES(?,?,?,?,?)",
                (identifier, action, "running", now, now),
            )
        self.worker = asyncio.create_task(
            self._run(identifier, action, transport, self.configuration.row()["revision"])
        )
        return self.store.one("SELECT * FROM search_service_jobs WHERE id=?", (identifier,))

    def validate(self, value):
        config = value.get("Config", {})
        host = value.get("HostConfig", {})
        labels = config.get("Labels", {})
        bindings = host.get("PortBindings", {})
        if (
            labels.get("org.dsgpt.owner") != self.owner
            or labels.get("org.dsgpt.purpose") != "local-search"
            or config.get("Image") != IMAGE
            or bindings != {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8888"}]}
            or host.get("Privileged")
            or host.get("Binds")
            or config.get("User") != "977:977"
            or not host.get("ReadonlyRootfs")
            or host.get("NetworkMode") != "bridge"
            or host.get("CapDrop") != ["ALL"]
            or "no-new-privileges" not in host.get("SecurityOpt", [])
            or host.get("Memory") != 1073741824
            or host.get("MemorySwap") != 1073741824
            or host.get("NanoCpus") != 1000000000
            or host.get("PidsLimit") != 128
            or config.get("Entrypoint") != ["/usr/local/searxng/.venv/bin/python"]
            or config.get("Cmd") != ["-c", PROGRAM]
            or any(m.get("Type") != "tmpfs" for m in value.get("Mounts", []))
        ):
            raise SandboxError("search_container_ownership_mismatch")

    async def _run(self, identifier, action, transport, revision):
        try:
            code, out, _, _ = await transport.cli(["container", "inspect", self.name])
            existing = json.loads(out)[0] if code == 0 else None
            if existing:
                self.validate(existing)
            if action == "stop":
                if self.configuration.row()["origin"] == ORIGIN:
                    self.configuration.update(None, revision)
                if existing:
                    await transport.checked(["container", "stop", self.name])
            else:
                if not existing:
                    await transport.checked(["pull", "--platform=linux/amd64", IMAGE], timeout=600)
                    image = json.loads(await transport.checked(["image", "inspect", IMAGE]))[0]
                    if image.get("Os") != "linux" or image.get("Architecture") != "amd64":
                        raise SandboxError("search_image_architecture_mismatch")
                    await transport.checked(
                        [
                            "container",
                            "create",
                            "--name",
                            self.name,
                            "--label",
                            "org.dsgpt.owner=" + self.owner,
                            "--label",
                            "org.dsgpt.purpose=local-search",
                            "--pull=never",
                            "--platform=linux/amd64",
                            "--publish",
                            "127.0.0.1:8888:8080",
                            "--network=bridge",
                            "--read-only",
                            "--cap-drop=ALL",
                            "--security-opt=no-new-privileges",
                            "--pids-limit=128",
                            "--cpus=1",
                            "--memory=1073741824",
                            "--memory-swap=1073741824",
                            "--user=977:977",
                            "--tmpfs=/tmp:rw,nosuid,nodev,size=134217728,uid=977,gid=977",
                            "--tmpfs=/etc/searxng:rw,nosuid,nodev,size=10485760,uid=977,gid=977",
                            "--tmpfs=/var/cache/searxng:rw,nosuid,nodev,size=134217728,uid=977,gid=977",
                            "--restart=unless-stopped",
                            "--log-driver=local",
                            "--log-opt=max-size=64k",
                            "--log-opt=max-file=1",
                            "--log-opt=compress=false",
                            "--entrypoint=/usr/local/searxng/.venv/bin/python",
                            IMAGE,
                            "-c",
                            PROGRAM,
                        ],
                        timeout=60,
                    )
                value = json.loads(await transport.checked(["container", "inspect", self.name]))[0]
                self.validate(value)
                await transport.checked(["container", "start", self.name])
                async with httpx.AsyncClient(trust_env=False, timeout=3) as client:
                    for _attempt in range(30):
                        try:
                            response = await client.get(ORIGIN + "/config")
                            if response.status_code == 200 and isinstance(response.json(), dict):
                                break
                        except (httpx.HTTPError, ValueError):
                            pass
                        await asyncio.sleep(1)
                    else:
                        raise SandboxError("search_service_not_ready")
                self.configuration.update(ORIGIN, revision)
            with self.store.transaction() as db:
                db.execute(
                    "UPDATE search_service_jobs SET status='completed',updated_at=? WHERE id=?",
                    (utcnow(), identifier),
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            code = str(exc) if isinstance(exc, SandboxError) else "search_service_setup_failed"
            with self.store.transaction() as db:
                db.execute(
                    "UPDATE search_service_jobs SET status='failed',error_code=?,updated_at=? "
                    "WHERE id=?",
                    (code, utcnow(), identifier),
                )
