import copy
import hashlib
import json
import sqlite3
import stat
import zipfile
from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import new_chat, pair, send, wait_run
from fastapi import HTTPException

from dsgpt.history import History
from dsgpt.history_archive import ArchiveError, preview, read_archive
from dsgpt.storage import Store, uid


def exported(source_id="synthetic-chat", body="My orchard marker is SAPPHIRE."):
    return {
        "id": source_id,
        "title": "Synthetic orchard",
        "create_time": 1700000000,
        "update_time": 1700000010,
        "current_node": "answer",
        "mapping": {
            "root": {"id": "root", "parent": None, "message": None},
            "question": {
                "parent": "root",
                "message": {
                    "author": {"role": "user"},
                    "create_time": 1700000001,
                    "content": {"content_type": "text", "parts": [body]},
                },
            },
            "answer": {
                "parent": "question",
                "message": {
                    "author": {"role": "assistant"},
                    "create_time": 1700000002,
                    "content": {"content_type": "text", "parts": ["Recorded 🌲."]},
                },
            },
        },
    }


def archive(tmp_path, records=None, zipped=True, name="export.zip"):
    path = tmp_path / name
    data = json.dumps(records if records is not None else [exported()], ensure_ascii=False).encode()
    if zipped:
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("conversations.json", data)
            z.writestr("user.json", '{"private":"ACCOUNT_SECRET"}')
            z.writestr("chat.html", "<script>never execute</script>")
    else:
        path.write_bytes(data)
    return path, read_archive(path)


def apply(history, value, request_id=None, selected=()):
    return history.apply(value, request_id or uid(), value["archive_sha256"], selected)


def test_archive_preview_branch_and_omissions(tmp_path):
    record = exported()
    record["mapping"]["old-answer"] = {
        "parent": "question",
        "message": {
            "author": {"role": "assistant"},
            "content": {"content_type": "text", "parts": ["old discarded branch"]},
        },
    }
    record["mapping"]["root"]["message"] = {
        "author": {"role": "system"},
        "content": {"content_type": "text", "parts": ["DO EVIL"]},
    }
    record["mapping"]["question"]["message"]["content"]["parts"].append({"image": "not opened"})
    _, value = archive(tmp_path, [record])
    item = value["conversations"][0]
    assert [m["role"] for m in item["messages"]] == ["user", "assistant"]
    assert item["omissions"]["inactive_nodes_omitted"] == 1
    assert item["omissions"]["nonchat_messages_omitted"] == 1
    assert item["omissions"]["unsupported_parts_omitted"] == 1
    assert item["created_at"] == "2023-11-14T22:13:20+00:00"
    result = preview(value)
    assert result["selected_messages"] == 2
    assert "SAPPHIRE" not in json.dumps(result)
    assert "ACCOUNT_SECRET" not in json.dumps(value)
    assert "old discarded" not in json.dumps(value)


def test_numbered_members_and_json_bom(tmp_path):
    p = tmp_path / "numbered.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("folder/conversations-002.json", json.dumps([exported("two")]))
        z.writestr(
            "folder/conversations-001.json", b"\xef\xbb\xbf" + json.dumps([exported()]).encode()
        )
    value = read_archive(p)
    assert [r["source_id"] for r in value["conversations"]] == ["synthetic-chat", "two"]
    assert preview(value, ["two"])["selected_conversations"] == 1
    with pytest.raises(ArchiveError):
        preview(value, ["missing"])
    raw = tmp_path / "conversations.json"
    raw.write_bytes(b"\xef\xbb\xbf" + json.dumps([exported()]).encode())
    assert read_archive(raw)["conversations"][0]["sha256"] == value["conversations"][0]["sha256"]


