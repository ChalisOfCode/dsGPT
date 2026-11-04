import json
import sqlite3

import pytest
from conftest import new_chat, pair, send, wait_run

from dsgpt import migrations
from dsgpt.config import Model
from dsgpt.memory import Memory, chat_context
from dsgpt.storage import APPLICATION_ID, SCHEMA, SCHEMA_VERSION, InstanceLock, Store


def old_database(path):
    path.mkdir()
    with sqlite3.connect(path / "dsgpt.db") as db:
        db.executescript(SCHEMA)
        db.execute(f"PRAGMA application_id={APPLICATION_ID}")
        db.execute("PRAGMA user_version=1")
        db.execute(
            "INSERT INTO conversations(id,title,created_at,updated_at) "
            "VALUES('keep','Keep this conversation','now','now')"
        )


def test_migration_preserves_data_and_creates_restorable_backup(tmp_path):
    path = tmp_path / "data"
    old_database(path)
    store = Store(path)
    assert store.one("SELECT title FROM conversations")["title"] == "Keep this conversation"
    assert store.one("PRAGMA user_version")["user_version"] == SCHEMA_VERSION
    backups = list(path.glob("before-v1-*.db"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("SELECT title FROM conversations").fetchone()[0].startswith("Keep")
    Store(path)
    assert len(list(path.glob("before-v1-*.db"))) == 1


def test_migration_failure_rolls_back_schema_and_keeps_backup(tmp_path, monkeypatch):
    path = tmp_path / "data"
    old_database(path)
    monkeypatch.setitem(migrations.MIGRATIONS, 2, "CREATE TABLE must_rollback(id); INVALID SQL;")
    with pytest.raises(sqlite3.OperationalError):
        Store(path)
    with sqlite3.connect(path / "dsgpt.db") as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert not db.execute(
            "SELECT name FROM sqlite_master WHERE name='must_rollback'"
        ).fetchone()
        assert db.execute("SELECT id FROM conversations").fetchone()[0] == "keep"
    assert len(list(path.glob("before-v1-*.db"))) == 1


def test_upgrade_refuses_live_backend_and_incomplete_schema(tmp_path):
    path = tmp_path / "data"
    old_database(path)
    lock = InstanceLock(path)
    lock.acquire()
    try:
        with pytest.raises(RuntimeError, match="Another"):
            Store(path)
    finally:
        lock.release()
    assert not list(path.glob("before-v1-*.db"))
    with sqlite3.connect(path / "dsgpt.db") as db:
        db.execute("DROP TABLE pairings")
    with pytest.raises(ValueError, match="Incomplete"):
        Store(path)


def test_memory_crud_search_export_revision_and_scope(backend):
    c = backend.client
    task = c.post("/v1/work/tasks", json={"title": "Project", "requirements": "Aurora app"}).json()
    personal = c.post(
        "/v1/memories", json={"title": "Location", "content": "Aurora Colorado"}
    ).json()
    project = c.post(
        "/v1/memories",
        json={"title": "Project", "content": "Aurora private project", "task_id": task["id"]},
    ).json()
    assert [r["id"] for r in c.get("/v1/memories", params={"q": "Aurora"}).json()] == [
        personal["id"]
    ]
    assert c.get("/v1/memories", params={"q": '" OR ** ()'}).status_code == 200
    phone, _ = pair(backend, ["chat"])
    headers = {"Authorization": "Bearer " + phone["token"]}
    assert c.get("/v1/memories", params={"task_id": task["id"]}, headers=headers).status_code == 403
    assert c.delete(f"/v1/memories/{project['id']}?revision=1", headers=headers).status_code == 403
    patch = {"revision": 1, "title": "Location", "content": "Denver Colorado"}
    assert c.patch("/v1/memories/" + personal["id"], json=patch).json()["revision"] == 2
    assert c.patch("/v1/memories/" + personal["id"], json=patch).status_code == 409
    assert c.get("/v1/memories", params={"q": "Aurora"}).json() == []
    export = c.get("/v1/memories/export").json()
    assert export["memories"][0]["content"] == "Denver Colorado"
    assert project["id"] not in json.dumps(export)
    assert c.delete(f"/v1/memories/{personal['id']}?revision=1").status_code == 409
    assert c.delete(f"/v1/memories/{personal['id']}?revision=2").status_code == 200
    assert c.get("/v1/memories", params={"q": "Denver"}).json() == []


def test_chat_retrieves_only_relevant_global_memory_and_deletion_takes_effect(backend):
    c = backend.client
    memory = c.post(
        "/v1/memories", json={"title": "Guitar", "content": "My guitar is blue."}
    ).json()
    c.post("/v1/memories", json={"title": "Unrelated", "content": "Car is red."})
    run = send(backend, new_chat(backend), "What color is my guitar?").json()
    assert wait_run(backend, run["id"])["status"] == "completed"
    context = backend.inference.calls[-1][1]
    assert context[0]["role"] == "system" and "My guitar is blue" in context[0]["content"]
    assert "Car is red" not in str(context)
    c.delete(f"/v1/memories/{memory['id']}?revision=1")
    run = send(backend, new_chat(backend), "My guitar?").json()
    wait_run(backend, run["id"])
    assert all(m["role"] != "system" for m in backend.inference.calls[-1][1])


def test_context_keeps_recent_whole_turns_and_never_truncates_latest(tmp_path):
    model = Model(
        "m", "M", "ollama", "http://127.0.0.1:11434", "m", context=2048, output_tokens=256
    )
    memory = Memory(Store(tmp_path))
    messages = [
        {"role": role, "content": str(i) * 280} for i in range(9) for role in ("user", "assistant")
    ]
    messages.append({"role": "user", "content": "current question"})
    context, stats = chat_context(model, messages, memory)
    assert stats["omitted_messages"] > 0
    assert context[0]["role"] == "user"
    assert context[-1]["content"] == "current question"
    latest = "x" * 5000
    assert (
        chat_context(model, [{"role": "user", "content": latest}], memory)[0][-1]["content"]
        == latest
    )
