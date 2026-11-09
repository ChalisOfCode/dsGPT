import asyncio
import hashlib
import ipaddress
import json
import sqlite3
import time
from contextlib import asynccontextmanager
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .account_sessions import AccountGrantCreate, AccountSessionCreate, AccountSessions
from .attachments import EXTENSIONS, MAX_FILE_BYTES, MAX_FILES, MAX_MESSAGE_BYTES
from .builds import WorkBuilds
from .catalog import CATALOG
from .config import Settings
from .diagnostics import Diagnostics, MobileSnapshot
from .document_processing import DocumentProcessor
from .documents import MAX_DOCUMENT_BYTES, MAX_DOCUMENT_TOTAL
from .downloads import DownloadError, DownloadManager
from .history import History
from .memory import Memory
from .models import ModelRegistry
from .public_browser import PublicBrowser
from .research import Research, ResearchOptions
from .runs import TERMINAL, RunManager
from .runtime import ManagedInference
from .scheduler import InferenceScheduler
from .search_service import SearchService
from .search_settings import SearchConfiguration
from .security import Auth
from .semantic import SemanticIndex
from .storage import SCHEMA_VERSION, InstanceLock, Store, uid, utcnow
from .submissions import fingerprint
from .tool_setup import ToolSetup
from .web_retrieval import ResearchError
from .work import WorkRegistry
from .work_inputs import WorkInputs
from .work_uploads import WorkUploads


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class SearchUpdate(Body):
    origin: str | None = Field(max_length=2048)
    revision: int = Field(ge=0)


class SearchCheck(Body):
    revision: int = Field(ge=0)


class HistoryMemoryCreate(Body):
    request_id: UUID
    title: str = Field(min_length=1, max_length=200)
    task_id: UUID | None = None


class RetrievalSettings(Body):
    revision: int = Field(ge=0)
    enabled: bool
    history_enabled: bool = False
    attachments_enabled: bool | None = None


class RetrievalQuery(Body):
    query: str = Field(min_length=1, max_length=1000)
    kind: Literal["memory", "history", "attachment"] = "memory"
    task_id: UUID | None = None
    hidden: bool = False
    limit: int = Field(default=8, ge=1, le=20)


class PairingCreate(Body):
    scopes: list[Literal["chat", "work", "diagnostics", "models"]] = Field(
        min_length=1, max_length=4
    )


class PairingRedeem(Body):
    code: str = Field(min_length=32, max_length=100)
    name: str = Field(min_length=1, max_length=80)


class ConversationCreate(Body):
    title: str = Field(default="New chat", min_length=1, max_length=300)


class ConversationPatch(Body):
    revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=300)
    hidden: bool | None = None
    pinned: bool | None = None
    pin_order: float | None = None


class AttachmentInput(Body):
    name: str = Field(min_length=1, max_length=160)
    text: str = Field(max_length=65536)


class ChatAttachmentInput(Body):
    name: str = Field(min_length=1, max_length=160)
    text: str | None = Field(default=None, max_length=65536)
    original_base64: str | None = Field(default=None, max_length=699052)


class DictationChunk(Body):
    sequence: int = Field(ge=0, le=100000)
    audio: str = Field(default="", max_length=42668)
    final: bool = False


class GenerationControls(Body):
    reasoning_effort: str | None = Field(default=None, pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,39}$")
    web_mode: Literal["off", "auto", "on"] = "off"


class MessageCreate(GenerationControls):
    request_id: UUID
    content: str = Field(min_length=1, max_length=1_500_000)
    model_id: str = Field(min_length=1, max_length=200)
    research: ResearchOptions | None = None
    attachments: list[ChatAttachmentInput] = Field(default_factory=list, max_length=4)


class TaskCreate(GenerationControls):
    start: bool = False
    title: str = Field(min_length=1, max_length=300)
    requirements: str = Field(min_length=1, max_length=1_500_000)
    model_id: str | None = Field(default=None, min_length=1, max_length=200)
    request_id: UUID | None = None
    reference_urls: list[str] = Field(default_factory=list, max_length=6)
    build_target: Literal["auto", "source", "files", "apk", "exe", "apps"] = "source"
    upload_ids: list[UUID] = Field(default_factory=list, max_length=4)
    source_files: list[ChatAttachmentInput] = Field(default_factory=list, max_length=4)
    public_query: str | None = Field(default=None, min_length=1, max_length=500)
    follow_links: bool = False


class DeviceHeartbeat(Body):
    app_version: str = Field(min_length=1, max_length=40)


class UploadCreate(Body):
    name: str = Field(min_length=1, max_length=160)
    size: int = Field(ge=1, le=268435456)


class UploadChunk(Body):
    offset: int = Field(ge=0, le=268435456)
    data: str = Field(min_length=1, max_length=349528)


class TaskRevision(Body):
    resume: bool = False
    web_mode: Literal["on", "off"] | None = None
    reasoning_effort: str | None = Field(default=None, pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,39}$")
    revision: int = Field(ge=1)
    note: str | None = Field(default=None, min_length=1, max_length=1_500_000)
    model_id: str | None = Field(default=None, min_length=1, max_length=200)
    reference_urls: list[str] = Field(default_factory=list, max_length=6)
    retry_sources: bool = False


class SourceChange(Body):
    action: Literal["refresh", "remove"]
    revision: int = Field(ge=1)
    request_id: UUID


class MemoryCreate(Body):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=8000)
    task_id: UUID | None = None
    request_id: UUID | None = None


class MemoryPatch(Body):
    revision: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=8000)


class TaskAction(Body):
    action: Literal["start", "pause", "resume", "stop"]
    revision: int = Field(ge=1)


class ExportPreview(Body):
    mobile_device: UUID | None = None
    include_work_logs: bool = False


class ModelRegistration(Body):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,199}$")
    name: str = Field(min_length=1, max_length=200)
    runtime: Literal["ollama", "llama.cpp"]
    endpoint: str = Field(min_length=1, max_length=100)
    runtime_model: str = Field(min_length=1, max_length=200)
    abliterated: bool = False
    context: int = Field(default=8192, ge=512, le=131072)
    output_tokens: int = Field(default=1024, ge=1, le=131071)
    expected_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class DownloadCreate(Body):
    asset_id: str = Field(min_length=1, max_length=100)


class DownloadAction(Body):
    action: Literal["pause", "cancel", "resume"]


class ManagedModelCreate(Body):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
    name: str = Field(min_length=1, max_length=200)
    asset_id: str = Field(min_length=1, max_length=100)
    runtime_id: str = Field(min_length=1, max_length=100)
    context: int = Field(default=4096, ge=512, le=131072)
    output_tokens: int = Field(default=1024, ge=1, le=131071)
    gpu_layers: int = Field(default=0, ge=0, le=999)


