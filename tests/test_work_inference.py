"""Protocol faults and process recovery, not actual-model acceptance."""

import asyncio
import json
import os
import sqlite3
import subprocess
import sys
from dataclasses import replace

import httpx
import pytest
from test_inference import ollama_handler

from dsgpt.config import Model
from dsgpt.diagnostic_details import work_details
from dsgpt.inference import InferenceError, LocalInference
from dsgpt.scheduler import InferenceScheduler
from dsgpt.storage import APPLICATION_ID, SCHEMA, SCHEMA_VERSION, Store, uid
from dsgpt.work import WorkRegistry
from dsgpt.work_inference import LIMIT, Attempt, recent, recover


def setup(tmp_path):
    store = Store(tmp_path)
    model = Model(
        "private-id",
        "private-name",
        "ollama",
        "http://127.0.0.1:11434",
        "test:9b",
        context=8192,
        output_tokens=2048,
        reasoning_effort="off",
    )
    work = WorkRegistry(store, models={model.id: model}, scheduler=InferenceScheduler(store))
    task = work.create("private-title", "private-requirements", model.id)
    return store, model, work, task["id"]


@pytest.mark.parametrize(
    "reason,code", [("length", "output_limit"), ("stop", "empty_model_response")]
)
async def test_empty_ollama_stream_keeps_metrics_without_reasoning_or_current_settings(
    tmp_path, reason, code
):
    store, model, work, tid = setup(tmp_path)
    secret = "private-thinking-and-output"

    def handler(request):
        if request.url.path == "/api/show":
            return httpx.Response(
                200,
                json={
                    "model_info": {"general.architecture": "qwen"},
                    "thinking": {"values": [False, True]},
                },
            )
        if request.url.path != "/api/chat":
            return ollama_handler(request)
        return httpx.Response(
            200,
            text="\n".join(
                json.dumps(x)
                for x in [
                    {"message": {"thinking": secret, "content": " \n"}},
                    {
                        "done": True,
                        "done_reason": reason,
                        "eval_count": 22,
                        "eval_duration": 2000000000,
                        "load_duration": 40000000,
                    },
                ]
            ),
        )

    work.inference = LocalInference(httpx.MockTransport(handler))
    with pytest.raises(InferenceError, match=code):
        with Attempt(store, tid, "action", model) as attempt:
            async for event in work.inference.stream(model, [{"role": "user", "content": secret}]):
                attempt.observe(event)
    # Registration changes cannot rewrite historical configuration.
    work.models[model.id] = replace(model, context=4096, output_tokens=512)
    value = work_details(Store(tmp_path))["recent_inference_attempts"][0]
    assert value["status"] == "failed" and value["error_code"] == code
    assert value["model"]["context_tokens"] == 8192
    assert value["model"]["output_token_limit"] == 2048
    assert value["model"]["reasoning_effort"] == "off"
    assert value["context"]["method"] == "utf8_safety_estimate"
    assert value["metrics"]["eval_count"] == 22
    assert value["metrics"]["thinking_chunks"] == 1
    assert value["output_bytes"] == 2 and value["first_visible_text_seconds"] is None
    assert value["elapsed_seconds"] >= 0
    for hidden in (secret, model.id, model.name, model.endpoint, model.runtime_model):
        assert hidden not in json.dumps(value)
    assert secret.encode() not in store.path.read_bytes()


@pytest.mark.parametrize("terminal", ["success", "cancel", "error", "consumer_error"])
async def test_partial_stream_terminal_outcomes_preserve_only_counts(tmp_path, terminal):
    store, model, _, tid = setup(tmp_path)
    error = {
        "cancel": asyncio.CancelledError(),
        "error": InferenceError("runtime_unavailable"),
        "consumer_error": ValueError("private-exception"),
    }.get(terminal)
    try:
        with Attempt(store, tid, "specification", model) as attempt:
            attempt.observe({"kind": "delta", "data": {"text": "秘密"}})
            attempt.observe(
                {
                    "kind": "metrics",
                    "data": {
                        "eval_count": 2,
                        "load_duration": float("nan"),
                        "prompt_tokens": True,
                        "total_tokens": -1,
                        "completion_tokens": "private-token",
                        "secret": "private",
                    },
                }
            )
            if error is not None:
                raise error
    except BaseException as observed:
        assert observed is error
    value = recent(store)[0]
    assert (
        value["status"]
        == {
            "success": "stream_completed",
            "cancel": "cancelled",
            "error": "failed",
            "consumer_error": "failed",
        }[terminal]
    )
    assert value["output_bytes"] == 6 and value["first_visible_text_seconds"] >= 0
    assert value["metrics"] == {"eval_count": 2}
    assert not any(s in json.dumps(value) for s in ("秘密", "private-exception", "private-token"))


async def test_work_asset_review_records_attempt_and_leaves_response_unchanged(tmp_path):
    store, model, work, tid = setup(tmp_path)

    class Image:
        async def stream(self, *args, **kwargs):
            yield {"kind": "context", "data": {"method": "runtime_tokenizer", "input_tokens": 2}}
            yield {
                "kind": "delta",
                "data": {"text": '{"brief":"Observed","section_notes":"Image"}'},
            }

    work.inference = Image()
    with store.transaction() as db:
        db.execute(
            "INSERT INTO work_inputs VALUES(?,?,?,?,?)",
            (tid, "fixture.png", b"\x89PNG\r\n\x1a\n", "a" * 64, "{}"),
        )
    result = await work._inspect_asset_image(tid, model, "inputs/fixture.png")
    assert result["brief"] == "Observed"
    value = recent(store, tid)[0]
    assert value["phase"] == "asset_image" and value["next_step"] == 1
    assert value["status"] == "stream_completed"
    assert "Observed" not in json.dumps(value)


