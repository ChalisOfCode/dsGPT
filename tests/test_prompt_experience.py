"""Actual runtime controls, persisted task behavior and private live audio boundaries."""

import base64
import importlib.util
import json
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException

from dsgpt.config import Model
from dsgpt.dictation import Dictation
from dsgpt.generation import controls, options
from dsgpt.inference import InferenceError, LocalInference
from dsgpt.storage import Store


@pytest.mark.parametrize(
    "choice,wire", [("off", False), ("on", True), ("high", "high"), ("auto", None)]
)
async def test_thinking_selection_reaches_ollama_without_invented_levels(choice, wire):
    posted = []

    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": "local", "size": 6000, "digest": "a" * 64}]}
            )
        if request.url.path == "/api/show":
            return httpx.Response(
                200,
                json={
                    "model_info": {"architecture": "qwen"},
                    "thinking": {"values": [False, True, "high"]},
                },
            )
        posted.append(json.loads(request.content))
        return httpx.Response(200, text='{"message":{"content":"Ready"},"done":true}\n')

    inference = LocalInference(httpx.MockTransport(handler))
    model = Model(
        "test", "Local", "ollama", "http://127.0.0.1:11434", "local", reasoning_effort=choice
    )
    events = [e async for e in inference.stream(model, [{"role": "user", "content": "Hi"}])]
    assert (
        posted[0]["think"] is wire
        if isinstance(wire, bool) or wire is None
        else posted[0]["think"] == wire
    )
    assert any(e["kind"] == "delta" for e in events)
    with pytest.raises(InferenceError, match="thinking_control_unsupported"):
        _ = [
            e
            async for e in inference.stream(
                replace(model, reasoning_effort="ultra"), [{"role": "user", "content": "Hi"}]
            )
        ]
    assert len(posted) == 1  # No silent runtime fallback to a different setting.


def test_old_runtime_capabilities_do_not_invent_numeric_thinking_effort():
    assert [c["id"] for c in controls({"capabilities": ["thinking"]})] == ["auto", "off", "on"]
    assert controls({}) == [{"id": "auto", "label": "Model default"}]


class Recognizer:
    def AcceptWaveform(self, pcm):
        return False

    def PartialResult(self):
        return '{"partial":"live words"}'

    def FinalResult(self):
        return '{"text":"live words finished"}'


def test_audio_is_partial_before_stop_scoped_to_device_ordered_and_not_saved(tmp_path):
    voice = Dictation(tmp_path, Recognizer)
    session = voice.start("phone-a")["id"]
    audio = base64.b64encode(b"\0\0" * 200).decode()
    assert voice.chunk("phone-a", session, 0, audio) == {"text": "live words", "final": False}
    with pytest.raises(HTTPException) as denied:
        voice.chunk("phone-b", session, 1, audio)
    assert denied.value.status_code == 404
    with pytest.raises(HTTPException) as order:
        voice.chunk("phone-a", session, 0, audio)
    assert order.value.status_code == 409
    assert voice.chunk("phone-a", session, 1, "", True)["text"] == "live words finished"
    assert not voice.sessions
    assert list(tmp_path.iterdir()) == []


def test_audio_limits_and_replacement_release_sessions(tmp_path):
    voice = Dictation(tmp_path, Recognizer)
    first = voice.start("one")["id"]
    second = voice.start("one")["id"]
    assert first not in voice.sessions
    with pytest.raises(HTTPException) as invalid:
        voice.chunk("one", second, 0, base64.b64encode(b"x" * 32002).decode())
    assert invalid.value.status_code == 422
    voice.cancel("other", second)
    assert second in voice.sessions
    voice.cancel("one", second)
    assert not voice.sessions


