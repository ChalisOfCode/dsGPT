import asyncio
import hashlib
import io
import json
import sqlite3
import threading
import time
import zipfile
from uuid import uuid4

import pytest
from conftest import new_chat, pair, send, wait_run

from dsgpt.migrations import MIGRATIONS
from dsgpt.project_tools import ProjectAction, action_schema
from dsgpt.storage import APPLICATION_ID, SCHEMA, SCHEMA_VERSION, Store, canonical
from dsgpt.web_retrieval import ResearchError
from dsgpt.work import WorkRegistry
from dsgpt.work_references import WorkReferences


class Reader:
    def __init__(self):
        self.calls = []
        self.fail = False
        self.gate = threading.Event()
        self.gate.set()
        self.started = threading.Event()

    async def read(self, url):
        self.calls.append(url)
        self.started.set()
        while not self.gate.is_set():
            await asyncio.sleep(0.005)
        if self.fail:
            raise ResearchError("research_source_inaccessible")
        return {
            "url": url,
            "final_url": url,
            "text": "Reference marker COBALT. " + "é" * 4000,
            "title": "<b>Public reference</b>",
            "retrieved_at": "2026-10-19T00:00:00Z",
            "published_at": "unverified",
            "content_sha256": "a" * 64,
            "text_truncated": False,
            "links": [{"url": "https://example.org/unapproved"}],
        }


class Agent:
    def __init__(self, actions=None):
        self.calls = []
        self.actions = actions or [
            {"tool": "read_source", "source_id": "S1", "summary": "Read the provided source"},
            {
                "tool": "write_file",
                "path": "evidence.txt",
                "content": "COBALT",
                "summary": "Drafted evidence",
            },
            {"tool": "finish", "summary": "Source draft completed"},
        ]

    async def stream(self, model, messages, response_schema=None):
        self.calls.append((messages, response_schema))
        yield {
            "kind": "delta",
            "data": {
                "text": json.dumps(self.actions[min(len(self.calls) - 1, len(self.actions) - 1)])
            },
        }


def setup(backend, actions=None):
    reader, agent = Reader(), Agent(actions)
    backend.app.state.work.references.reader = reader
    backend.app.state.work.inference = agent
    return reader, agent