class RequestBoundary:
    def __init__(self, app, settings):
        self.app, self.settings = app, settings

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        origin = headers.get(b"origin")
        if origin and origin.decode() not in self.settings.allowed_origins:
            return await JSONResponse({"detail": "Origin not authorized"}, 403)(
                scope, receive, send
            )
        if headers.get(b"content-encoding", b"identity") != b"identity":
            return await JSONResponse({"detail": "Compressed requests unsupported"}, 415)(
                scope, receive, send
            )
        data = bytearray()
        while True:
            event = await receive()
            if event["type"] == "http.disconnect":
                return
            data.extend(event.get("body", b""))
            if len(data) > self.settings.max_request_bytes:
                return await JSONResponse(
                    {"detail": "Request exceeds transport safety limit"}, 413
                )(scope, receive, send)
            if not event.get("more_body", False):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(data), "more_body": False}
            return await receive()

        async def secure_send(message):
            if message["type"] == "http.response.start":
                message["headers"] += [
                    (b"cache-control", b"no-store"),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                ]
            await send(message)

        await self.app(scope, replay, secure_send)


def create_app(settings: Settings, inference=None, managed=None):
    store = Store(settings.data_dir)
    store.diagnostic_event_retention = settings.diagnostic_event_retention
    store.diagnostic_snapshot_retention = settings.diagnostic_snapshot_retention
    store.diagnostic_snapshot_bytes = settings.diagnostic_snapshot_bytes
    auth, diagnostics = Auth(store), Diagnostics(store, settings)
    memory, scheduler = Memory(store), InferenceScheduler(store)
    registry = ModelRegistry(store, settings.models)
    downloads = DownloadManager(store)
    semantic = SemanticIndex(store, downloads)
    memory.semantic = semantic
    runtime = ManagedInference(store, downloads, registry)
    inference = inference or runtime
    research = Research(store, settings.models, inference, scheduler, settings.search_origin)
    search_configuration = SearchConfiguration(store, research.search, settings.search_origin)
    builds = WorkBuilds(
        store,
        settings.sandbox_image
        or store.one("SELECT image_id FROM tool_settings WHERE id=1")["image_id"],
    )
    tool_setup = ToolSetup(store, builds)
    search_service = SearchService(store, search_configuration)
    documents = DocumentProcessor(store, builds)
    work_inputs = WorkInputs(documents)
    work_uploads = WorkUploads(store)
    research.reader.documents = documents
    research.reader.browser = PublicBrowser(store, builds)
    diagnostics.builds = builds
    work = WorkRegistry(store, settings.models, inference, scheduler, memory, builds=builds)
    work.references.reader.documents = documents
    work.references.reader.browser = research.reader.browser
    work.public_research.search = research.search
    work.research_planner = research
    work.tool_setup = tool_setup
    runs = RunManager(store, settings.models, inference, scheduler, memory, research)
    lock = InstanceLock(settings.data_dir)

    @asynccontextmanager
    async def lifespan(app):
        lock.acquire()
        try:
            previous = store.one(
                "SELECT code FROM diagnostic_events WHERE code IN "
                "('backend_started','backend_stopped') ORDER BY id DESC LIMIT 1"
            )
            if previous and previous["code"] == "backend_started":
                store.log("backend_restarted")
            await runs.start()
            tool_setup.recover()
            search_service.recover()
            await builds.recover()
            await work.start()
            await downloads.start()
            await semantic.start()
            store.log("backend_started")
            yield
        finally:
            try:
                await search_service.stop_worker()
                await tool_setup.stop()
                await runs.stop()
                await work.stop()
                await semantic.stop()
                await downloads.stop()
                await runtime.stop()
                store.log("backend_stopped")
            finally:
                lock.release()

    app = FastAPI(
        title="dsGPT API",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    if settings.allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.allowed_origins),
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "Last-Event-ID"],
        )
    app.add_middleware(RequestBoundary, settings=settings)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))
    app.state.store, app.state.auth, app.state.runs = store, auth, runs
    app.state.work, app.state.scheduler, app.state.memory = work, scheduler, memory
    app.state.models = registry
    app.state.downloads = downloads
    app.state.runtime = runtime
    app.state.research = research
    app.state.semantic = semantic
    app.state.builds = builds

    @app.exception_handler(DownloadError)
    async def runtime_integrity_error(request, exc):
        return JSONResponse({"detail": "Managed asset verification failed", "code": str(exc)}, 409)

    @app.exception_handler(Exception)
    async def backend_failure(request, exc):
        code = "database_failed" if isinstance(exc, sqlite3.Error) else "backend_exception"
        try:
            store.log(code)
        except (sqlite3.Error, OSError):
            # A full/broken data volume cannot reliably persist its own diagnostics.
            pass
        return JSONResponse({"detail": "Backend operation failed", "code": code}, 503)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Default validation bodies may echo invalid passwords/tokens back to logs or clients.
        return JSONResponse(
            {
                "detail": "Invalid request",
                "fields": [{"location": e["loc"], "type": e["type"]} for e in exc.errors()],
            },
            status_code=422,
        )

    async def device(authorization: Annotated[str | None, Header()] = None):
        return auth.authenticate(authorization)

    def scoped(*scopes):
        async def check(current=Depends(device)):
            if not set(scopes).intersection(current["scopes"]):
                raise HTTPException(403, "Device lacks this permission")
            return current

        return check

    chat_device, work_device = scoped("chat"), scoped("work")
    diag_device, owner = scoped("diagnostics"), scoped("admin")
    model_manager = scoped("admin", "models")
    search_reader = scoped("chat", "admin")
    app.state.search_configuration = search_configuration
    history = History(store)
    app.state.history = history

    account_sessions = AccountSessions(store)
    app.state.account_sessions = account_sessions

    async def local_account_owner(request: Request, current=Depends(owner)):
        try:
            local = request.client is not None and ipaddress.ip_address(
                request.client.host
            ).is_loopback
        except ValueError:
            local = False
        if not local:
            raise HTTPException(403, "Account access requires the local desktop owner")
        return current

    @app.get("/v1/account-sessions")
    async def list_account_sessions(current=Depends(local_account_owner)):
        return account_sessions.list(current["id"])

    @app.post("/v1/account-sessions", status_code=201)
    async def create_account_session(
        body: AccountSessionCreate, current=Depends(local_account_owner)
    ):
        return await account_sessions.create(current["id"], body)

    @app.post("/v1/account-sessions/{session_id}/read")
    async def read_account_session(session_id: UUID, current=Depends(local_account_owner)):
        return await account_sessions.read(current["id"], str(session_id))

    @app.delete("/v1/account-sessions/{session_id}", status_code=204)
    async def revoke_account_session(session_id: UUID, current=Depends(local_account_owner)):
        await account_sessions.revoke(current["id"], str(session_id))
        return Response(status_code=204)

    @app.get("/v1/account-sessions/{session_id}/grants")
    async def list_account_grants(session_id: UUID, current=Depends(local_account_owner)):
        return account_sessions.grants(current["id"], str(session_id))

    @app.post("/v1/account-sessions/{session_id}/grants", status_code=201)
    async def create_account_grant(
        session_id: UUID, body: AccountGrantCreate, current=Depends(local_account_owner)
    ):
        return await account_sessions.grant(current["id"], str(session_id), body)

    @app.delete("/v1/account-sessions/{session_id}/grants/{grant_id}", status_code=204)
    async def revoke_account_grant(
        session_id: UUID, grant_id: UUID, current=Depends(local_account_owner)
    ):
        await account_sessions.revoke_grant(current["id"], str(session_id), str(grant_id))
        return Response(status_code=204)

    @app.post("/v1/work/tasks/{task_id}/account-grants/{grant_id}/read")
    async def read_granted_account(
        task_id: UUID, grant_id: UUID, current=Depends(work_device)
    ):
        return await account_sessions.read_grant(current["id"], str(task_id), str(grant_id))

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    from .dictation import Dictation

    dictation = Dictation(settings.data_dir)
    app.state.dictation = dictation
    voice_device = scoped("chat", "work", "admin")

    @app.get("/v1/setup/experience", dependencies=[Depends(voice_device)])
    async def experience_status():
        path = settings.data_dir / "experience-setup.json"
        try:
            if path.stat().st_size > 4096:
                raise ValueError("Invalid setup status")
            value = json.loads(path.read_text(encoding="utf-8"))
            if value.get("status") == "running" and time.time() - value.get("updated_at", 0) > 600:
                return {
                    "status": "needs_attention",
                    "message": "Automatic setup paused. Restart dsGPT to resume downloads.",
                }
            return {key: value.get(key) for key in ("status", "message", "percent", "phase")}
        except (OSError, ValueError, TypeError):
            return {
                "status": "pending",
                "message": (
                    "The Windows app prepares standard models and local voice "
                    "automatically on launch."
                ),
            }

    @app.get("/v1/dictation", dependencies=[Depends(voice_device)])
    async def dictation_status():
        return dictation.status()

    @app.post("/v1/dictation")
    async def start_dictation(current=Depends(voice_device)):
        return await asyncio.to_thread(dictation.start, current["id"])

    @app.post("/v1/dictation/{session_id}")
    async def dictate(session_id: UUID, body: DictationChunk, current=Depends(voice_device)):
        return await asyncio.to_thread(
            dictation.chunk, current["id"], str(session_id), body.sequence, body.audio, body.final
        )

    @app.delete("/v1/dictation/{session_id}")
    async def stop_dictation(session_id: UUID, current=Depends(voice_device)):
        return await asyncio.to_thread(dictation.cancel, current["id"], str(session_id))

    @app.get("/v1/capabilities")
    async def capabilities(current=Depends(device)):
        scopes = current["scopes"]
        return {
            "backend_version": __version__,
            "schema_version": SCHEMA_VERSION,
            "permissions": {
                "chat": "chat" in scopes,
                "work": "work" in scopes,
                "model_management": bool({"admin", "models"}.intersection(scopes)),
                "search_administration": "admin" in scopes,
            },
            "attachments": {
                "chat_text_files": True,
                "keyword_search": True,
                "semantic_search": True,
                "chat_docx_files": True,
                "document_formats": ["docx", "pdf", "png", "jpg", "jpeg", "webp", "xlsx", "pptx"],
                "isolated_document_tools_ready": builds.ready,
                "image_interpretation": "local_ollama_vision_model_required",
                "max_document_bytes": MAX_DOCUMENT_BYTES,
                "max_document_total_bytes": MAX_DOCUMENT_TOTAL,
                "max_files": MAX_FILES,
                "max_file_bytes": MAX_FILE_BYTES,
                "max_message_bytes": MAX_MESSAGE_BYTES,
                "extensions": sorted(EXTENSIONS),
                "public_research_combination": False,
            },
            "memory": {"creation_retries": True, "semantic_retrieval": True},
            "history": {
                "local_archive_import": True,
                "keyword_search": True,
                "semantic_search": True,
                "source_provenance": True,
                "explicit_memory_copy": True,
                "semantic_retrieval": True,
                "remote_archive_upload": False,
            },
            "work": {
                "project_drafting": True,
                "code_execution": builds.ready,
                "isolated_build_protocol": True,
                "source_file_import": True,
                "document_and_zip_inputs": True,
                "public_file_downloads": True,
                "file_download_requires_web": True,
                "local_audio_transcription": True,
                "transcription_languages": ["en-US"],
                "transcription_window_seconds": 900,
                "build_artifacts": True,
                "reference_sources": True,
                "public_query_and_links": True,
                "ongoing_research": True,
                "public_page_reader": True,
                "isolated_browser": builds.ready,
                "source_management": True,
            },
        }

    if managed:

        @app.get("/managed/identity")
        async def managed_identity(challenge: str = Query(pattern=r"^[a-f0-9]{64}$")):
            return managed["identity"](challenge)

        @app.post("/v1/backend/stop", dependencies=[Depends(owner)])
        async def stop_managed_backend():
            managed["stop"]()
            return {"stopping": True}

    @app.get("/v1/schema", dependencies=[Depends(owner)])
    async def schema():
        return app.openapi()

    @app.post("/v1/pairings", dependencies=[Depends(owner)])
    async def create_pairing(body: PairingCreate):
        return auth.create_pairing(body.scopes)

    @app.post("/v1/pairings/redeem")
    async def redeem(body: PairingRedeem):
        return auth.redeem(body.code, body.name)

    @app.get("/v1/device")
    async def current_device(current=Depends(device)):
        return {key: current[key] for key in ("id", "name", "role", "scopes", "created_at")}

    @app.post("/v1/device/heartbeat")
    async def device_heartbeat(body: DeviceHeartbeat, current=Depends(device)):
        with store.transaction() as db:
            db.execute(
                "INSERT INTO device_presence VALUES(?,?,?) ON CONFLICT(device_id) DO UPDATE "
                "SET last_seen=excluded.last_seen,app_version=excluded.app_version",
                (current["id"], time.time(), body.app_version),
            )
        return {"id": current["id"], "connected": True}

    @app.get("/v1/devices/phone-status", dependencies=[Depends(owner)])
    async def phone_connection_status():
        phones = store.all(
            "SELECT d.id,d.name,p.last_seen,p.app_version FROM devices d LEFT JOIN "
            "device_presence p ON p.device_id=d.id WHERE d.revoked=0 AND d.role!='owner'"
            " AND (d.name='dsGPT Mobile' OR p.app_version IS NOT NULL) ORDER BY "
            "coalesce(p.last_seen,0) DESC"
        )
        for phone in phones:
            phone["online"] = bool(
                phone["last_seen"] and 0 <= time.time() - phone["last_seen"] < 90
            )
        return {
            "paired": bool(phones),
            "online": any(p["online"] for p in phones),
            "phones": phones,
        }

    @app.get("/v1/devices", dependencies=[Depends(owner)])
    async def devices(
        limit: int = Query(default=100, ge=1, le=200), offset: int = Query(default=0, ge=0)
    ):
        rows = store.all(
            "SELECT id,name,role,scopes,created_at,revoked FROM devices "
            "ORDER BY created_at,id LIMIT ? OFFSET ?",
            (limit, offset),
        )
        for row in rows:
            row["scopes"] = json.loads(row["scopes"])
        return rows

    @app.delete("/v1/devices/{device_id}", dependencies=[Depends(owner)])
    async def revoke(device_id: UUID):
        auth.revoke(str(device_id))
        return {"revoked": True}

    @app.get("/v1/models", dependencies=[Depends(scoped("chat", "models", "admin"))])
    async def models():
        return [
            {
                "id": m.id,
                "label": m.label,
                "abliterated": m.abliterated,
                "runtime_model": m.runtime_model,
                "context": m.context,
                "runtime": m.runtime,
                "output_tokens": m.output_tokens,
                "availability": "checked_when_used",
                "benchmark_status": "not_benchmarked",
                "digest_pinned": bool(m.expected_digest or runtime.attached(m.id)),
                "managed": runtime.attached(m.id) is not None,
                "configuration_owned": m.id in registry.configured_ids,
            }
            for m in settings.models.values()
        ]

    @app.get(
        "/v1/models/{model_id}/thinking",
        dependencies=[Depends(scoped("chat", "work", "models", "admin"))],
    )
    async def thinking_controls(model_id: str):
        model = settings.models.get(model_id)
        if not model:
            raise HTTPException(404, "Model not found")
        try:
            async with registry.validator.client(model) as client:
                local = await registry.validator.validate_local_model(client, model)
            return {
                "choices": local.get(
                    "thinking_choices", [{"id": "auto", "label": "Model default"}]
                ),
                "output_tokens": model.output_tokens,
                "context": model.context,
            }
        except Exception as exc:
            raise HTTPException(503, "Start Ollama to load supported thinking controls") from exc

    @app.get("/v1/model-catalog", dependencies=[Depends(model_manager)])
    async def model_catalog(include_embeddings: bool = False):
        return [
            asset.public()
            for asset in CATALOG.values()
            if include_embeddings or asset.kind != "embedding"
        ]

    @app.get("/v1/runtimes", dependencies=[Depends(model_manager)])
    async def runtimes():
        return runtime.packages.list()

    @app.get("/v1/runtime/status", dependencies=[Depends(model_manager)])
    async def runtime_status():
        return runtime.status()

    @app.post("/v1/runtimes/{runtime_id}/install", dependencies=[Depends(model_manager)])
    async def install_runtime(runtime_id: str):
        return await runtime.install(runtime_id)

    @app.delete("/v1/runtimes/{runtime_id}", dependencies=[Depends(model_manager)])
    async def remove_runtime(runtime_id: str):
        return await runtime.remove(runtime_id)

    @app.post("/v1/runtime/unload", dependencies=[Depends(model_manager)])
    async def unload_runtime():
        return await runtime.unload()

    @app.post("/v1/models/managed", dependencies=[Depends(model_manager)], status_code=201)
    async def attach_managed_model(body: ManagedModelCreate):
        fields = body.model_dump()
        fields["identifier"] = fields.pop("id")
        return await runtime.attach(**fields)

    @app.get("/v1/downloads", dependencies=[Depends(model_manager)])
    async def get_downloads():
        return downloads.list()

    @app.post("/v1/downloads", dependencies=[Depends(model_manager)], status_code=202)
    async def download_create(body: DownloadCreate):
        return downloads.submit(body.asset_id)

    @app.get("/v1/downloads/{download_id}", dependencies=[Depends(model_manager)])
    async def get_download(download_id: UUID):
        return downloads.get(str(download_id))

    @app.post("/v1/downloads/{download_id}/actions", dependencies=[Depends(model_manager)])
    async def download_action(download_id: UUID, body: DownloadAction):
        return await downloads.action(str(download_id), body.action)

    @app.delete("/v1/downloads/{download_id}", dependencies=[Depends(model_manager)])
    async def remove_download(download_id: UUID):
        return downloads.remove(str(download_id))

    @app.post("/v1/models/register", dependencies=[Depends(model_manager)], status_code=201)
    async def register_model(body: ModelRegistration):
        return await registry.register(body.model_dump())

    @app.delete("/v1/models/{model_id}", dependencies=[Depends(model_manager)])
    async def forget_model(model_id: str):
        return await runtime.forget(model_id)

    @app.post("/v1/conversations", dependencies=[Depends(chat_device)], status_code=201)
    async def create_conversation(body: ConversationCreate):
        chat_id, now = uid(), utcnow()
        with store.transaction() as db:
            db.execute(
                "INSERT INTO conversations(id,title,created_at,updated_at) VALUES(?,?,?,?)",
                (chat_id, body.title, now, now),
            )
        return store.one("SELECT * FROM conversations WHERE id=?", (chat_id,))

    @app.get("/v1/conversations", dependencies=[Depends(chat_device)])
    async def conversations(
        hidden: bool = False,
        q: str = Query(default="", max_length=500),
        limit: int = Query(default=100, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ):
        # Literal search avoids interpreting '%' and '_' as search wildcards.
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = "%" + escaped + "%"
        return store.all(
            "SELECT * FROM conversations c WHERE hidden=? AND (title LIKE ? ESCAPE '\\' OR "
            "EXISTS(SELECT 1 FROM messages m WHERE m.conversation_id=c.id AND "
            "m.content LIKE ? ESCAPE '\\')) "
            "ORDER BY pinned DESC,pin_order,updated_at DESC,id LIMIT ? OFFSET ?",
            (int(hidden), pattern, pattern, limit, offset),
        )

    @app.get("/v1/conversations/{chat_id}", dependencies=[Depends(chat_device)])
    async def get_conversation(chat_id: UUID):
        chat = store.one("SELECT * FROM conversations WHERE id=?", (str(chat_id),))
        if not chat:
            raise HTTPException(404, "Conversation not found")
        return chat

    @app.patch("/v1/conversations/{chat_id}", dependencies=[Depends(chat_device)])
    async def update_conversation(chat_id: UUID, body: ConversationPatch):
        changes = body.model_dump(exclude_none=True, exclude={"revision"})
        if not changes:
            raise HTTPException(422, "No changes supplied")
        assignments = ",".join(key + "=?" for key in changes)  # keys from fixed Pydantic schema
        with store.transaction() as db:
            changed = db.execute(
                "UPDATE conversations SET " + assignments + ",revision=revision+1,updated_at=? "
                "WHERE id=? AND revision=?",
                (*changes.values(), utcnow(), str(chat_id), body.revision),
            ).rowcount
            if not changed:
                raise HTTPException(409, "Conversation changed or no longer exists; reload first")
        return store.one("SELECT * FROM conversations WHERE id=?", (str(chat_id),))

    @app.delete("/v1/conversations/{chat_id}", dependencies=[Depends(chat_device)])
    async def delete_conversation(chat_id: UUID):
        identifier = str(chat_id)
        for run in store.all(
            "SELECT id FROM runs WHERE conversation_id=? AND status IN ('queued','running')",
            (identifier,),
        ):
            await runs.cancel(run["id"])
        with store.transaction() as db:
            if db.execute(
                "SELECT 1 FROM runs WHERE conversation_id=? AND status IN ('queued','running')",
                (identifier,),
            ).fetchone():
                raise HTTPException(409, "A new response started; stop it and retry deletion")
            db.execute(
                "INSERT OR IGNORE INTO history_tombstones SELECT source_id,? FROM "
                "history_sources WHERE conversation_id=?",
                (utcnow(), identifier),
            )
            for table in ("events", "web_sources", "run_research", "chat_submission_receipts"):
                column = "request_id" if table == "chat_submission_receipts" else "run_id"
                db.execute(
                    f"DELETE FROM {table} WHERE {column} IN "
                    "(SELECT id FROM runs WHERE conversation_id=?)",
                    (identifier,),
                )
            db.execute(
                "DELETE FROM generation_options WHERE kind='chat' AND id IN (SELECT id FROM "
                "runs WHERE conversation_id=?)",
                (identifier,),
            )
            db.execute("DELETE FROM runs WHERE conversation_id=?", (identifier,))
            db.execute(
                "DELETE FROM attachment_documents WHERE id IN (SELECT a.id FROM "
                "message_attachments a JOIN messages m ON m.id=a.message_id WHERE "
                "m.conversation_id=?)",
                (identifier,),
            )
            for table in ("message_attachments", "history_messages"):
                db.execute(
                    f"DELETE FROM {table} WHERE message_id IN "
                    "(SELECT id FROM messages WHERE conversation_id=?)",
                    (identifier,),
                )
            db.execute("DELETE FROM history_sources WHERE conversation_id=?", (identifier,))
            db.execute("DELETE FROM messages WHERE conversation_id=?", (identifier,))
            db.execute("DELETE FROM conversations WHERE id=?", (identifier,))
        return {"deleted": True}

    @app.get("/v1/conversations/{chat_id}/files", dependencies=[Depends(chat_device)])
    async def conversation_files(chat_id: UUID, offset: int = Query(default=0, ge=0)):
        if not store.one("SELECT id FROM conversations WHERE id=?", (str(chat_id),)):
            raise HTTPException(404, "Conversation not found")
        return store.all(
            "SELECT a.id,a.message_id,a.name,a.bytes,a.sha256,a.created_at,a.removed "
            "FROM message_attachments a JOIN messages m ON m.id=a.message_id WHERE "
            "m.conversation_id=? AND a.removed=0 ORDER BY m.ordinal,a.id LIMIT 100 "
            "OFFSET ?",
            (str(chat_id), offset),
        )

    @app.get("/v1/conversations/{chat_id}/messages", dependencies=[Depends(chat_device)])
    async def messages(
        chat_id: UUID,
        after: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=200),
    ):
        if not store.one("SELECT id FROM conversations WHERE id=?", (str(chat_id),)):
            raise HTTPException(404, "Conversation not found")
        return runs.attachments.metadata(
            store.all(
                "SELECT m.*,r.id AS run_id,r.error_code AS run_error_code,"
                "CASE WHEN rr.run_id IS NULL THEN 0 ELSE 1 END AS research "
                "FROM messages m LEFT JOIN runs r ON r.message_id=m.id "
                "LEFT JOIN run_research rr ON rr.run_id=r.id "
                "WHERE m.conversation_id=? AND m.ordinal>? ORDER BY m.ordinal LIMIT ?",
                (str(chat_id), after, limit),
            )
        )

    @app.post(
        "/v1/conversations/{chat_id}/messages", dependencies=[Depends(chat_device)], status_code=202
    )
    async def send_message(chat_id: UUID, body: MessageCreate):
        try:
            research_options = (
                research.validate(body.research.model_dump()) if body.research else None
            )
        except (ValueError, ResearchError) as exc:
            raise HTTPException(422, "Invalid research options") from exc
        submission_hash = fingerprint(
            body, conversation_id=str(chat_id), normalized={"research": research_options}
        )
        replay = runs.replay(str(body.request_id), submission_hash)
        if replay is not None:
            return replay
        prepared = await documents.prepare([a.model_dump() for a in body.attachments])
        return runs.submit(
            str(chat_id),
            str(body.request_id),
            body.content,
            body.model_id,
            research_options,
            [a.model_dump() for a in body.attachments],
            prepared=prepared,
            submission_hash=submission_hash,
            reasoning_effort=body.reasoning_effort,
            web_mode=body.web_mode,
        )

    @app.get("/v1/conversations/{chat_id}/latest-run", dependencies=[Depends(chat_device)])
    async def latest_run(chat_id: UUID):
        # Capture content and replay cursor in one transaction: clients must not append
        # events already represented by the restored assistant message.
        with store.transaction() as db:
            row = db.execute(
                "SELECT r.* FROM runs r JOIN messages m ON m.id=r.message_id "
                "WHERE r.conversation_id=? ORDER BY m.ordinal DESC LIMIT 1",
                (str(chat_id),),
            ).fetchone()
            if not row:
                return None
            message = db.execute(
                "SELECT m.*,r.id AS run_id,r.error_code AS run_error_code,"
                "CASE WHEN rr.run_id IS NULL THEN 0 ELSE 1 END AS research "
                "FROM messages m LEFT JOIN runs r ON r.message_id=m.id "
                "LEFT JOIN run_research rr ON rr.run_id=r.id WHERE m.id=?",
                (row["message_id"],),
            ).fetchone()
            cursor = db.execute(
                "SELECT COALESCE(MAX(id),0) FROM events WHERE run_id=?", (row["id"],)
            ).fetchone()[0]
            return {
                "run": dict(row),
                "message": runs.attachments.metadata([dict(message)])[0],
                "cursor": cursor,
            }

    @app.post("/v1/documents/preview", dependencies=[Depends(chat_device)])
    async def preview_document(body: ChatAttachmentInput):
        if body.original_base64 is None:
            raise HTTPException(422, "Provide a DOCX original")
        result = (await documents.prepare([body.model_dump()]))[0]
        return {k: v for k, v in result.items() if k != "original_base64"}

    @app.get(
        "/v1/conversations/{chat_id}/attachments/{attachment_id}",
        dependencies=[Depends(chat_device)],
    )
    async def read_attachment(
        chat_id: UUID, attachment_id: UUID, offset: int = Query(default=0, ge=0)
    ):
        return runs.attachments.text(str(chat_id), str(attachment_id), offset)

    @app.get(
        "/v1/conversations/{chat_id}/attachments/{attachment_id}/download",
        dependencies=[Depends(chat_device)],
    )
    async def download_attachment(chat_id: UUID, attachment_id: UUID):
        record = runs.attachments.get(str(chat_id), str(attachment_id))
        if record["removed"]:
            raise HTTPException(410, "The stored attachment body was removed")
        return Response(
            record["original"] if "original" in record else record["text"].encode("utf-8"),
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": 'attachment; filename="dsGPT-attachment.'
                + ("docx" if "original" in record else "txt")
                + '"'
            },
        )

    @app.delete(
        "/v1/conversations/{chat_id}/attachments/{attachment_id}",
        dependencies=[Depends(chat_device)],
    )
    async def remove_attachment(chat_id: UUID, attachment_id: UUID):
        return runs.attachments.remove(str(chat_id), str(attachment_id))

    @app.get("/v1/runs/{run_id}", dependencies=[Depends(chat_device)])
    async def get_run(run_id: UUID):
        row = store.one("SELECT * FROM runs WHERE id=?", (str(run_id),))
        if not row:
            raise HTTPException(404, "Run not found")
        return row

    @app.post("/v1/runs/{run_id}/cancel", dependencies=[Depends(chat_device)])
    async def cancel_run(run_id: UUID):
        return await runs.cancel(str(run_id))

    @app.get("/v1/research/capabilities", dependencies=[Depends(chat_device)])
    async def research_capabilities():
        return {
            "public_page_reading": True,
            "search_configured": research.search.origin is not None,
            "search_provider": "self-hosted SearXNG",
            "javascript_execution": False,
            "private_network_access": False,
            "paid_search_required": False,
            "search_configuration": True,
        }

    @app.get("/v1/research/settings")
    async def search_settings(current=Depends(search_reader)):
        return {**search_configuration.status(), "can_configure": "admin" in current["scopes"]}

    @app.put("/v1/research/settings", dependencies=[Depends(owner)])
    async def update_search_settings(body: SearchUpdate):
        return {**search_configuration.update(body.origin, body.revision), "can_configure": True}

    @app.post("/v1/research/check", dependencies=[Depends(owner)])
    async def check_search_settings(body: SearchCheck):
        return {**await search_configuration.check(body.revision), "can_configure": True}

    @app.get("/v1/runs/{run_id}/sources", dependencies=[Depends(chat_device)])
    async def research_sources(run_id: UUID, include_text: bool = False):
        if not store.one("SELECT id FROM runs WHERE id=?", (str(run_id),)):
            raise HTTPException(404, "Run not found")
        record = research.configured(str(run_id))
        return {
            "sources": research.sources(str(run_id), include_text),
            "retrieval_complete": bool(record and record["retrieval_complete"]),
            "warnings": json.loads(record["warnings"]) if record else [],
        }

    @app.get("/v1/runs/{run_id}/events")
    async def events(
        run_id: UUID,
        request: Request,
        current=Depends(chat_device),
        after: int = Query(default=0, ge=0),
        last_event_id: Annotated[str | None, Header()] = None,
    ):
        row = await get_run(run_id)
        if last_event_id:
            try:
                after = max(after, int(last_event_id))
            except ValueError as exc:
                raise HTTPException(422, "Invalid event cursor") from exc

        async def stream():
            cursor = after
            heartbeat = time.monotonic()
            while True:
                if await request.is_disconnected():
                    return
                still_valid = store.one("SELECT revoked FROM devices WHERE id=?", (current["id"],))
                if not still_valid or still_valid["revoked"]:
                    return
                batch = store.all(
                    "SELECT * FROM events WHERE run_id=? AND id>? ORDER BY id LIMIT 200",
                    (row["id"], cursor),
                )
                for event in batch:
                    cursor = event["id"]
                    yield f"id: {cursor}\nevent: {event['kind']}\ndata: {event['payload']}\n\n"
                state = store.one("SELECT status FROM runs WHERE id=?", (row["id"],))
                # Query completion then check for pending records to avoid a lost final event.
                if state is None:
                    return
                if state["status"] in TERMINAL and not store.one(
                    "SELECT id FROM events WHERE run_id=? AND id>? LIMIT 1", (row["id"], cursor)
                ):
                    return
                if time.monotonic() - heartbeat > 10:
                    yield ": heartbeat\n\n"
                    heartbeat = time.monotonic()
                await asyncio.sleep(0.05)

        return StreamingResponse(
            stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
        )

    @app.post("/v1/work/tasks", dependencies=[Depends(work_device)], status_code=201)
    async def create_task(body: TaskCreate, current=Depends(work_device)):
        urls = work.references.normalize(body.reference_urls)
        query = body.public_query.strip() if body.public_query is not None else None
        submission_hash = fingerprint(
            body, normalized={"reference_urls": urls, "public_query": query}
        )
        replay = work.replay(str(body.request_id), submission_hash) if body.request_id else None
        if replay is not None:
            return replay
        prepared, originals = await work_inputs.prepare([f.model_dump() for f in body.source_files])
        if len(body.upload_ids) + len(body.source_files) > 4:
            raise HTTPException(422, "Choose up to four Work inputs")
        if body.upload_ids and body.build_target == "source":
            raise HTTPException(
                422,
                "Select Automatic or Files output to inspect large originals with isolated tools. "
                "Small source imports also support Draft only.",
            )
        originals += work_uploads.originals(current["id"], [str(x) for x in body.upload_ids])
        if len({x["name"].casefold() for x in originals}) != len(originals):
            raise HTTPException(422, "Choose distinct input names")
        created = work.create(
            body.title,
            body.requirements,
            body.model_id,
            str(body.request_id) if body.request_id else None,
            urls,
            body.build_target,
            [file.model_dump() for file in body.source_files],
            query,
            body.follow_links,
            prepared_files=prepared,
            originals=originals,
            submission_hash=submission_hash,
            reasoning_effort=body.reasoning_effort,
            web_mode=body.web_mode,
            start=body.start,
        )

        for upload_id in body.upload_ids:
            work_uploads.delete(current["id"], str(upload_id))
        return created

    @app.post("/v1/work/uploads", status_code=201)
    async def start_upload(body: UploadCreate, current=Depends(work_device)):
        return work_uploads.start(current["id"], body.name, body.size)

    @app.get("/v1/work/uploads/{upload_id}")
    async def upload_status(upload_id: UUID, current=Depends(work_device)):
        return work_uploads.status(current["id"], str(upload_id))

    @app.put("/v1/work/uploads/{upload_id}")
    async def upload_chunk(upload_id: UUID, body: UploadChunk, current=Depends(work_device)):
        return work_uploads.chunk(current["id"], str(upload_id), body.offset, body.data)

    @app.post("/v1/work/uploads/{upload_id}/finish")
    async def finish_upload(upload_id: UUID, current=Depends(work_device)):
        return work_uploads.finish(current["id"], str(upload_id))

    @app.delete("/v1/work/uploads/{upload_id}")
    async def delete_upload(upload_id: UUID, current=Depends(work_device)):
        return work_uploads.delete(current["id"], str(upload_id))

    @app.post("/v1/work/inputs/preview", dependencies=[Depends(work_device)])
    async def preview_work_input(body: ChatAttachmentInput):
        if body.original_base64 is None:
            raise HTTPException(422, "Choose a document or source ZIP")
        return await work_inputs.preview(body.model_dump())

    @app.get("/v1/search/service", dependencies=[Depends(owner)])
    async def search_service_status():
        return search_service.status()

    @app.post(
        "/v1/search/service/{action}/{request_id}", dependencies=[Depends(owner)], status_code=202
    )
    async def manage_search_service(action: Literal["start", "stop"], request_id: UUID):
        return search_service.request(str(request_id), action)

    @app.get("/v1/tools/setup", dependencies=[Depends(owner)])
    async def tool_setup_status():
        return tool_setup.status()

    @app.post("/v1/tools/setup/{request_id}", dependencies=[Depends(owner)], status_code=202)
    async def start_tool_setup(request_id: UUID):
        return tool_setup.start(str(request_id))

    @app.get("/v1/work/sandbox", dependencies=[Depends(scoped("admin", "work"))])
    async def sandbox_status():
        return builds.status()

    @app.post("/v1/work/sandbox/probe", dependencies=[Depends(owner)])
    async def sandbox_probe():
        return await builds.probe()

    @app.get("/v1/work/tasks/{task_id}/executions", dependencies=[Depends(work_device)])
    async def task_executions(
        task_id: UUID,
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ):
        work.get(str(task_id))
        return store.all(
            "SELECT id,step,snapshot_sha256,image_id,status,cleanup_pending,recorded,created_at "
            "FROM work_executions WHERE task_id=? ORDER BY step DESC LIMIT ? OFFSET ?",
            (str(task_id), limit, offset),
        )

    @app.get(
        "/v1/work/tasks/{task_id}/executions/{execution_id}", dependencies=[Depends(work_device)]
    )
    async def task_execution(task_id: UUID, execution_id: UUID):
        row = store.one(
            "SELECT * FROM work_executions WHERE task_id=? AND id=?",
            (str(task_id), str(execution_id)),
        )
        if not row:
            raise HTTPException(404, "Execution not found")
        row["action"] = json.loads(row["action"])
        row["result"] = json.loads(row["result"]) if row["result"] else None
        return row

    @app.get("/v1/work/tasks/{task_id}/artifacts", dependencies=[Depends(work_device)])
    async def task_artifacts(
        task_id: UUID,
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ):
        work.get(str(task_id))
        return store.all(
            "SELECT id,execution_id,path,sha256,bytes FROM work_artifacts "
            "WHERE task_id=? ORDER BY rowid DESC LIMIT ? OFFSET ?",
            (str(task_id), limit, offset),
        )

    @app.get(
        "/v1/work/tasks/{task_id}/artifacts/{artifact_id}", dependencies=[Depends(work_device)]
    )
    async def task_artifact(task_id: UUID, artifact_id: UUID):
        row = store.one(
            "SELECT * FROM work_artifacts WHERE task_id=? AND id=?",
            (str(task_id), str(artifact_id)),
        )
        if not row:
            raise HTTPException(404, "Artifact not found")
        if hashlib.sha256(row["content"]).hexdigest() != row["sha256"]:
            raise HTTPException(409, "Stored artifact failed its integrity check")
        extension = (
            ".apk"
            if row["path"].lower().endswith(".apk")
            else ".exe"
            if row["path"].lower().endswith(".exe")
            else ".bin"
        )
        return Response(
            row["content"],
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": 'attachment; filename="dsGPT-artifact' + extension + '"',
                "X-Content-SHA256": row["sha256"],
            },
        )

    @app.get("/v1/work/tasks", dependencies=[Depends(work_device)])
    async def tasks(
        limit: int = Query(default=100, ge=1, le=200), offset: int = Query(default=0, ge=0)
    ):
        return [
            work.get(row["id"])
            for row in store.all(
                "SELECT id FROM work_tasks ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
        ]

    @app.get("/v1/work/tasks/{task_id}", dependencies=[Depends(work_device)])
    async def get_task(task_id: UUID):
        return work.get(str(task_id))

    @app.patch("/v1/work/tasks/{task_id}", dependencies=[Depends(work_device)])
    async def revise_task(task_id: UUID, body: TaskRevision):
        return work.revise(
            str(task_id),
            body.revision,
            body.note,
            body.model_id,
            body.reference_urls,
            body.retry_sources,
            resume=body.resume,
            reasoning_effort=body.reasoning_effort,
            web_mode=body.web_mode,
        )

    @app.post(
        "/v1/work/tasks/{task_id}/sources/{source_id}/actions", dependencies=[Depends(work_device)]
    )
    async def change_work_source(task_id: UUID, source_id: str, body: SourceChange):
        return work.change_source(
            str(task_id), source_id, body.action, body.revision, str(body.request_id)
        )

    @app.get("/v1/work/tasks/{task_id}/sources", dependencies=[Depends(work_device)])
    async def work_sources(
        task_id: UUID,
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ):
        work.get(str(task_id))
        return work.references.list(str(task_id), limit, offset)

    @app.get("/v1/work/tasks/{task_id}/sources/{source_id}", dependencies=[Depends(work_device)])
    async def work_source(
        task_id: UUID, source_id: str, offset: int = Query(default=0, ge=0, le=262144)
    ):
        work.get(str(task_id))
        with store.transaction() as db:
            result = work.references.read(db, str(task_id), source_id, offset)
        if result.get("error") == "source_not_found":
            raise HTTPException(404, "Reference source not found")
        return result

    @app.post("/v1/work/tasks/{task_id}/actions", dependencies=[Depends(work_device)])
    async def task_action(task_id: UUID, body: TaskAction):
        return work.transition(str(task_id), body.action, body.revision)

    @app.get("/v1/work/tasks/{task_id}/checkpoints", dependencies=[Depends(work_device)])
    async def task_checkpoints(
        task_id: UUID,
        limit: int = Query(default=100, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ):
        return work.checkpoints(str(task_id), limit, offset)

    @app.get("/v1/work/tasks/{task_id}/steps", dependencies=[Depends(work_device)])
    async def task_steps(
        task_id: UUID,
        after: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=200),
    ):
        work.get(str(task_id))
        rows = store.all(
            "SELECT * FROM work_steps WHERE task_id=? AND step>? ORDER BY step LIMIT ?",
            (str(task_id), after, limit),
        )
        for row in rows:
            row["action"], row["result"] = json.loads(row["action"]), json.loads(row["result"])
        return rows

    @app.get("/v1/work/tasks/{task_id}/files", dependencies=[Depends(work_device)])
    async def task_files(task_id: UUID):
        work.get(str(task_id))
        return store.all(
            "SELECT path,sha256,revision,length(CAST(content AS BLOB)) AS bytes "
            "FROM work_files WHERE task_id=? ORDER BY path",
            (str(task_id),),
        )

    @app.get("/v1/work/tasks/{task_id}/export", dependencies=[Depends(work_device)])
    async def task_export(task_id: UUID):
        work.get(str(task_id))
        return Response(
            work.tools.export(str(task_id)),
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="dsGPT-project.zip"'},
        )

    def memory_permission(current, task_id):
        if ("work" if task_id else "chat") not in current["scopes"]:
            raise HTTPException(403, "Device lacks permission for this memory scope")

    @app.get("/v1/retrieval/settings", dependencies=[Depends(owner)])
    async def retrieval_settings():
        return semantic.status()

    @app.patch("/v1/retrieval/settings", dependencies=[Depends(owner)])
    async def update_retrieval_settings(body: RetrievalSettings):
        return await semantic.configure(
            body.revision, body.enabled, body.history_enabled, body.attachments_enabled
        )

    @app.post("/v1/retrieval/search")
    async def semantic_search(body: RetrievalQuery, current=Depends(device)):
        project = str(body.task_id) if body.task_id else None
        if body.kind in {"history", "attachment"}:
            if "chat" not in current["scopes"]:
                raise HTTPException(403, "Device lacks Chat permission")
        else:
            memory_permission(current, project)
            memory.check_project(project)
        return await semantic.search(body.query, body.kind, project, body.hidden, body.limit)

    @app.get("/v1/memories")
    async def memories(
        current=Depends(device),
        task_id: UUID | None = None,
        q: str = Query(default="", max_length=1000),
        limit: int = Query(default=100, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ):
        project = str(task_id) if task_id else None
        memory_permission(current, project)
        return memory.list(q, project, limit, offset)

    @app.get("/v1/attachments/search", dependencies=[Depends(chat_device)])
    async def attachment_search(
        q: str = Query(min_length=1, max_length=1000),
        hidden: bool = False,
        conversation_id: UUID | None = None,
        limit: int = Query(default=50, ge=1, le=50),
        offset: int = Query(default=0, ge=0, le=10000),
    ):
        return runs.attachments.search(
            q, hidden, limit, offset, str(conversation_id) if conversation_id else None
        )

    @app.get("/v1/history/search", dependencies=[Depends(chat_device)])
    async def history_search(
        q: str = Query(min_length=1, max_length=1000),
        hidden: bool = False,
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ):
        return history.search(q, hidden, limit, offset)

    @app.get("/v1/conversations/{chat_id}/import", dependencies=[Depends(chat_device)])
    async def history_provenance(chat_id: UUID):
        return history.provenance(str(chat_id))

    @app.get("/v1/history/imports", dependencies=[Depends(owner)])
    async def history_imports(
        limit: int = Query(default=100, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ):
        return history.list(limit, offset)

    @app.delete("/v1/history/imports/{chat_id}", dependencies=[Depends(owner)])
    async def remove_history(chat_id: UUID):
        return history.remove(str(chat_id))

    @app.post("/v1/history/messages/{message_id}/memory", dependencies=[Depends(chat_device)])
    async def history_memory(message_id: UUID, body: HistoryMemoryCreate, current=Depends(device)):
        project = str(body.task_id) if body.task_id else None
        memory_permission(current, project)
        return history.promote(str(message_id), str(body.request_id), body.title, project)

    @app.post("/v1/memories", status_code=201)
    async def create_memory(body: MemoryCreate, current=Depends(device)):
        project = str(body.task_id) if body.task_id else None
        memory_permission(current, project)
        return memory.create(
            body.title,
            body.content,
            project,
            request_id=str(body.request_id) if body.request_id else None,
        )

    @app.patch("/v1/memories/{memory_id}")
    async def update_memory(memory_id: UUID, body: MemoryPatch, current=Depends(device)):
        row = memory.get(str(memory_id))
        memory_permission(current, row["task_id"])
        return memory.update(str(memory_id), body.revision, body.title, body.content)

    @app.delete("/v1/memories/{memory_id}")
    async def delete_memory(memory_id: UUID, revision: int = Query(ge=1), current=Depends(device)):
        row = memory.get(str(memory_id))
        memory_permission(current, row["task_id"])
        memory.delete(str(memory_id), revision)
        return {"deleted": True}

    @app.get("/v1/memories/export")
    async def export_memories(current=Depends(device), task_id: UUID | None = None):
        project = str(task_id) if task_id else None
        memory_permission(current, project)
        memory.check_project(project)
        rows = store.all("SELECT * FROM memories WHERE task_id IS ? ORDER BY id", (project,))
        return Response(
            json.dumps({"format": "dsgpt-memory-v1", "memories": rows}),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="dsGPT-memory.json"'},
        )

    @app.get("/v1/diagnostics/scheduler", dependencies=[Depends(diag_device)])
    async def scheduler_status():
        return scheduler.snapshot()

    @app.get("/v1/diagnostics/overview", dependencies=[Depends(diag_device)])
    async def overview():
        return await asyncio.to_thread(diagnostics.desktop_snapshot)

    @app.post("/v1/diagnostics/snapshots", status_code=201, dependencies=[Depends(diag_device)])
    async def manual_snapshot():
        return await asyncio.to_thread(diagnostics.capture_manual)

    @app.post("/v1/diagnostics/mobile", status_code=201)
    async def mobile_snapshot(
        request: Request, current=Depends(diag_device), collection_id: UUID | None = None
    ):
        # JSON validation preserves strict types and supports RFC3339 datetime/enum strings.
        try:
            body = MobileSnapshot.model_validate_json(await request.body())
        except ValueError as exc:
            raise HTTPException(
                422, "Invalid sanitized mobile snapshot or missing consent"
            ) from exc
        return diagnostics.save_mobile(
            current["id"], body, str(collection_id) if collection_id else None
        )

    @app.post("/v1/diagnostics/collections/{device_id}", dependencies=[Depends(owner)])
    async def request_collection(device_id: UUID):
        target = store.one("SELECT * FROM devices WHERE id=? AND revoked=0", (str(device_id),))
        if not target or "diagnostics" not in json.loads(target["scopes"]):
            raise HTTPException(404, "Diagnostic device unavailable")
        collection_id = uid()
        with store.transaction() as db:
            existing = db.execute(
                "SELECT * FROM collections WHERE device_id=? AND status='pending'",
                (str(device_id),),
            ).fetchone()
            if existing:
                return dict(existing)
            db.execute(
                "INSERT INTO collections VALUES(?,?,?,?,?)",
                (collection_id, str(device_id), "pending", utcnow(), None),
            )
        return {"id": collection_id, "status": "pending", "requires_device_consent": True}

    @app.get("/v1/diagnostics/collections")
    async def pending_collections(current=Depends(diag_device)):
        return store.all(
            "SELECT * FROM collections WHERE device_id=? AND status='pending'", (current["id"],)
        )

    @app.post("/v1/diagnostics/exports/preview")
    async def preview(body: ExportPreview, current=Depends(diag_device)):
        target = (
            str(body.mobile_device)
            if body.mobile_device
            else current["id"]
            if current["role"] != "owner"
            else None
        )
        if target and target != current["id"] and current["role"] != "owner":
            raise HTTPException(403, "Only the desktop owner can retrieve another mobile device")
        if body.include_work_logs and "work" not in current["scopes"]:
            raise HTTPException(403, "Work permission is required to include private build logs")
        return await asyncio.to_thread(
            diagnostics.preview, current["id"], target, body.include_work_logs
        )

    @app.get("/v1/diagnostics/exports/{export_id}")
    async def export(
        export_id: UUID,
        sha256: str = Query(pattern=r"^[0-9a-f]{64}$"),
        current=Depends(diag_device),
    ):
        content = diagnostics.download(
            str(export_id), current["id"], sha256, allow_work_logs="work" in current["scopes"]
        )
        return Response(
            content,
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="dsGPT-diagnostics.zip"'},
        )

    generated_openapi = app.openapi

    def openapi_with_mobile_contract():
        result = generated_openapi()
        mobile_schema = MobileSnapshot.model_json_schema(
            ref_template="#/components/schemas/{model}"
        )
        definitions = mobile_schema.pop("$defs", {})
        components = result.setdefault("components", {}).setdefault("schemas", {})
        components.update(definitions)
        components["MobileSnapshot"] = mobile_schema
        result["paths"]["/v1/diagnostics/mobile"]["post"]["requestBody"] = {
            "required": True,
            "content": {
                "application/json": {"schema": {"$ref": "#/components/schemas/MobileSnapshot"}}
            },
        }
        return result

    app.openapi = openapi_with_mobile_contract
    return app
