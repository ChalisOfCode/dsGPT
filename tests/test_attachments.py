import hashlib
import json
import sqlite3
from uuid import uuid4

import pytest
from conftest import new_chat, pair, send, wait_run

from dsgpt.attachments import MAX_FILE_BYTES, MAX_MESSAGE_BYTES, Attachments, prepare
from dsgpt.migrations import MIGRATIONS
from dsgpt.storage import APPLICATION_ID, SCHEMA, SCHEMA_VERSION, Store, canonical


def submit(backend, chat, files, identifier=None, **extra):
    return backend.client.post(
        f"/v1/conversations/{chat}/messages",
        json={
            "request_id": identifier or str(uuid4()),
            "content": "Explain the attached marker",
            "model_id": "test-na",
            "attachments": files,
            **extra,
        },
    )


def records(backend, chat):
    return backend.client.get(f"/v1/conversations/{chat}/messages").json()


def path(chat, attachment):
    return f"/v1/conversations/{chat}/attachments/{attachment}"


def test_attachment_retry_is_atomic_local_and_preserves_original_utf8_bytes(backend):
    chat = new_chat(backend)
    text = "\ufeffMarker COBALT\r\n<svg onload=alert(1)> é\n"
    files = [{"name": "notes.txt", "text": text}]
    identifier = str(uuid4())
    first = submit(backend, chat, files, identifier)
    assert first.status_code == 202
    wait_run(backend, identifier)
    before = records(backend, chat)
    assert submit(backend, chat, files, identifier).json()["id"] == identifier
    assert records(backend, chat) == before
    user, assistant = before
    assert assistant["attachments"] == [] and user["content"] == "Explain the attached marker"
    meta = user["attachments"][0]
    assert "text" not in meta and meta["bytes"] == len(text.encode())
    assert meta["sha256"] == hashlib.sha256(text.encode()).hexdigest()
    endpoint = path(chat, meta["id"])
    assert backend.client.get(endpoint).json()["text"] == text
    downloaded = backend.client.get(endpoint + "/download")
    assert (
        downloaded.content == text.encode()
        and downloaded.headers["content-type"] == "application/octet-stream"
    )
    assert downloaded.headers["content-disposition"].startswith("attachment;")
    context = backend.inference.calls[0][1][-1]["content"]
    assert "untrusted reference data" in context and "COBALT" in context
    assert meta["sha256"] in context
    assert (
        submit(backend, chat, [{"name": "notes.txt", "text": "changed"}], identifier).status_code
        == 409
    )
    assert len(backend.store.all("SELECT * FROM message_attachments")) == 1


@pytest.mark.parametrize(
    "name",
    [
        "../x.txt",
        "dir/x.py",
        "dir\\x.py",
        "C:x.txt",
        "x.exe",
        "x.pdf",
        "CON.txt",
        "lpt1.py",
        "x.txt ",
        "x.txt.",
        "a\n.txt",
        ".txt",
    ],
)
def test_attachment_names_and_unsupported_formats_are_rejected(backend, name):
    chat = new_chat(backend)
    assert submit(backend, chat, [{"name": name, "text": "content"}]).status_code == 422
    assert records(backend, chat) == []


@pytest.mark.parametrize("text", ["NUL\x00data", "escape\x1b[31m", "\ud800"])
def test_attachment_binary_controls_and_invalid_unicode_are_rejected(backend, text):
    chat = new_chat(backend)
    body = {
        "request_id": str(uuid4()),
        "content": "Read",
        "model_id": "test-na",
        "attachments": [{"name": "file.txt", "text": text}],
    }
    result = backend.client.post(
        f"/v1/conversations/{chat}/messages",
        content=json.dumps(body),
        headers={"Content-Type": "application/json"},
    )
    assert result.status_code == 422 and records(backend, chat) == []


