import asyncio
import json
from uuid import uuid4

from test_work_references import create, setup, transition, wait_task


def change(backend, task, action, source="S1", request_id=None):
    body = {
        "action": action,
        "revision": task["revision"],
        "request_id": request_id or str(uuid4()),
    }
    return backend.client.post(
        f"/v1/work/tasks/{task['id']}/sources/{source}/actions", json=body
    ), body


def test_refresh_remove_restore_and_lost_response_replay(backend):
    reader, _ = setup(backend, [{"tool": "blocked", "summary": "Waiting for owner"}])
    task = create(backend)
    transition(backend, task, "start")
    task = wait_task(backend, task["id"], "blocked")
    response, request = change(backend, task, "refresh")
    assert response.status_code == 200
    task = response.json()
    row = backend.store.one("SELECT * FROM work_sources")
    assert row["status"] == "pending" and row["document"] is None and row["generation"] == 2
    assert len(reader.calls) == 1  # Saving a refresh never performs network IO.
    url = f"/v1/work/tasks/{task['id']}/sources/S1/actions"
    assert backend.client.post(url, json=request).json()["revision"] == task["revision"]
    response, _ = change(backend, task, "remove")
    task = response.json()
    assert task["references"]["removed"] == 1
    assert backend.client.post(url, json=request).status_code == 200  # Original accepted request.
    assert backend.store.one("SELECT * FROM work_sources")["status"] == "removed"
    assert backend.client.post(url, json={**request, "action": "remove"}).status_code == 409
    with backend.store.connect() as db:
        assert backend.app.state.work.references.tool_list(db, task["id"], 0)["sources"] == []
        exported = backend.app.state.work.references.export(db, task["id"])
        assert exported[0]["text"] == "" and exported[0]["generation"] == 3
    # Adding the same URL again cannot implicitly restore removed content.
    amended = backend.client.patch(
        f"/v1/work/tasks/{task['id']}",
        json={"revision": task["revision"], "reference_urls": ["https://example.org/reference"]},
    )
    assert amended.status_code == 200
    task = amended.json()
    assert backend.store.one("SELECT status FROM work_sources")["status"] == "removed"
    response, _ = change(backend, task, "refresh")
    task = response.json()
    assert backend.store.one("SELECT * FROM work_sources")["generation"] == 4
    transition(backend, task, "resume")
    wait_task(backend, task["id"], "blocked")
    assert len(reader.calls) == 2
    assert backend.store.one("SELECT * FROM work_sources")["status"] == "retrieved"


def test_stale_revision_and_scope_do_not_mutate(backend):
    setup(backend)
    task = create(backend)
    other = create(backend, ["https://example.org/other"])
    response, _ = change(backend, task, "remove", "S2")
    assert response.status_code == 404
    response, _ = change(backend, task, "refresh")
    assert response.status_code == 200
    assert change(backend, task, "remove")[0].status_code == 409
    assert (
        backend.store.one("SELECT status FROM work_sources WHERE task_id=?", (other["id"],))[
            "status"
        ]
        == "pending"
    )
    assert change(backend, {**task, "id": str(uuid4())}, "remove")[0].status_code == 404


def test_active_task_refuses_changes_completed_only_allows_removal(backend):
    reader, _ = setup(backend)
    reader.gate.clear()
    task = create(backend)
    transition(backend, task, "start")
    assert reader.started.wait(2)
    task = backend.app.state.work.get(task["id"])
    assert change(backend, task, "remove")[0].status_code == 409
    reader.gate.set()
    task = wait_task(backend, task["id"])
    assert change(backend, task, "refresh")[0].status_code == 409
    response, body = change(backend, task, "remove")
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    stored = backend.store.one("SELECT * FROM work_sources")
    assert stored["document"] is None and stored["status"] == "removed"
    read = backend.client.get(f"/v1/work/tasks/{task['id']}/sources/S1").json()
    assert "text" not in read and read["error"] == "source_not_retrieved"
    # Durable receipt remains after reopening the store.
    from dsgpt.storage import Store

    reopened = Store(backend.store.directory)
    assert reopened.one("SELECT definition FROM work_source_requests")["definition"]
    assert (
        backend.client.post(
            f"/v1/work/tasks/{task['id']}/sources/S1/actions", json=body
        ).status_code
        == 200
    )