@pytest.mark.parametrize(
    "kind",
    [
        "cycle",
        "missing_parent",
        "missing_current",
        "ambiguous",
        "bad_date",
        "bool_date",
        "surrogate",
        "nul",
        "parts",
        "role",
        "title",
        "duplicate_id",
        "empty",
        "conflicting_id",
    ],
)
def test_malformed_records_are_rejected_without_partial_import(tmp_path, kind):
    r = exported()
    if kind == "cycle":
        r["mapping"]["root"]["parent"] = "answer"
    elif kind == "missing_parent":
        r["mapping"]["answer"]["parent"] = "absent"
    elif kind == "missing_current":
        r["current_node"] = "absent"
    elif kind == "ambiguous":
        r.pop("current_node")
        r["mapping"]["other"] = {"parent": None, "message": None}
    elif kind == "bad_date":
        r["create_time"] = 1e100
    elif kind == "bool_date":
        r["create_time"] = True
    elif kind in {"surrogate", "nul"}:
        r["title"] = "\ud800" if kind == "surrogate" else "\x00"
    elif kind == "parts":
        r["mapping"]["answer"]["message"]["content"]["parts"] = {}
    elif kind == "role":
        r["mapping"]["answer"]["message"]["author"] = "assistant"
    elif kind == "title":
        r["title"] = "x" * 301
    elif kind == "empty":
        r["mapping"] = {}
    elif kind == "conflicting_id":
        r["conversation_id"] = "different"
    p = tmp_path / "data.json"
    p.write_text(json.dumps([r, r] if kind == "duplicate_id" else [exported("ok"), r]))
    with pytest.raises(ArchiveError):
        read_archive(p)


@pytest.mark.parametrize(
    "kind",
    [
        "traversal",
        "absolute",
        "backslash",
        "symlink",
        "duplicate",
        "mixed",
        "collision",
        "bomb",
        "broken",
        "missing",
    ],
)
def test_zip_rejects_unsafe_or_ambiguous_input(tmp_path, kind):
    p = tmp_path / "bad.zip"
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        if kind != "missing":
            z.writestr("conversations.json", json.dumps([exported()]))
        if kind in {"traversal", "absolute", "backslash"}:
            z.writestr(
                {"traversal": "../evil", "absolute": "/evil", "backslash": "..\\evil"}[kind], "x"
            )
        elif kind == "symlink":
            info = zipfile.ZipInfo("evil")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(info, "outside")
        elif kind == "duplicate":
            z.writestr("CONVERSATIONS.JSON", "[]")
        elif kind == "mixed":
            z.writestr("conversations-001.json", "[]")
        elif kind == "collision":
            z.writestr("folder/conversations.json", "[]")
        elif kind == "bomb":
            z.writestr("folder/conversations-001.json", " " * 500000)
        elif kind == "missing":
            z.writestr("user.json", "[]")
    if kind == "broken":
        p.write_bytes(b"PKbroken")
    with pytest.raises(ArchiveError):
        read_archive(p)
    assert not (tmp_path.parent / "evil").exists()


@pytest.mark.parametrize("raw", [b"{}", b"[", b"[NaN]", b'[{"id":1,"id":2}]', b"[\xff]"])
def test_json_rejects_invalid_data(tmp_path, raw):
    p = tmp_path / "bad.json"
    p.write_bytes(raw)
    with pytest.raises(ArchiveError):
        read_archive(p)


def test_file_and_message_limits_and_missing_dates(tmp_path, monkeypatch):
    from dsgpt import history_archive as reader

    p, value = archive(tmp_path)
    link = tmp_path / "link.zip"
    link.symlink_to(p)
    with pytest.raises(ArchiveError):
        read_archive(link)
    monkeypatch.setattr(reader, "MAX_ARCHIVE_BYTES", 1)
    with pytest.raises(ArchiveError):
        read_archive(p)
    monkeypatch.undo()
    r = exported(body="z" * (reader.MAX_MESSAGE_BYTES + 1))
    with pytest.raises(ArchiveError):
        archive(tmp_path, [r], zipped=False)
    r = exported()
    r.pop("current_node")
    r["create_time"] = None
    r["mapping"]["question"]["message"]["create_time"] = None
    _, value = archive(tmp_path, [r])
    assert value["conversations"][0]["omissions"]["branch_inferred"] == 1
    assert value["conversations"][0]["omissions"]["missing_message_dates"] == 1
    assert value["conversations"][0]["created_at"] is None