def test_attachment_limits_count_utf8_bytes_and_enforce_aggregate(backend):
    chat = new_chat(backend)
    assert (
        submit(
            backend, chat, [{"name": "file.txt", "text": "é" * (MAX_FILE_BYTES // 2 + 1)}]
        ).status_code
        == 413
    )
    assert (
        submit(
            backend, chat, [{"name": f"{i}.txt", "text": "a" * MAX_FILE_BYTES} for i in range(3)]
        ).status_code
        == 413
    )
    assert (
        submit(backend, chat, [{"name": f"{i}.txt", "text": ""} for i in range(5)]).status_code
        == 422
    )
    assert records(backend, chat) == []
    assert (
        sum(
            f["bytes"]
            for f in prepare(
                [{"name": f"{i}.txt", "text": "é" * (MAX_FILE_BYTES // 2)} for i in range(2)]
            )
        )
        == MAX_MESSAGE_BYTES
    )


def test_scope_cross_conversation_and_chunk_boundaries(backend):
    chat, other = new_chat(backend), new_chat(backend)
    text = "é" * 4000
    run = submit(backend, chat, [{"name": "unicode.txt", "text": text}]).json()
    wait_run(backend, run["id"])
    meta = records(backend, chat)[0]["attachments"][0]
    endpoint = path(chat, meta["id"])
    chunks, offset = [], 0
    while True:
        page = backend.client.get(endpoint, params={"offset": offset}).json()
        assert len(page["text"].encode()) <= 3000
        chunks.append(page["text"])
        offset = page["next_offset"]
        if offset is None:
            break
    assert "".join(chunks) == text
    assert backend.client.get(endpoint, params={"offset": 10000}).json()["text"] == ""
    assert backend.client.get(endpoint, params={"offset": -1}).status_code == 422
    for suffix in ["", "/download"]:
        assert backend.client.get(path(other, meta["id"]) + suffix).status_code == 404
    assert backend.client.delete(path(other, meta["id"])).status_code == 404
    for scopes in [["work"], ["models"]]:
        phone, _ = pair(backend, scopes)
        headers = {"Authorization": "Bearer " + phone["token"]}
        assert backend.client.get(endpoint, headers=headers).status_code == 403
        assert backend.client.get(endpoint + "/download", headers=headers).status_code == 403
        assert backend.client.delete(endpoint, headers=headers).status_code == 403
    phone, _ = pair(backend, ["chat"])
    assert (
        backend.client.get(
            endpoint, headers={"Authorization": "Bearer " + phone["token"]}
        ).status_code
        == 200
    )


def test_attachment_removal_blocks_active_reply_and_retries_never_resurrect(backend):
    chat = new_chat(backend)
    files = [{"name": "secret.txt", "text": "PRIVATE_MARKER"}]
    identifier = str(uuid4())
    backend.inference.gate.clear()
    run = submit(backend, chat, files, identifier).json()
    assert backend.inference.started.wait(3)
    meta = records(backend, chat)[0]["attachments"][0]
    endpoint = path(chat, meta["id"])
    assert backend.client.delete(endpoint).status_code == 409
    backend.inference.gate.set()
    wait_run(backend, run["id"])
    assert backend.client.delete(endpoint).status_code == 200
    assert backend.client.delete(endpoint).status_code == 200
    assert backend.client.get(endpoint).status_code == 410
    assert backend.client.get(endpoint + "/download").status_code == 410
    assert submit(backend, chat, files, identifier).status_code == 202
    assert records(backend, chat)[0]["attachments"][0]["removed"] is True
    assert backend.store.one("SELECT text FROM message_attachments")["text"] is None
    later = send(backend, chat, "What remains?").json()
    wait_run(backend, later["id"])
    context = canonical(backend.inference.calls[-1][1])
    assert "PRIVATE_MARKER" not in context and "removed" in context


def test_attachment_insert_failure_rolls_back_message_run_and_all_files(backend, monkeypatch):
    chat = new_chat(backend)
    original = backend.app.state.runs.attachments.insert

    def broken(db, message_id, values):
        original(db, message_id, values)
        raise RuntimeError("injected transaction failure")

    monkeypatch.setattr(backend.app.state.runs.attachments, "insert", broken)
    with pytest.raises(RuntimeError):
        submit(backend, chat, [{"name": "a.txt", "text": "A"}, {"name": "b.txt", "text": "B"}])
    assert records(backend, chat) == []
    assert backend.store.all("SELECT * FROM runs") == []
    assert backend.store.all("SELECT * FROM message_attachments") == []


def test_ordinary_legacy_retry_and_research_separation(backend):
    chat = new_chat(backend)
    identifier = str(uuid4())
    body = {"request_id": identifier, "content": "Legacy", "model_id": "test-na"}
    endpoint = f"/v1/conversations/{chat}/messages"
    assert backend.client.post(endpoint, json=body).status_code == 202
    wait_run(backend, identifier)
    assert backend.client.post(endpoint, json={**body, "attachments": []}).status_code == 202
    assert (
        submit(
            backend,
            chat,
            [{"name": "private.txt", "text": "Never query this"}],
            research={"search": False, "urls": ["https://example.org"]},
        ).status_code
        == 422
    )
    assert len(records(backend, chat)) == 2
    assert len(backend.inference.calls) == 1


def test_latest_file_is_whole_and_old_attachment_context_is_bounded(backend):
    chat = new_chat(backend)
    first = submit(backend, chat, [{"name": "old.txt", "text": "OLD_MARKER" * 300}]).json()
    wait_run(backend, first["id"])
    later = submit(backend, chat, [{"name": "new.txt", "text": "NEW_MARKER" * 500}]).json()
    wait_run(backend, later["id"])
    assert "OLD_MARKER" not in canonical(backend.inference.calls[-1][1])
    assert "NEW_MARKER" * 500 in backend.inference.calls[-1][1][-1]["content"]
    event = backend.store.one(
        "SELECT payload FROM events WHERE run_id=? AND kind='retrieval'", (later["id"],)
    )
    assert json.loads(event["payload"])["omitted_messages"] == 2


def test_schema8_backup_preserves_search_and_message_state(tmp_path):
    with sqlite3.connect(tmp_path / "dsgpt.db") as db:
        db.executescript(SCHEMA + "".join(MIGRATIONS[v] for v in range(2, 9)))
        db.execute(f"PRAGMA application_id={APPLICATION_ID}")
        db.execute("PRAGMA user_version=8")
        db.execute("UPDATE search_settings SET origin='http://127.0.0.1:8888',revision=2")
        db.execute(
            "INSERT INTO conversations(id,title,created_at,updated_at) "
            "VALUES('chat','Keep','now','now')"
        )
        db.execute(
            "INSERT INTO messages VALUES"
            "('message','chat','user','Keep content','completed',1,'now')"
        )
    store = Store(tmp_path)
    assert store.one("PRAGMA user_version")["user_version"] == SCHEMA_VERSION
    assert store.one("SELECT revision FROM search_settings")["revision"] == 2
    assert store.one("SELECT content FROM messages")["content"] == "Keep content"
    assert Attachments(store).metadata(store.all("SELECT * FROM messages"))[0]["attachments"] == []
    with sqlite3.connect(next(tmp_path.glob(f"before-v8-to-v{SCHEMA_VERSION}-*.db"))) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 8
        assert not db.execute(
            "SELECT name FROM sqlite_master WHERE name='message_attachments'"
        ).fetchall()


async def test_oversized_attachment_context_fails_runtime_before_generation(backend):
    import httpx
    from test_inference import ollama_handler, ollama_model

    from dsgpt.inference import InferenceError, LocalInference

    chat = new_chat(backend)
    run = submit(backend, chat, [{"name": "large.txt", "text": "Z" * 9000}]).json()
    wait_run(backend, run["id"])
    rows = backend.store.all(
        "SELECT id,role,content FROM messages WHERE conversation_id=? ORDER BY ordinal", (chat,)
    )
    expanded, _ = Attachments(backend.store).context(rows[:1], ollama_model())
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return ollama_handler(request)

    adapter = LocalInference(httpx.MockTransport(handler))
    with pytest.raises(InferenceError, match="context_exceeded"):
        _ = [event async for event in adapter.stream(ollama_model(), expanded)]
    assert "/api/chat" not in calls and "Z" * 9000 in expanded[0]["content"]


def test_private_file_body_is_absent_from_diagnostics_and_public_research_prompts(backend):
    from test_research import Answer, Reader

    chat = new_chat(backend)
    marker = "TOP_SECRET_ATTACHMENT_SCOPE"
    first = submit(backend, chat, [{"name": "private-notes.txt", "text": marker}]).json()
    wait_run(backend, first["id"])
    exported = backend.client.post("/v1/diagnostics/exports/preview", json={}).json()
    assert marker not in canonical(exported) and "private-notes.txt" not in canonical(exported)
    observed = []
    delegate = Answer()

    class Spy:
        async def stream(self, model, messages, response_schema=None):
            observed.append(canonical(messages))
            async for event in delegate.stream(model, messages, response_schema=response_schema):
                yield event

    backend.app.state.research.inference = Spy()
    backend.app.state.research.reader = Reader()
    later = backend.client.post(
        f"/v1/conversations/{chat}/messages",
        json={
            "request_id": str(uuid4()),
            "content": "What do the public sources say?",
            "model_id": "test-na",
            "research": {"search": False, "urls": ["https://example.org/docs"]},
        },
    )
    assert later.status_code == 202
    assert wait_run(backend, later.json()["id"])["status"] == "completed"
    assert observed and all(
        marker not in prompt and "private-notes.txt" not in prompt for prompt in observed
    )
