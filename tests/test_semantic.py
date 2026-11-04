import asyncio
import json
import sqlite3
import struct
import threading
import time

import pytest
from conftest import new_chat, pair, send, wait_run
from fastapi import HTTPException

from dsgpt.downloads import DownloadManager
from dsgpt.embeddings import ASSET_IDS, EmbeddingError, verified_bytes
from dsgpt.memory import Memory
from dsgpt.semantic import SemanticIndex
from dsgpt.storage import APPLICATION_ID, SCHEMA, SCHEMA_VERSION, Store, uid

VECTOR = struct.pack("<384f", 1, *([0] * 383))


class FixtureEmbedder:
    """Only a boundary/recovery fixture; semantic quality uses the actual ONNX model."""

    def __init__(self, downloads):
        self.documents = []
        self.gate = None
        self.entered = threading.Event()

    def document(self, text):
        self.documents.append(text)
        self.entered.set()
        if self.gate:
            assert self.gate.wait(5)
        return [(0, len(text), VECTOR)], 0

    def query(self, text):
        return VECTOR


@pytest.fixture
def index(tmp_path):
    store = Store(tmp_path)
    memory = Memory(store)
    semantic = SemanticIndex(store, DownloadManager(store), FixtureEmbedder)
    memory.semantic = semantic
    return semantic, memory


def history_message(store, content="Private imported material", hidden=0):
    chat, message = uid(), uid()
    with store.transaction() as db:
        db.execute(
            "INSERT INTO conversations(id,title,hidden,created_at,updated_at) VALUES(?,?,?,?,?)",
            (chat, "Prior discussion", hidden, "now", "now"),
        )
        db.execute(
            "INSERT INTO messages VALUES(?,?,?,?,?,?,?)",
            (message, chat, "user", content, "completed", 1, "now"),
        )
    return chat, message


async def drain(semantic):
    for _ in range(30):
        if not await semantic.process_one():
            return
    raise AssertionError("Index did not drain")


async def test_disabled_default_scope_and_explicit_history(index):
    semantic, memory = index
    row = memory.create("Meal", "I eat lentils")
    _, message = history_message(semantic.store)
    assert not await semantic.process_one()
    with pytest.raises(HTTPException) as error:
        await semantic.search("dinner")
    assert error.value.status_code == 409
    await semantic.configure(0, True, False)
    await drain(semantic)
    assert (await semantic.search("dinner"))["results"][0]["id"] == row["id"]
    assert not semantic.store.one("SELECT 1 FROM semantic_chunks WHERE source_id=?", (message,))
    with pytest.raises(HTTPException):
        await semantic.search("old", "history")
    await semantic.configure(1, True, True)
    await drain(semantic)
    assert (await semantic.search("old", "history"))["results"][0]["id"] == message
    assert semantic.status()["automatic_history_context"] is False


async def test_memory_update_delete_and_transaction_rollback(index):
    semantic, memory = index
    row = memory.create("Old", "old data")
    await semantic.configure(0, True, False)
    await drain(semantic)
    assert await memory.aretrieve("unrelated paraphrase")
    with pytest.raises(RuntimeError), semantic.store.transaction() as db:
        db.execute("DELETE FROM memories WHERE id=?", (row["id"],))
        raise RuntimeError("rollback")
    assert len((await semantic.search("anything"))["results"]) == 1
    memory.update(row["id"], 1, "Updated", "new data")
    assert (await semantic.search("anything"))["results"] == []
    await drain(semantic)
    result = (await semantic.search("anything"))["results"][0]
    assert result["revision"] == 2 and result["content"] == "Updated\nnew data"
    memory.delete(row["id"], 2)
    assert (await semantic.search("anything"))["results"] == []
    assert not semantic.store.all("SELECT * FROM semantic_jobs")