def create(backend, urls=None, **fields):
    response = backend.client.post(
        "/v1/work/tasks",
        json={
            "title": "Reference task",
            "requirements": "Use the supplied reference to draft evidence",
            "model_id": "test-na",
            "reference_urls": urls or ["https://example.org/reference"],
            **fields,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def transition(backend, task, action):
    response = backend.client.post(
        f"/v1/work/tasks/{task['id']}/actions",
        json={
            "action": action,
            "revision": task["revision"],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def wait_task(backend, task_id, status="completed"):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        task = backend.app.state.work.get(task_id)
        if task["status"] == status:
            return task
        time.sleep(0.01)
    raise AssertionError(task)


def test_sources_are_declared_before_reading_and_survive_creation_replay(backend):
    reader, _ = setup(backend)
    identifier = str(uuid4())
    task = create(
        backend,
        ["https://example.org/one#first", "https://example.org/one#second"],
        request_id=identifier,
    )
    assert task["references"] == {"total": 1, "pending": 1, "retrieved": 0, "failed": 0}
    assert reader.calls == []
    assert create(backend, ["https://example.org/one"], request_id=identifier)["id"] == identifier
    response = backend.client.patch(
        f"/v1/work/tasks/{identifier}",
        json={
            "revision": task["revision"],
            "reference_urls": [f"https://example.org/more/{n}" for n in range(6)],
        },
    )
    assert response.status_code == 200
    assert response.json()["references"]["total"] == 7  # Per-request bound, not a total-task quota.
    assert (
        create(backend, ["https://example.org/one"], request_id=identifier)["references"]["total"]
        == 7
    )
    rows = backend.client.get(f"/v1/work/tasks/{identifier}/sources?limit=2&offset=2").json()
    assert [row["source_id"] for row in rows] == ["S3", "S4"]
    assert all("text" not in row for row in rows)
    assert reader.calls == []
    changed = backend.client.post(
        "/v1/work/tasks",
        json={
            "title": task["title"],
            "requirements": task["requirements"],
            "model_id": "test-na",
            "request_id": identifier,
            "reference_urls": ["https://example.org/different"],
        },
    )
    assert changed.status_code == 409


@pytest.mark.parametrize(
    "url",
    [
        "http://example.org",
        "https://localhost",
        "https://127.0.0.1",
        "https://example.org:8443",
        "https://user:secret@example.org",
    ],
)
def test_unsafe_reference_declaration_never_commits_or_reads(backend, url):
    reader, _ = setup(backend)
    response = backend.client.post(
        "/v1/work/tasks", json={"title": "Invalid", "requirements": "Read", "reference_urls": [url]}
    )
    assert response.status_code == 422
    assert backend.store.all("SELECT * FROM work_tasks") == []
    assert backend.store.all("SELECT * FROM work_sources") == []
    assert reader.calls == []


def test_reference_permissions_and_task_scoped_reads(backend):
    task = create(backend)
    client, _ = pair(backend, ["chat", "models"])
    headers = {"Authorization": "Bearer " + client["token"]}
    for suffix in ["/sources", "/sources/S1"]:
        assert (
            backend.client.get(f"/v1/work/tasks/{task['id']}{suffix}", headers=headers).status_code
            == 403
        )
    assert backend.client.get(f"/v1/work/tasks/{task['id']}/sources/S99").status_code == 404
    assert (
        backend.client.get(f"/v1/work/tasks/{task['id']}/sources/S1").json()["error"]
        == "source_not_retrieved"
    )
    other = backend.app.state.work.create("Other", "No declared sources")
    with backend.store.transaction() as db:
        assert WorkReferences.read(db, other["id"], "S1") == {"error": "source_not_found"}
    assert not any(
        v["properties"]["tool"]["const"] == "read_source" for v in action_schema()["oneOf"]
    )
    assert any(
        v["properties"]["tool"]["const"] == "read_source"
        for v in action_schema(reference_sources=True)["oneOf"]
    )
    with pytest.raises(ValueError):
        ProjectAction(tool="read_source", source_id="../S1", summary="Invalid identity")


def test_reference_reads_preserve_snapshot_and_export_without_network_from_model(backend):
    reader, agent = setup(backend)
    task = create(backend)
    transition(backend, task, "start")
    finished = wait_task(backend, task["id"])
    assert finished["references"] == {"total": 1, "pending": 0, "retrieved": 1, "failed": 0}
    assert len(reader.calls) == 1
    prompt = json.loads(agent.calls[0][0][1]["content"])
    assert prompt["reference_sources"]["sources"][0]["source_id"] == "S1"
    steps = backend.client.get(f"/v1/work/tasks/{task['id']}/steps").json()
    result = steps[0]["result"]
    assert (
        result["text"].startswith("Reference marker COBALT")
        and len(result["text"].encode()) <= 3000
    )
    assert (
        result["text_sha256"]
        == hashlib.sha256(("Reference marker COBALT. " + "é" * 4000).encode()).hexdigest()
    )
    assert "links" not in result
    second = backend.client.get(
        f"/v1/work/tasks/{task['id']}/sources/S1?offset={result['next_offset']}"
    ).json()
    assert second["text"] and "�" not in second["text"]
    assert len(reader.calls) == 1
    with zipfile.ZipFile(
        io.BytesIO(backend.client.get(f"/v1/work/tasks/{task['id']}/export").content)
    ) as z:
        sources = json.loads(z.read("sources.json"))
        assert sources["format"] == "dsgpt-work-sources-v1"
        assert sources["sources"][0]["text"].endswith("é" * 4000)
        manifest = json.loads(z.read("manifest.json"))
        assert manifest["reference_sources"] == 1 and manifest["execution_verified"] is False
        assert z.read("project/evidence.txt") == b"COBALT"
        assert backend.credentials["token"].encode() not in z.read("sources.json")


def test_pause_during_reference_read_preserves_pending_state_and_chat_can_run(backend):
    reader, agent = setup(backend)
    reader.gate.clear()
    task = create(backend)
    transition(backend, task, "start")
    assert reader.started.wait(2)
    assert agent.calls == []
    chat = new_chat(backend)
    run = send(backend, chat).json()
    assert wait_run(backend, run["id"])["status"] == "completed"
    current = backend.app.state.work.get(task["id"])
    paused = transition(backend, current, "pause")
    assert paused["status"] == "paused"
    assert paused["references"]["pending"] == 1
    reader.gate.set()
    assert backend.app.state.work.get(task["id"])["status"] == "paused"
    transition(backend, backend.app.state.work.get(task["id"]), "resume")
    assert wait_task(backend, task["id"])["references"]["retrieved"] == 1
    assert len(reader.calls) == 2


def test_failed_source_retries_only_after_revision_guarded_user_update(backend):
    actions = [
        {"tool": "blocked", "summary": "Please retry the unavailable source"},
        *Agent().actions,
    ]
    reader, _ = setup(backend, actions)
    reader.fail = True
    task = create(backend)
    transition(backend, task, "start")
    blocked = wait_task(backend, task["id"], "blocked")
    assert blocked["references"]["failed"] == 1 and len(reader.calls) == 1
    assert (
        backend.client.patch(
            f"/v1/work/tasks/{task['id']}", json={"revision": 1, "retry_sources": True}
        ).status_code
        == 409
    )
    reader.fail = False
    response = backend.client.patch(
        f"/v1/work/tasks/{task['id']}",
        json={"revision": blocked["revision"], "retry_sources": True},
    )
    assert response.status_code == 200 and response.json()["references"]["pending"] == 1
    assert len(reader.calls) == 1
    transition(backend, response.json(), "resume")
    assert wait_task(backend, task["id"])["references"]["retrieved"] == 1
    assert len(reader.calls) == 2


def test_reference_snapshot_and_checkpoint_commit_or_rollback_together(backend):
    reader, _ = setup(backend)
    task = create(backend)
    with backend.store.transaction() as db:
        db.execute(
            "CREATE TRIGGER reject_reference_checkpoint BEFORE INSERT ON checkpoints "
            "WHEN NEW.state LIKE '%reference_retrieval%' "
            "BEGIN SELECT RAISE(ABORT,'fixture checkpoint failure'); END"
        )
    transition(backend, task, "start")
    blocked = wait_task(backend, task["id"], "blocked")
    assert blocked["blocker"] == "work_step_failed"
    source = backend.store.one("SELECT * FROM work_sources WHERE task_id=?", (task["id"],))
    assert source["status"] == "pending" and source["document"] is None
    assert not any(
        c["state"].get("action") == "reference_retrieval"
        for c in backend.app.state.work.checkpoints(task["id"])
    )
    with backend.store.transaction() as db:
        db.execute("DROP TRIGGER reject_reference_checkpoint")
    transition(backend, blocked, "resume")
    assert wait_task(backend, task["id"])["references"]["retrieved"] == 1
    assert len(reader.calls) == 2


def test_v6_upgrade_preserves_legacy_task_retries_memory_and_backup(tmp_path):
    legacy = hashlib.sha256(canonical(["Legacy", "Keep requirements", None]).encode()).hexdigest()
    with sqlite3.connect(tmp_path / "dsgpt.db") as db:
        db.executescript(SCHEMA + "".join(MIGRATIONS[v] for v in range(2, 7)))
        db.execute(f"PRAGMA application_id={APPLICATION_ID}")
        db.execute("PRAGMA user_version=6")
        db.execute(
            "INSERT INTO work_tasks VALUES"
            "('task','Legacy','Keep requirements','paused',2,'now','now')"
        )
        db.execute("INSERT INTO work_creation_requests VALUES('task',?)", (legacy,))
        db.execute(
            "INSERT INTO memories VALUES"
            "('memory','task','Keep','Retained note','user',1,'now','now')"
        )
        db.execute("INSERT INTO memory_creation_requests VALUES('memory','immutable-hash')")
    store = Store(tmp_path)
    assert store.one("PRAGMA user_version")["user_version"] == SCHEMA_VERSION
    work = WorkRegistry(store)
    assert work.create("Legacy", "Keep requirements", request_id="task")["status"] == "paused"
    assert work.get("task")["references"]["total"] == 0
    assert store.one("SELECT content FROM memories")["content"] == "Retained note"
    assert (
        store.one("SELECT request_hash FROM memory_creation_requests")["request_hash"]
        == "immutable-hash"
    )
    assert store.all("PRAGMA foreign_key_check") == []
    with sqlite3.connect(next(tmp_path.glob(f"before-v6-to-v{SCHEMA_VERSION}-*.db"))) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 6
        assert (
            db.execute("SELECT name FROM sqlite_master WHERE name='work_sources'").fetchone()
            is None
        )