def test_atomic_import_retry_versions_search_and_continue(backend, tmp_path):
    _, value = archive(tmp_path)
    h = backend.app.state.history
    request_id = uid()
    first = apply(h, value, request_id)
    assert first == apply(h, value, request_id)
    chat = first["items"][0]["conversation_id"]
    assert apply(h, value)["items"][0]["outcome"] == "duplicate"
    assert backend.store.one("SELECT count(*) AS n FROM conversations")["n"] == 1
    assert backend.store.one("SELECT count(*) AS n FROM runs")["n"] == 0
    provenance = backend.client.get(f"/v1/conversations/{chat}/import").json()
    assert provenance["archive_sha256"] == value["archive_sha256"]
    messages = backend.client.get(f"/v1/conversations/{chat}/messages").json()
    assert [m["ordinal"] for m in messages] == [1, 2]
    assert messages[0]["created_at"] == "2023-11-14T22:13:21+00:00"
    assert (
        backend.client.get("/v1/history/search", params={"q": "SAPPHIRE"}).json()[0][
            "source_node_id"
        ]
        == "question"
    )
    assert backend.client.get("/v1/conversations", params={"q": "SAPPHIRE"}).json()[0]["id"] == chat
    run = send(backend, chat, "What is my orchard marker?").json()
    assert wait_run(backend, run["id"])["status"] == "completed"
    assert any("SAPPHIRE" in m["content"] for m in backend.inference.calls[-1][1])
    changed = copy.deepcopy(value)
    _, changed = archive(tmp_path, [exported(body="A new SAPPHIRE version")])
    with pytest.raises(HTTPException) as exc:
        apply(h, changed, request_id)
    assert exc.value.status_code == 409
    next_chat = apply(h, changed)["items"][0]["conversation_id"]
    assert next_chat != chat
    assert len(backend.client.get(f"/v1/conversations/{chat}/messages").json()) == 4
    assert len(h.list()) == 2
    with pytest.raises(HTTPException):
        h.apply(value, uid(), "0" * 64)


def test_import_is_atomic_and_concurrent_retries_deduplicate(tmp_path):
    store = Store(tmp_path / "data")
    h = History(store)
    _, value = archive(tmp_path, [exported("one"), exported("two")])
    with store.transaction() as db:
        db.execute(
            "CREATE TRIGGER refuse_import BEFORE INSERT ON messages WHEN new.ordinal=2 "
            "BEGIN SELECT RAISE(ABORT,'synthetic failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        apply(h, value)
    assert store.one("SELECT count(*) AS n FROM conversations")["n"] == 0
    assert store.one("SELECT count(*) AS n FROM history_batches")["n"] == 0
    with store.transaction() as db:
        db.execute("DROP TRIGGER refuse_import")
    request_id = uid()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: apply(h, value, request_id), range(4)))
    assert all(r == results[0] for r in results)
    assert store.one("SELECT count(*) AS n FROM messages")["n"] == 4


def test_remove_all_versions_keeps_local_turns_and_never_resurrects(backend, tmp_path):
    h = backend.app.state.history
    _, value = archive(tmp_path)
    request_id = uid()
    chat = apply(h, value, request_id)["items"][0]["conversation_id"]
    _, changed = archive(tmp_path, [exported(body="SAPPHIRE changed source")])
    other = apply(h, changed)["items"][0]["conversation_id"]
    backend.inference.gate.clear()
    run = send(backend, other, "Keep this local follow-up").json()
    with pytest.raises(HTTPException) as exc:
        h.remove(chat)
    assert exc.value.status_code == 409
    backend.inference.gate.set()
    wait_run(backend, run["id"])
    assert h.remove(chat) == h.remove(chat)
    assert h.search("SAPPHIRE") == []
    assert h.provenance(chat)["source_title"] is None
    assert len(backend.client.get(f"/v1/conversations/{other}/messages").json()) == 4
    assert h.search("follow-up")[0]["conversation_id"] == other
    assert apply(h, value, request_id)["items"][0]["removed"] is True
    assert apply(h, value)["items"][0]["outcome"] == "blocked_removed_source"
    _, newest = archive(tmp_path, [exported(body="SAPPHIRE another later export")])
    assert apply(h, newest)["items"][0]["conversation_id"] is None
    restored = History(Store(backend.store.directory))
    assert apply(restored, value, request_id)["items"][0]["removed"] is True
    assert backend.store.one("SELECT count(*) AS n FROM conversations")["n"] == 2