async def test_work_cancellation_keeps_observed_stream_counters(tmp_path):
    store, model, work, tid = setup(tmp_path)
    ready = asyncio.Event()

    class Streaming:
        async def stream(self, *args, **kwargs):
            yield {"kind": "context", "data": {"method": "runtime_tokenizer", "input_tokens": 7}}
            yield {"kind": "delta", "data": {"text": "private-partial"}}
            ready.set()
            await asyncio.Event().wait()

    work.inference = Streaming()
    with store.transaction() as db:
        db.execute("UPDATE work_tasks SET status='queued' WHERE id=?", (tid,))
    running = asyncio.create_task(work._step(work.get(tid)))
    await asyncio.wait_for(ready.wait(), timeout=2)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    value, = recent(store, tid)
    assert value["status"] == "cancelled"
    assert value["output_bytes"] == len("private-partial")
    assert value["context"]["input_tokens"] == 7
    assert "private-partial" not in json.dumps(value)
    assert not store.all("SELECT * FROM work_steps")


def test_diagnostic_preview_contains_frozen_attempt_but_not_content(backend):
    task = backend.client.post("/v1/work/tasks", json={
        "title": "private-title", "requirements": "private-requirements"
    }).json()
    model = next(iter(backend.settings.models.values()))
    with Attempt(backend.store, task["id"], "action", model) as attempt:
        attempt.observe({"kind": "delta", "data": {"text": "private-output"}})
    preview = backend.client.post("/v1/diagnostics/exports/preview", json={}).json()
    all_text = json.dumps(preview)
    assert attempt.id in all_text and "stream_completed" in all_text
    assert not any(
        s in all_text for s in ("private-title", "private-requirements", "private-output")
    )


async def test_work_research_planning_metrics_are_retained_without_changing_fallback(tmp_path):
    from types import SimpleNamespace

    from dsgpt.research import Research

    store, model, work, tid = setup(tmp_path)

    class Empty:
        async def stream(self, *args, **kwargs):
            yield {"kind": "metrics", "data": {"eval_count": 8}}
            raise InferenceError("empty_model_response")

    research = Research(store, work.models, Empty(), work.scheduler,
                        search=SimpleNamespace(origin="http://127.0.0.1:12345"))
    result = await research.automatic_plan(model, "current public weather", "on", "work", tid)
    assert result == ["current public weather"]
    value, = recent(store)
    assert value["phase"] == "research_plan" and value["error_code"] == "empty_model_response"
    assert value["metrics"]["eval_count"] == 8
    assert "current public weather" not in json.dumps(value)


def test_abrupt_exit_recovery_does_not_invent_terminal_metrics_or_replay(tmp_path):
    store, _, _, tid = setup(tmp_path)
    program = """
import os,sys
from dsgpt.storage import Store
from dsgpt.config import Model
from dsgpt.work_inference import Attempt
store=Store(sys.argv[1])
model=Model('private','private','ollama','http://127.0.0.1:11434','private')
a=Attempt(store,sys.argv[2],'action',model)
a.__enter__()
a.observe({'kind':'context','data':{'method':'runtime_tokenizer','input_tokens':7}})
os._exit(23)
"""
    child = subprocess.run(
        [sys.executable, "-B", "-c", program, str(tmp_path), tid],
        capture_output=True,
        timeout=20,
        env=dict(os.environ),
    )
    assert child.returncode == 23
    restarted = Store(tmp_path)
    assert recent(restarted)[0]["status"] == "running"
    with restarted.transaction() as db:
        recover(db)
    value = recent(restarted)[0]
    assert value["status"] == "interrupted" and value["error_code"] == "backend_restarted"
    assert value["context"]["input_tokens"] == 7 and value["metrics"] == {}
    assert value["output_bytes"] == 0
    assert not restarted.all("SELECT * FROM work_steps")


def test_attempt_retention_does_not_change_tasks_and_denies_unknown_phase(tmp_path):
    store, model, _, tid = setup(tmp_path)
    before = store.all("SELECT * FROM work_tasks")
    for _ in range(LIMIT + 2):
        with Attempt(store, tid, "input_image", model):
            pass
    assert store.one("SELECT COUNT(*) AS n FROM work_inference_attempts")["n"] == LIMIT
    assert len(recent(store, tid)) == 50
    assert store.all("SELECT * FROM work_tasks") == before
    with pytest.raises(ValueError):
        Attempt(store, tid, "private-phase", model)


def test_real_v31_migration_keeps_groups_and_originals_and_backup(tmp_path):
    from dsgpt.migrations import MIGRATIONS

    task, group = uid(), uid()
    with sqlite3.connect(tmp_path / "dsgpt.db") as db:
        db.executescript(SCHEMA + "".join(MIGRATIONS[n] for n in range(2, 32)))
        db.execute(f"PRAGMA application_id={APPLICATION_ID}")
        db.execute("PRAGMA user_version=31")
        db.execute(
            "INSERT INTO work_tasks VALUES(?,?,?,'paused',1,?,?)",
            (task, "Original", "Original bytes", "now", "now"),
        )
        db.execute(
            "INSERT INTO project_groups VALUES(?,?,1,?,?,?,0)",
            (group, "Original group", '["work"]', "now", "now"),
        )
    store = Store(tmp_path)
    assert store.one("PRAGMA user_version")["user_version"] == SCHEMA_VERSION
    assert store.one("SELECT requirements FROM work_tasks")["requirements"] == "Original bytes"
    assert store.one("SELECT name FROM project_groups")["name"] == "Original group"
    assert recent(store) == []
    (backup,) = tmp_path.glob("before-v31-*.db")
    with sqlite3.connect(backup) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 31
        assert db.execute("SELECT name FROM project_groups").fetchone()[0] == "Original group"