def test_work_autostart_followup_and_model_effort_are_atomic_and_durable(backend):
    work = backend.app.state.work
    model = next(iter(backend.settings.models))
    identifier = str(uuid4())
    task = work.create(
        "Prompt",
        "Create a note",
        model,
        identifier,
        reasoning_effort="on",
        web_mode="auto",
        start=True,
    )
    assert task["status"] == "queued"
    assert options(backend.store, "work", identifier)["effort"] == "on"
    replay = work.create(
        "Prompt",
        "Create a note",
        model,
        identifier,
        reasoning_effort="on",
        web_mode="auto",
        start=True,
    )
    assert replay["id"] == task["id"]
    with backend.store.transaction() as db:
        db.execute("UPDATE work_tasks SET status='completed' WHERE id=?", (identifier,))
    revision = work.get(identifier)["revision"]
    updated = work.revise(
        identifier, revision, "Add a second page", resume=True, reasoning_effort="off"
    )
    assert updated["status"] == "queued"
    assert updated["requirements"].count("Add a second page") == 1
    with pytest.raises(HTTPException):
        work.revise(identifier, revision, "Add a second page", resume=True)
    assert options(Store(backend.store.directory), "work", identifier)["effort"] == "off"


def test_private_attachments_disable_automatic_search_at_acceptance(backend):
    from dsgpt.runs import RunManager
    from dsgpt.storage import utcnow

    store = backend.store
    conversation, run = str(uuid4()), str(uuid4())
    with store.transaction() as db:
        db.execute(
            "INSERT INTO conversations(id,title,created_at,updated_at) VALUES(?,?,?,?)",
            (conversation, "private", utcnow(), utcnow()),
        )
    runs = RunManager(store, backend.settings.models, None)
    runs.submit(
        conversation,
        run,
        "Look up this file",
        next(iter(backend.settings.models)),
        attachments=[{"name": "private.txt", "text": "never-search-this-secret"}],
        web_mode="auto",
    )
    assert options(store, "chat", run)["web_mode"] == "off"


def test_standard_model_recommendations_respect_memory():
    path = Path(__file__).resolve().parents[1] / "scripts/application/experience.py"
    spec = importlib.util.spec_from_file_location("experience_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.recommendations(32 * 1024**3, 12288) == [module.FAST_MODEL, module.QUALITY_MODEL]
    assert module.QUALITY_MODEL not in module.recommendations(16 * 1024**3, 8192)


def test_v21_profile_upgrade_keeps_messages_and_makes_a_backup(tmp_path):
    import sqlite3

    from dsgpt.storage import SCHEMA_VERSION, utcnow

    store = Store(tmp_path)
    with store.transaction() as db:
        db.execute(
            "INSERT INTO conversations(id,title,created_at,updated_at) VALUES(?,?,?,?)",
            ("keep-chat", "Keep my chat", utcnow(), utcnow()),
        )
        for table in (
            "account_browser_writes",
            "account_grants",
            "account_sessions",
            "device_presence",
            "work_uploads",
            "work_web_calls",
            "work_specs",
            "work_spec_sections",
            "work_signing_keys",
        ):
            db.execute("DROP TABLE " + table)
        db.execute("DROP TABLE generation_options")
        db.execute("PRAGMA user_version=21")
    upgraded = Store(tmp_path)
    assert (
        upgraded.one("SELECT title FROM conversations WHERE id='keep-chat'")["title"]
        == "Keep my chat"
    )
    assert upgraded.one("PRAGMA user_version")["user_version"] == SCHEMA_VERSION
    assert upgraded.all("SELECT * FROM generation_options") == []
    backups = list(tmp_path.glob(f"before-v21-to-v{SCHEMA_VERSION}-*.db"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 21


async def test_auto_search_planner_sees_only_current_question(backend):
    from dsgpt.research import Research
    from dsgpt.scheduler import InferenceScheduler

    seen = []

    class Planner:
        async def stream(self, model, messages, response_schema=None):
            seen.extend(messages)
            yield {
                "kind": "delta",
                "data": {"text": '{"search":true,"queries":["current Python release official"]}'},
            }

    research = Research(
        backend.store,
        backend.settings.models,
        Planner(),
        InferenceScheduler(backend.store),
        search_origin="http://127.0.0.1:8888",
    )
    result = await research.automatic_plan(
        next(iter(backend.settings.models.values())),
        "What is the current Python release?",
        "auto",
        "chat",
        str(uuid4()),
    )
    assert result == ["current Python release official"]
    assert len(seen) == 2 and seen[1]["content"] == "What is the current Python release?"