def test_explicit_memory_copy_provenance_scopes_and_receipt(backend, tmp_path):
    _, value = archive(tmp_path)
    h = backend.app.state.history
    chat = apply(h, value)["items"][0]["conversation_id"]
    message = backend.client.get(f"/v1/conversations/{chat}/messages").json()[0]
    assert backend.client.get("/v1/memories").json() == []
    body = {"request_id": uid(), "title": "Orchard preference"}
    url = f"/v1/history/messages/{message['id']}/memory"
    memory = backend.client.post(url, json=body).json()
    assert backend.client.post(url, json=body).json() == memory
    assert (
        json.loads(memory["source"])["sha256"]
        == hashlib.sha256(message["content"].encode()).hexdigest()
    )
    assert len(backend.client.get("/v1/memories").json()) == 1
    assert backend.client.delete(f"/v1/memories/{memory['id']}?revision=1").status_code == 200
    assert backend.client.post(url, json=body).status_code == 409
    phone, _ = pair(backend, ["chat"])
    headers = {"Authorization": "Bearer " + phone["token"]}
    assert (
        backend.client.post(url, headers=headers, json={**body, "task_id": uid()}).status_code
        == 403
    )
    assert backend.client.delete(f"/v1/history/imports/{chat}", headers=headers).status_code == 403
    assert backend.client.get("/v1/history/imports", headers=headers).status_code == 403
    assert (
        backend.client.get(f"/v1/conversations/{chat}/import", headers=headers).status_code == 200
    )
    work, _ = pair(backend, ["work", "models"])
    headers = {"Authorization": "Bearer " + work["token"]}
    assert backend.client.get("/v1/history/search?q=SAPPHIRE", headers=headers).status_code == 403
    assert backend.client.post(url, headers=headers, json=body).status_code == 403
    h.remove(chat)
    assert backend.client.post(url, json={**body, "request_id": uid()}).status_code == 410


def test_index_hidden_scope_escaping_and_streamed_updates(backend):
    chat = new_chat(backend)
    r = send(backend, chat, "Indexed kiwi orchard").json()
    wait_run(backend, r["id"])
    h = backend.app.state.history
    assert h.search("world")[0]["role"] == "assistant"
    assert h.search('kiwi" OR 1=1 --')[0]["conversation_id"] == chat
    with backend.store.transaction() as db:
        db.execute("UPDATE conversations SET hidden=1 WHERE id=?", (chat,))
    assert h.search("kiwi") == []
    assert len(h.search("kiwi", hidden=True)) == 1
    assert h.search("---") == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("recipient", "python"),
        ("channel", "analysis"),
        ("metadata", {"is_visually_hidden_from_conversation": True}),
    ],
)
def test_hidden_reasoning_and_tool_requests_are_not_imported(tmp_path, field, value):
    record = exported()
    record["mapping"]["answer"]["message"][field] = value
    _, parsed = archive(tmp_path, [record])
    item = parsed["conversations"][0]
    assert len(item["messages"]) == 1
    assert item["omissions"]["nonchat_messages_omitted"] == 1


@pytest.mark.parametrize(
    "bound,limit",
    [
        ("MAX_ENTRIES", 1),
        ("MAX_JSON_BYTES", 10),
        ("MAX_CONVERSATIONS", 1),
        ("MAX_NODES", 4),
    ],
)
def test_aggregate_bounds_refuse_the_whole_export(tmp_path, monkeypatch, bound, limit):
    import dsgpt.history_archive as reader

    path, _ = archive(tmp_path, [exported("one"), exported("two")])
    monkeypatch.setattr(reader, bound, limit)
    with pytest.raises(ArchiveError):
        read_archive(path)


def test_memory_promotion_scope_limits_and_transaction_rollback(backend, tmp_path):
    _, value = archive(tmp_path, [exported(body="x" * 8001)])
    h = backend.app.state.history
    chat = apply(h, value)["items"][0]["conversation_id"]
    messages = backend.client.get(f"/v1/conversations/{chat}/messages").json()
    with pytest.raises(HTTPException) as exc:
        h.promote(messages[0]["id"], uid(), "Too long")
    assert exc.value.status_code == 422
    task = backend.client.post(
        "/v1/work/tasks",
        json={
            "title": "Existing project",
            "requirements": "Preserve explicit scope",
        },
    ).json()
    memory_id = uid()
    with backend.store.transaction() as db:
        db.execute(
            "CREATE TRIGGER refuse_memory BEFORE INSERT ON memory_creation_requests "
            "BEGIN SELECT RAISE(ABORT,'test rollback'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        h.promote(messages[1]["id"], memory_id, "Project note", task["id"])
    assert backend.store.all("SELECT * FROM memories") == []
    with backend.store.transaction() as db:
        db.execute("DROP TRIGGER refuse_memory")
    row = h.promote(messages[1]["id"], memory_id, "Project note", task["id"])
    assert row["task_id"] == task["id"]
    assert backend.client.get("/v1/memories").json() == []
    assert backend.client.get("/v1/memories", params={"task_id": task["id"]}).json()[0] == row
    report = backend.client.get("/v1/diagnostics/overview").text
    assert "SAPPHIRE" not in report and "Saved original reply" not in report