async def test_hidden_and_cleared_history_never_return_stale_content(index):
    semantic, _ = index
    chat, message = history_message(semantic.store)
    await semantic.configure(0, True, True)
    await drain(semantic)
    with semantic.store.transaction() as db:
        db.execute("UPDATE conversations SET hidden=1 WHERE id=?", (chat,))
    assert not (await semantic.search("old", "history"))["results"]
    assert (await semantic.search("old", "history", hidden=True))["results"][0]["id"] == message
    with semantic.store.transaction() as db:
        db.execute("UPDATE messages SET content='' WHERE id=?", (message,))
    assert not (await semantic.search("old", "history", hidden=True))["results"]
    assert not semantic.store.all("SELECT * FROM semantic_chunks")
    assert not semantic.store.all("SELECT * FROM semantic_jobs")


async def test_edit_during_indexing_cannot_commit_old_embedding(index):
    semantic, memory = index
    row = memory.create("Before", "old content")
    await semantic.configure(0, True, False)
    engine = semantic.engine
    engine.gate = threading.Event()
    operation = asyncio.create_task(semantic.process_one())
    assert await asyncio.to_thread(engine.entered.wait, 3)
    memory.update(row["id"], 1, "After", "replacement")
    engine.gate.set()
    await operation
    assert not semantic.store.all("SELECT * FROM semantic_chunks")
    await drain(semantic)
    assert "replacement" in (await semantic.search("q"))["results"][0]["content"]


async def test_delete_during_search_filters_already_ranked_results(index, monkeypatch):
    semantic, memory = index
    row = memory.create("Secret", "erase this")
    await semantic.configure(0, True, False)
    await drain(semantic)
    original = semantic._rank

    def rank_and_delete(*args):
        ranked = original(*args)
        memory.delete(row["id"], 1)
        return ranked

    monkeypatch.setattr(semantic, "_rank", rank_and_delete)
    assert not (await semantic.search("q"))["results"]


async def test_cancellation_holds_native_grant_until_work_finishes(index):
    semantic, memory = index
    memory.create("One", "one")
    await semantic.configure(0, True, False)
    engine = semantic.engine
    engine.gate = threading.Event()
    operation = asyncio.create_task(semantic.process_one())
    assert await asyncio.to_thread(engine.entered.wait, 3)
    operation.cancel()
    await asyncio.sleep(0.01)
    assert semantic.compute_lock.locked()
    assert set(ASSET_IDS) <= semantic.downloads.busy_assets
    assert not operation.done()
    engine.gate.set()
    with pytest.raises(asyncio.CancelledError):
        await operation
    assert not semantic.compute_lock.locked()
    assert not semantic.downloads.busy_assets
    assert not semantic.store.all("SELECT * FROM semantic_chunks")
    await drain(semantic)
    assert semantic.store.all("SELECT * FROM semantic_chunks")


async def test_disable_purges_vectors_and_restart_resumes_queue(index):
    semantic, memory = index
    first = memory.create("First", "one")
    await semantic.configure(0, True, False)
    await drain(semantic)
    second = memory.create("Second", "two")
    restarted = SemanticIndex(Store(semantic.store.directory), semantic.downloads, FixtureEmbedder)
    assert restarted.engine is None
    await drain(restarted)
    assert {r["id"] for r in (await restarted.search("q"))["results"]} == {
        first["id"],
        second["id"],
    }
    await restarted.configure(1, False, False)
    assert restarted.engine is None
    assert not restarted.store.all("SELECT * FROM semantic_chunks")
    with pytest.raises(HTTPException):
        await restarted.configure(1, True, False)


async def test_capacity_failure_is_explicit_and_retryable(index, monkeypatch):
    import dsgpt.semantic

    semantic, memory = index
    memory.create("One", "one")
    await semantic.configure(0, True, False)
    monkeypatch.setattr(dsgpt.semantic, "MAX_INDEX_CHUNKS", 0)
    await drain(semantic)
    assert (
        semantic.store.one("SELECT error_code FROM semantic_jobs")["error_code"] == "index_capacity"
    )
    monkeypatch.setattr(dsgpt.semantic, "MAX_INDEX_CHUNKS", 100)
    await semantic.configure(1, True, False)
    await drain(semantic)
    assert (await semantic.search("q"))["results"]


