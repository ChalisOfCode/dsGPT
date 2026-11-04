import asyncio
import hashlib
import time

from fastapi import HTTPException

from . import generation
from .attachments import Attachments, prepare
from .inference import InferenceError
from .memory import chat_context
from .storage import canonical, uid, utcnow
from .submissions import accepted, remember
from .web_retrieval import ResearchError

TERMINAL = {"completed", "failed", "interrupted", "cancelled"}


def add_event(db, run_id, kind, data):
    db.execute(
        "INSERT INTO events(run_id,kind,payload,created_at) VALUES(?,?,?,?)",
        (run_id, kind, canonical(data), utcnow()),
    )


class RunManager:
    """Durable accepted requests; client disconnects do not own inference tasks."""

    def __init__(self, store, models, inference, scheduler=None, memory=None, research=None):
        self.store, self.models, self.inference = store, models, inference
        self.scheduler, self.memory = scheduler, memory
        self.research = research
        self.attachments = Attachments(store)
        self.wake = asyncio.Event()
        self.worker = None
        self.active = None
        self.active_id = None

    async def start(self):
        with self.store.transaction() as db:
            interrupted = db.execute("SELECT * FROM runs WHERE status='running'").fetchall()
            for row in interrupted:
                db.execute(
                    "UPDATE runs SET status='interrupted',error_code='backend_restarted',"
                    "updated_at=? WHERE id=?",
                    (utcnow(), row["id"]),
                )
                db.execute(
                    "UPDATE messages SET status='interrupted' WHERE id=?", (row["message_id"],)
                )
                add_event(db, row["id"], "interrupted", {"code": "backend_restarted"})
        self.worker = asyncio.create_task(self._worker())

    async def stop(self):
        if self.worker:
            self.worker.cancel()
            try:
                await self.worker
            except asyncio.CancelledError:
                pass

    def replay(self, run_id, submission_hash):
        with self.store.connect() as db:
            if accepted(db, "chat", run_id, submission_hash):
                return dict(db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())
        return None

    def submit(
        self,
        conversation_id,
        run_id,
        content,
        model_id,
        research=None,
        attachments=None,
        *,
        prepared=None,
        submission_hash=None,
        reasoning_effort=None,
        web_mode="off",
    ):
        replay = self.replay(run_id, submission_hash)
        if replay is not None:
            return replay
        attachments = (
            prepared if prepared is not None else prepare(attachments or [], documents=True)
        )
        if attachments and research is not None:
            raise HTTPException(422, "Send private text attachments with Research turned off")
        if research is not None:
            try:
                research = self.research.validate(research)
            except (ValueError, ResearchError) as exc:
                raise HTTPException(422, "Invalid research options") from exc
        request = [conversation_id, content, model_id]
        if reasoning_effort is not None or web_mode != "off":
            request.append({"effort": reasoning_effort, "web_mode": web_mode})
        if research is not None:
            request.append(research)
        if attachments:
            request.append({"attachments": attachments})
        request_hash = hashlib.sha256(canonical(request).encode()).hexdigest()
        with self.store.transaction() as db:
            existing = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if existing:
                if accepted(db, "chat", run_id, submission_hash):
                    return dict(existing)
                if existing["request_hash"] != request_hash:
                    raise HTTPException(409, "Request id was already used for different input")
                remember(db, "chat", run_id, submission_hash)
                return dict(existing)
            if model_id not in self.models:
                raise HTTPException(422, "Configure a verified local model first")
            chat = db.execute(
                "SELECT * FROM conversations WHERE id=?", (conversation_id,)
            ).fetchone()
            if not chat:
                raise HTTPException(404, "Conversation not found")
            if db.execute(
                "SELECT 1 FROM runs WHERE conversation_id=? AND status IN ('queued','running')",
                (conversation_id,),
            ).fetchone():
                raise HTTPException(409, "Wait for the current reply before sending another")
            ordinal = db.execute(
                "SELECT COALESCE(MAX(ordinal),0) FROM messages WHERE conversation_id=?",
                (conversation_id,),
            ).fetchone()[0]
            assistant_id, user_id, now = uid(), uid(), utcnow()
            for mid, role, text, status, order in (
                (user_id, "user", content, "completed", ordinal + 1),
                (assistant_id, "assistant", "", "queued", ordinal + 2),
            ):
                db.execute(
                    "INSERT INTO messages VALUES(?,?,?,?,?,?,?)",
                    (mid, conversation_id, role, text, status, order, now),
                )
            self.attachments.insert(db, user_id, attachments)
            db.execute(
                "INSERT INTO runs VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    conversation_id,
                    model_id,
                    request_hash,
                    assistant_id,
                    "queued",
                    None,
                    now,
                    now,
                ),
            )
            db.execute(
                "UPDATE conversations SET model_id=?,revision=revision+1,updated_at=? WHERE id=?",
                (model_id, now, conversation_id),
            )
            remember(db, "chat", run_id, submission_hash)
            generation.save(
                db,
                "chat",
                run_id,
                reasoning_effort,
                "off" if attachments or research is not None else web_mode,
            )
            if research is not None:
                db.execute(
                    "INSERT INTO run_research(run_id,definition) VALUES(?,?)",
                    (run_id, canonical({**research, "question": content})),
                )
            add_event(db, run_id, "accepted", {"message_id": assistant_id})
        self.wake.set()
        return self.store.one("SELECT * FROM runs WHERE id=?", (run_id,))

    async def cancel(self, run_id):
        row = self.store.one("SELECT * FROM runs WHERE id=?", (run_id,))
        if not row:
            raise HTTPException(404, "Run not found")
        if row["status"] in TERMINAL:
            return row
        self._finish(run_id, "cancelled")
        if self.active_id == run_id and self.active:
            self.active.cancel()
            try:
                await self.active
            except asyncio.CancelledError:
                pass
        return self.store.one("SELECT * FROM runs WHERE id=?", (run_id,))

    def _finish(self, run_id, status, error_code=None):
        with self.store.transaction() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if row["status"] in TERMINAL:
                return
            db.execute(
                "UPDATE runs SET status=?,error_code=?,updated_at=? WHERE id=?",
                (status, error_code, utcnow(), run_id),
            )
            db.execute("UPDATE messages SET status=? WHERE id=?", (status, row["message_id"]))
            add_event(db, run_id, status, {"code": error_code} if error_code else {})

    async def _worker(self):
        try:
            while True:
                self.wake.clear()
                row = self.store.one(
                    "SELECT * FROM runs WHERE status='queued' ORDER BY created_at,id LIMIT 1"
                )
                if not row:
                    await self.wake.wait()
                    continue
                self.active_id = row["id"]
                self.active = asyncio.create_task(self._execute(row))
                try:
                    await self.active
                except asyncio.CancelledError:
                    if asyncio.current_task().cancelling():
                        raise
                finally:
                    self.active, self.active_id = None, None
        except asyncio.CancelledError:
            raise

    async def _execute(self, row):
        try:
            if self.research:
                await self.research.automatic_chat(row)
            if self.research and self.research.configured(row["id"]):
                await self.research.prepare(row)
            if self.scheduler:
                async with self.scheduler.acquire("chat", row["id"]):
                    await self._generate(row)
            else:
                await self._generate(row)
        except ResearchError as exc:
            self._finish(row["id"], "failed", str(exc))
            self.store.log("research_failed", row["id"])
        except InferenceError as exc:
            self._finish(row["id"], "failed", exc.code)
            self.store.log(exc.code, row["id"])
        except Exception:
            self._finish(row["id"], "failed", "research_failed")
            self.store.log("research_failed", row["id"])

    async def _generate(self, row):
        run_id = row["id"]
        model = self.models.get(row["model_id"])
        if not model:
            self._finish(run_id, "failed", "local_model_required")
            return
        model = generation.for_request(self.store, "chat", run_id, model)
        with self.store.transaction() as db:
            changed = db.execute(
                "UPDATE runs SET status='running',updated_at=? WHERE id=? AND status='queued'",
                (utcnow(), run_id),
            ).rowcount
            if not changed:
                return
            db.execute("UPDATE messages SET status='running' WHERE id=?", (row["message_id"],))
            add_event(db, run_id, "running", {"model_id": model.id})
        messages = self.store.all(
            "SELECT id,role,content FROM messages WHERE conversation_id=? "
            "AND status='completed' ORDER BY ordinal",
            (row["conversation_id"],),
        )
        messages, attachment_omitted = self.attachments.context(messages, model)
        if self.memory and not (self.research and self.research.configured(run_id)):
            query = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
            retrieved = await self.memory.aretrieve(query)
            messages, context = chat_context(model, messages, self.memory, retrieved)
            context["omitted_messages"] += attachment_omitted
            with self.store.transaction() as db:
                add_event(db, run_id, "retrieval", context)
        started, first_delta, total_bytes = time.perf_counter(), None, 0
        output_limited = False
        try:
            stream = (
                self.research.answer_stream(model, run_id, messages)
                if self.research and self.research.configured(run_id)
                else self.inference.stream(model, messages)
            )
            try:
                async for event in stream:
                    if event["kind"] == "delta":
                        first_delta = first_delta or time.perf_counter()
                        total_bytes += len(event["data"]["text"].encode())
                        if total_bytes > 8_000_000:
                            raise InferenceError("runtime_protocol_error")
                    if event["kind"] == "warning" and event["data"].get("code") == "output_limit":
                        output_limited = True
                    with self.store.transaction() as db:
                        add_event(db, run_id, event["kind"], event["data"])
                        if event["kind"] == "delta":
                            db.execute(
                                "UPDATE messages SET content=content || ? WHERE id=?",
                                (event["data"]["text"], row["message_id"]),
                            )
            finally:
                timing = {"elapsed_seconds": time.perf_counter() - started}
                if first_delta is not None:
                    timing["first_text_seconds"] = first_delta - started
                with self.store.transaction() as db:
                    add_event(db, run_id, "timing", timing)
            if first_delta is None:
                raise InferenceError("output_limit" if output_limited else "runtime_protocol_error")
            self._finish(run_id, "completed")
            self.store.log("run_completed", run_id)
        except asyncio.CancelledError:
            # Interrupted text is retained; do not silently regenerate or double-run work.
            self._finish(run_id, "interrupted", "backend_stopped_or_cancelled")
            raise
        except InferenceError as exc:
            self._finish(run_id, "failed", exc.code)
            self.store.log(exc.code, run_id)
        except ResearchError as exc:
            self._finish(run_id, "failed", str(exc))
            self.store.log("research_failed", run_id)
        except Exception:
            # Exception strings may contain prompts, paths or credentials.
            self._finish(run_id, "failed", "inference_failed")
            self.store.log("inference_failed", run_id)