def test_old_fetch_cannot_commit_after_newer_revision(backend):
    reader, _ = setup(backend)
    work = backend.app.state.work
    task = create(backend)
    source = work.references.pending(task["id"])
    reader.gate.clear()

    async def scenario():
        with backend.store.transaction() as db:
            db.execute("UPDATE work_tasks SET status='queued' WHERE id=?", (task["id"],))
        operation = asyncio.create_task(work._reference_step(task["id"], source))
        while not reader.started.is_set():
            await asyncio.sleep(0.005)
        # Model the pause/new decision/resume boundary while the old reader finishes.
        with backend.store.transaction() as db:
            db.execute(
                "UPDATE work_tasks SET status='paused',revision=revision+1 WHERE id=?",
                (task["id"],),
            )
        paused = work.get(task["id"])
        work.change_source(task["id"], "S1", "remove", paused["revision"], str(uuid4()))
        with backend.store.transaction() as db:
            db.execute(
                "UPDATE work_tasks SET status='running',revision=revision+1 WHERE id=?",
                (task["id"],),
            )
        reader.gate.set()
        await operation

    asyncio.run(scenario())
    assert backend.store.one("SELECT status,document FROM work_sources") == {
        "status": "removed",
        "document": None,
    }
    assert work.get(task["id"])["status"] == "running"


def test_historical_read_result_is_not_reintroduced_after_removal(backend):
    setup(
        backend,
        [
            {"tool": "read_source", "source_id": "S1", "summary": "Read source"},
            {"tool": "blocked", "summary": "Waiting"},
        ],
    )
    task = create(backend)
    transition(backend, task, "start")
    task = wait_task(backend, task["id"], "blocked")
    change(backend, task, "remove")
    work = backend.app.state.work
    row = backend.store.one("SELECT * FROM work_tasks WHERE id=?", (task["id"],))
    session = backend.store.one("SELECT * FROM work_sessions WHERE task_id=?", (task["id"],))
    messages = work._prompt(row, session, work.models["test-na"], memories=[])
    assert "COBALT" not in json.dumps(messages)
    assert "source_snapshot_no_longer_current" in json.dumps(messages)
    assert "COBALT" in backend.store.one("SELECT result FROM work_steps WHERE step=1")["result"]


def test_v13_sources_preserved_with_backup(tmp_path):
    import sqlite3

    from dsgpt.migrations import MIGRATIONS
    from dsgpt.storage import APPLICATION_ID, SCHEMA, SCHEMA_VERSION, Store

    with sqlite3.connect(tmp_path / "dsgpt.db") as db:
        db.executescript(SCHEMA + "\n".join(MIGRATIONS[n] for n in range(2, 14)))
        db.execute(f"PRAGMA application_id={APPLICATION_ID}")
        db.execute("PRAGMA user_version=13")
        db.execute("INSERT INTO work_tasks VALUES('t','Task','Keep','draft',1,'now','now')")
        db.execute(
            "INSERT INTO work_sources VALUES('t','S9','https://example.org','retrieved',?,NULL,'now','now')",
            (json.dumps({"text": "KEPT"}),),
        )
    store = Store(tmp_path)
    row = store.one("SELECT * FROM work_sources")
    assert row["generation"] == 1 and json.loads(row["document"])["text"] == "KEPT"
    assert store.all("SELECT * FROM work_source_requests") == []
    backup = next(tmp_path.glob(f"before-v13-to-v{SCHEMA_VERSION}-*.db"))
    with sqlite3.connect(backup) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 13
        assert db.execute("SELECT source_id FROM work_sources").fetchone()[0] == "S9"


def test_source_management_requires_work_permission(backend):
    from conftest import pair

    setup(backend)
    task = create(backend)
    credential, _ = pair(backend, ["chat"])
    headers = {"Authorization": "Bearer " + credential["token"]}
    response = backend.client.post(
        f"/v1/work/tasks/{task['id']}/sources/S1/actions",
        headers=headers,
        json={"action": "remove", "revision": task["revision"], "request_id": str(uuid4())},
    )
    assert response.status_code == 403
    assert backend.store.one("SELECT status FROM work_sources")["status"] == "pending"