def test_asset_activation_requires_verified_owned_files(index):
    semantic, _ = index
    with pytest.raises(EmbeddingError, match="embedding_assets_required"):
        verified_bytes(semantic.downloads, ASSET_IDS[0])
    row = semantic.downloads.submit(ASSET_IDS[0])
    semantic.downloads.update(row["id"], "downloaded", 1)
    path = semantic.downloads.paths(semantic.downloads.catalog[ASSET_IDS[0]])[1]
    path.write_bytes(b"corrupt model")
    with pytest.raises(EmbeddingError, match="embedding_integrity_failed"):
        verified_bytes(semantic.downloads, ASSET_IDS[0])


def test_api_owner_configuration_and_personal_project_permissions(backend):
    backend.app.state.semantic.factory = FixtureEmbedder
    c = backend.client
    task = c.post("/v1/work/tasks", json={"title": "Project", "requirements": "Build"}).json()
    personal = c.post("/v1/memories", json={"title": "Personal", "content": "one"}).json()
    project = c.post(
        "/v1/memories",
        json={
            "title": "Project",
            "content": "two",
            "task_id": task["id"],
        },
    ).json()
    chat_token, _ = pair(backend, ["chat"])
    work_token, _ = pair(backend, ["work"])
    chat_headers = {"Authorization": "Bearer " + chat_token["token"]}
    work_headers = {"Authorization": "Bearer " + work_token["token"]}
    config = {"revision": 0, "enabled": True, "history_enabled": True}
    assert c.patch("/v1/retrieval/settings", json=config, headers=chat_headers).status_code == 403
    assert c.get("/v1/retrieval/settings", headers=work_headers).status_code == 403
    assert c.patch("/v1/retrieval/settings", json=config).status_code == 200
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if backend.store.one("SELECT count(*) AS n FROM semantic_chunks")["n"] == 2:
            break
        time.sleep(0.01)
    assert c.patch("/v1/retrieval/settings", json=config).status_code == 409
    q = {"query": "unmatched"}
    assert (
        c.post("/v1/retrieval/search", json=q, headers=chat_headers).json()["results"][0]["id"]
        == personal["id"]
    )
    assert c.post("/v1/retrieval/search", json=q, headers=work_headers).status_code == 403
    q["task_id"] = task["id"]
    assert c.post("/v1/retrieval/search", json=q, headers=chat_headers).status_code == 403
    assert (
        c.post("/v1/retrieval/search", json=q, headers=work_headers).json()["results"][0]["id"]
        == project["id"]
    )
    assert (
        c.post(
            "/v1/retrieval/search", json={"query": "old", "kind": "history"}, headers=work_headers
        ).status_code
        == 403
    )
    run = send(backend, new_chat(backend), "unmatched").json()
    assert wait_run(backend, run["id"])["status"] == "completed"
    context = json.dumps(backend.inference.calls[-1][1])
    assert personal["id"] in context and project["id"] not in context


def test_v10_migration_queues_existing_records_with_backup(tmp_path):
    from dsgpt.migrations import MIGRATIONS

    path = tmp_path / "data"
    path.mkdir()
    with sqlite3.connect(path / "dsgpt.db") as db:
        db.executescript(SCHEMA + "\n".join(MIGRATIONS[n] for n in range(2, 11)))
        db.execute(f"PRAGMA application_id={APPLICATION_ID}")
        db.execute("PRAGMA user_version=10")
        db.execute("INSERT INTO memories VALUES('old',NULL,'Old','retained','user',1,'now','now')")
    store = Store(path)
    assert store.one("SELECT source_id FROM semantic_jobs")["source_id"] == "old"
    assert store.one("SELECT content FROM memories")["content"] == "retained"
    assert len(list(path.glob(f"before-v10-to-v{SCHEMA_VERSION}-*.db"))) == 1
    assert store.one("PRAGMA quick_check")["quick_check"] == "ok"
