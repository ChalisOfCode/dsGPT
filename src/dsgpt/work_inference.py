"""Frozen, bounded Work stream measurements. Never retain prompts or generated text."""

import asyncio
import hashlib
import time

from .diagnostic_details import ERROR_HELP, METRICS, model_details, object_value
from .hardware import number
from .inference import InferenceError
from .storage import canonical, uid, utcnow

PHASES = {"action", "specification", "input_image", "asset_image", "research_plan"}
LIMIT = 200


def recover(db):
    """A prior running receipt means the stream's terminal state was not observed."""
    for row in db.execute(
        "SELECT id,payload FROM work_inference_attempts WHERE status='running'"
    ).fetchall():
        value = object_value(row["payload"])
        value.update(status="interrupted", error_code="backend_restarted")
        db.execute(
            "UPDATE work_inference_attempts SET status='interrupted',updated_at=?,payload=? "
            "WHERE id=?",
            (utcnow(), canonical(value), row["id"]),
        )


def recent(store, task_id=None, limit=50):
    limit = max(1, min(int(limit), 50))
    query = "SELECT payload FROM work_inference_attempts "
    args = ()
    if task_id is not None:
        query += "WHERE task_id=? "
        args = (task_id,)
    rows = store.all(query + "ORDER BY rowid DESC LIMIT ?", (*args, limit))
    return [object_value(row["payload"]) for row in rows]


class Attempt:
    """Wrap one stream consumption, including consumer errors and cancellation.

    A completed stream does not establish that its JSON or proposed action is valid.
    Event measurements checkpoint at most once per second, plus context/metrics and
    terminal events. On abrupt process exit the last checkpoint is a lower bound.
    """

    def __init__(self, store, task_id, phase, model):
        if phase not in PHASES:
            raise ValueError("Unknown Work inference phase")
        self.store, self.task_id = store, task_id
        self.id, self.started = uid(), time.monotonic()
        self.last_saved = self.started
        self.visible = self.limited = False
        frozen = model_details(model)
        frozen.update(
            runtime_model_reference=hashlib.sha256(model.runtime_model.encode()).hexdigest()[:16],
            configured_digest=model.expected_digest,
            reasoning_effort=model.reasoning_effort
            if model.reasoning_effort in {None, "auto", "off", "on", "low", "medium", "high"}
            else "runtime_specific",
        )
        row = store.one(
            "SELECT t.revision,s.step FROM work_tasks t LEFT JOIN work_sessions s "
            "ON s.task_id=t.id WHERE t.id=?",
            (task_id,),
        )
        if row is None:
            raise ValueError("Work task missing")
        self.value = {
            "attempt_id": self.id,
            "task_id": task_id,
            "phase": phase,
            "task_revision": row["revision"],
            "next_step": (row["step"] or 0) + 1,
            "started_at": utcnow(),
            "status": "running",
            "error_code": None,
            "model": frozen,
            "context": {},
            "metrics": {},
            "output_bytes": 0,
            "first_visible_text_seconds": None,
            "elapsed_seconds": 0,
            "output_limit_reported": False,
            "scope": "Stream measurements, not action validation or tool success.",
            "interruption_limit": ("Abrupt exit retains only the last checkpoint; "
                                   "missing metrics are unknown."),
        }

    def __enter__(self):
        with self.store.transaction() as db:
            # Keep running receipts; the scheduler permits one Work stream at a time.
            db.execute(
                "DELETE FROM work_inference_attempts WHERE status!='running' AND id NOT IN "
                "(SELECT id FROM work_inference_attempts ORDER BY rowid DESC LIMIT ?)",
                (LIMIT - 1,),
            )
            if db.execute("SELECT COUNT(*) FROM work_inference_attempts").fetchone()[0] >= LIMIT:
                raise InferenceError("inference_diagnostics_full")
            db.execute(
                "INSERT INTO work_inference_attempts VALUES(?,?,?,?,?,?)",
                (
                    self.id,
                    self.task_id,
                    "running",
                    self.value["started_at"],
                    self.value["started_at"],
                    canonical(self.value),
                ),
            )
        return self

    def _save(self):
        self.last_saved = time.monotonic()
        self.value["elapsed_seconds"] = max(0, self.last_saved - self.started)
        self.value["updated_at"] = utcnow()
        with self.store.transaction() as db:
            db.execute(
                "UPDATE work_inference_attempts SET status=?,updated_at=?,payload=? WHERE id=?",
                (self.value["status"], self.value["updated_at"], canonical(self.value), self.id),
            )

    def observe(self, event):
        kind, data = event.get("kind"), event.get("data", {})
        if not isinstance(data, dict):
            return
        if kind == "delta" and isinstance(data.get("text"), str):
            text = data["text"]
            self.value["output_bytes"] += len(text.encode("utf-8"))
            if text.strip() and not self.visible:
                self.visible = True
                self.value["first_visible_text_seconds"] = max(0, time.monotonic() - self.started)
        elif kind == "context":
            if data.get("method") in {"runtime_tokenizer", "utf8_safety_estimate"}:
                self.value["context"]["method"] = data["method"]
            for key in ("input_tokens", "input_tokens_upper_estimate"):
                value = number(data.get(key), 1e9)
                if value is not None:
                    self.value["context"][key] = value
        elif kind == "metrics":
            for key in METRICS - {"first_text_seconds", "elapsed_seconds"}:
                value = number(data.get(key), 1e18)
                if value is not None:
                    self.value["metrics"][key] = value
        elif kind == "warning" and data.get("code") == "output_limit":
            self.limited = self.value["output_limit_reported"] = True
        if kind in {"context", "metrics"} or time.monotonic() - self.last_saved >= 1:
            self._save()

    def __exit__(self, kind, error, traceback):
        if kind is not None:
            if issubclass(kind, (asyncio.CancelledError, GeneratorExit)):
                self.value.update(status="cancelled", error_code="backend_stopped_or_cancelled")
            else:
                code = str(error) if isinstance(error, InferenceError) else None
                self.value.update(
                    status="failed",
                    error_code=code
                    if code in ERROR_HELP or code == "agent_output_too_large"
                    else "inference_failed",
                )
        elif not self.visible:
            self.value.update(
                status="failed",
                error_code="output_limit" if self.limited else "empty_model_response",
            )
        else:
            self.value["status"] = "stream_completed"
        self._save()
        return False
