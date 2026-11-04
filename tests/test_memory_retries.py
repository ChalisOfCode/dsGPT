import sqlite3
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi import HTTPException

from dsgpt.memory import Memory
from dsgpt.migrations import MIGRATIONS
from dsgpt.storage import APPLICATION_ID, SCHEMA, SCHEMA_VERSION, Store


def test_capabilities_report_actual_permissions_without_granting_them(backend):
    from conftest import pair

    owner = backend.client.get("/v1/capabilities").json()
    assert owner["memory"]["creation_retries"] is True
    assert owner["permissions"]["model_management"] is True
    assert owner["permissions"]["search_administration"] is True
    assert owner["work"]["code_execution"] is False
    phone, _ = pair(backend, ["chat"])
    headers = {"Authorization": "Bearer " + phone["token"]}
    capabilities = backend.client.get("/v1/capabilities", headers=headers).json()
    assert capabilities["permissions"] == {
        "chat": True,
        "work": False,
        "model_management": False,
        "search_administration": False,
    }
    assert backend.client.get("/v1/model-catalog", headers=headers).status_code == 403


def test_memory_create_retry_keeps_current_record_and_rejects_changed_request(backend):
    body = {"request_id": str(uuid4()), "title": "Preference", "content": "Use plain text"}
    first = backend.client.post("/v1/memories", json=body)
    assert first.status_code == 201
    row = first.json()
    assert row["id"] == body["request_id"]
    assert backend.client.post("/v1/memories", json=body).json() == row
    assert len(backend.client.get("/v1/memories").json()) == 1
    changed = backend.client.post("/v1/memories", json={**body, "content": "Different"})
    assert changed.status_code == 409
    updated = backend.client.patch(
        f"/v1/memories/{row['id']}",
        json={"revision": 1, "title": "Updated preference", "content": "Use short paragraphs"},
    ).json()
    assert updated["revision"] == 2
    # A delayed creation retry must return the edited record, never overwrite it.
    assert backend.client.post("/v1/memories", json=body).json() == updated


def test_memory_receipt_survives_deletion_and_process_style_reopen(tmp_path):
    memory = Memory(Store(tmp_path))
    identifier = str(uuid4())
    memory.create("Temporary", "Do not resurrect", request_id=identifier)
    memory.delete(identifier, 1)
    reopened = Memory(Store(tmp_path))
    with pytest.raises(HTTPException) as failure:
        reopened.create("Temporary", "Do not resurrect", request_id=identifier)
    assert failure.value.status_code == 409
    assert reopened.list() == []
    assert reopened.list("resurrect") == []
    assert reopened.store.one("SELECT COUNT(*) AS n FROM memory_creation_requests")["n"] == 1


def test_memory_creation_receipt_and_fts_rollback_together(tmp_path):
    store = Store(tmp_path)
    with store.transaction() as db:
        db.execute(
            "CREATE TRIGGER fail_receipt BEFORE INSERT ON memory_creation_requests "
            "BEGIN SELECT RAISE(ABORT,'fixture receipt failure'); END"
        )
    memory = Memory(store)
    with pytest.raises(sqlite3.IntegrityError, match="fixture receipt failure"):
        memory.create("Never commit", "Rollback marker", request_id=str(uuid4()))
    assert memory.list() == []
    assert memory.list("Rollback") == []
    assert store.all("SELECT * FROM memory_creation_requests") == []


def test_concurrent_memory_creation_retries_commit_once(tmp_path):
    memory = Memory(Store(tmp_path))
    identifier = str(uuid4())
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(
                lambda _: memory.create("Concurrent", "One record", request_id=identifier), range(8)
            )
        )
    assert {row["id"] for row in results} == {identifier}
    assert len(memory.list()) == 1
    assert memory.store.one("SELECT COUNT(*) AS n FROM memory_creation_requests")["n"] == 1


def test_v5_upgrade_backs_up_research_and_memory_before_receipts(tmp_path):
    with sqlite3.connect(tmp_path / "dsgpt.db") as db:
        db.executescript(SCHEMA + "".join(MIGRATIONS[v] for v in range(2, 6)))
        db.execute(f"PRAGMA application_id={APPLICATION_ID}")
        db.execute("PRAGMA user_version=5")
        db.execute(
            "INSERT INTO work_tasks VALUES"
            "('task','Keep task','Requirements','paused',2,'now','now')"
        )
        db.execute(
            "INSERT INTO memories VALUES"
            "('memory','task','Keep memory','Preserved content','user',3,'now','now')"
        )
        db.execute("INSERT INTO conversations VALUES('chat','Keep chat',NULL,0,0,0,1,'now','now')")
        db.execute(
            "INSERT INTO messages VALUES"
            "('message','chat','assistant','Prior answer','completed',1,'now')"
        )
        db.execute(
            "INSERT INTO runs VALUES"
            "('run','chat','model','hash','message','completed',NULL,'now','now')"
        )
        db.execute("INSERT INTO run_research VALUES('run','{}',NULL,1,'[]')")
        db.execute(
            "INSERT INTO web_sources VALUES('source','run','https://example.org','retrieved','{}',NULL)"
        )
    store = Store(tmp_path)
    assert store.one("PRAGMA user_version")["user_version"] == SCHEMA_VERSION
    assert Memory(store).list("Preserved", "task")[0]["revision"] == 3
    assert store.one("SELECT * FROM work_tasks")["status"] == "paused"
    assert store.one("SELECT * FROM web_sources")["status"] == "retrieved"
    assert store.one("SELECT * FROM messages")["content"] == "Prior answer"
    assert store.all("SELECT * FROM memory_creation_requests") == []
    assert store.all("PRAGMA foreign_key_check") == []
    backup = next(tmp_path.glob(f"before-v5-to-v{SCHEMA_VERSION}-*.db"))
    with sqlite3.connect(backup) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 5
        assert db.execute("SELECT content FROM memories").fetchone()[0] == "Preserved content"
        assert (
            db.execute(
                "SELECT name FROM sqlite_master WHERE name='memory_creation_requests'"
            ).fetchone()
            is None
        )
