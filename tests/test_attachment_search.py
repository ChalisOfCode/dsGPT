import sqlite3
from uuid import uuid4

import pytest
from conftest import new_chat, pair, wait_run
from test_attachments import path, records, submit
from test_documents import document, item

from dsgpt.attachments import Attachments
from dsgpt.migrations import MIGRATIONS
from dsgpt.storage import APPLICATION_ID, SCHEMA, SCHEMA_VERSION, Store


def search(backend, q, **params):
    response = backend.client.get("/v1/attachments/search", params={"q": q, **params})
    assert response.status_code == 200, response.text
    return response.json()


def test_search_filename_body_scope_removal_and_retry(backend):
    chat, other = new_chat(backend), new_chat(backend)
    files = [{"name": "cobalt.txt", "text": "Private saffron reference"}]
    run = submit(backend, chat, files).json()
    wait_run(backend, run["id"])
    meta = records(backend, chat)[0]["attachments"][0]
    found = search(backend, "saffron")
    assert len(found) == 1 and found[0]["id"] == meta["id"]
    assert found[0]["kind"] == "attachment" and found[0]["conversation_id"] == chat
    assert "text" not in found[0] and "original" not in found[0]
    assert search(backend, "cobalt") == found
    assert search(backend, "saffron", conversation_id=other) == []
    assert search(backend, "saffron", conversation_id=chat) == found
    assert search(backend, "saffron", hidden=True) == []
    with backend.store.transaction() as db:
        db.execute("UPDATE conversations SET hidden=1 WHERE id=?", (chat,))
    assert search(backend, "saffron") == []
    assert search(backend, "saffron", hidden=True) == found
    assert backend.client.delete(path(chat, meta["id"])).status_code == 200
    assert search(backend, "saffron", hidden=True) == []
    assert search(backend, "cobalt", hidden=True) == []
    assert submit(backend, chat, files, run["id"]).status_code == 202
    assert search(backend, "saffron", hidden=True) == []
    assert (
        backend.store.all("SELECT rowid FROM attachments_fts WHERE attachments_fts MATCH 'saffron'")
        == []
    )


def test_docx_search_extract_only_and_original_download(backend):
    chat = new_chat(backend)
    raw = document(extras={"docProps/core.xml": "<secret>ZIPMETADATASECRET</secret>"})
    run = submit(backend, chat, [item(raw)]).json()
    wait_run(backend, run["id"])
    found = search(backend, "COBALT")
    assert len(found) == 1 and found[0]["document"]["format"] == "docx"
    assert found[0]["bytes"] == len(raw)
    assert search(backend, "ZIPMETADATASECRET") == []
    assert backend.client.get(path(chat, found[0]["id"]) + "/download").content == raw
    assert len(backend.inference.calls) == 1  # Search never invokes inference.


def test_search_limits_literal_operators_and_permissions(backend):
    chat = new_chat(backend)
    run = submit(backend, chat, [{"name": "huge.txt", "text": "saffron " + "z" * 60000}]).json()
    wait_run(backend, run["id"])
    assert len(search(backend, "saffron")[0]["excerpt"]) <= 800
    assert len(search(backend, '"saffron" OR name:* NOT "missing"')) == 1
    assert search(backend, '* : "') == []
    assert search(backend, "saffron", offset=1) == []
    for params in [
        {"limit": 51},
        {"limit": 0},
        {"offset": -1},
        {"offset": 10001},
        {"conversation_id": "bad"},
        {"q": "a" * 1001},
    ]:
        assert (
            backend.client.get(
                "/v1/attachments/search", params={"q": "saffron", **params}
            ).status_code
            == 422
        )
    for scopes, status in [(["work"], 403), (["models"], 403), (["chat"], 200)]:
        phone, _ = pair(backend, scopes)
        assert (
            backend.client.get(
                "/v1/attachments/search?q=saffron",
                headers={"Authorization": "Bearer " + phone["token"]},
            ).status_code
            == status
        )
    assert backend.client.get("/v1/capabilities").json()["attachments"]["keyword_search"] is True


def test_index_update_delete_and_transaction_rollback(backend):
    chat = new_chat(backend)
    run = submit(backend, chat, [{"name": "before.txt", "text": "saffron"}]).json()
    wait_run(backend, run["id"])
    meta = records(backend, chat)[0]["attachments"][0]
    with pytest.raises(RuntimeError):
        with backend.store.transaction() as db:
            db.execute("UPDATE message_attachments SET text='cobalt' WHERE id=?", (meta["id"],))
            raise RuntimeError("rollback")
    assert search(backend, "saffron") and not search(backend, "cobalt")
    with backend.store.transaction() as db:
        db.execute(
            "UPDATE message_attachments SET name='after.txt',text='cobalt' WHERE id=?",
            (meta["id"],),
        )
    assert not search(backend, "saffron") and not search(backend, "before")
    assert search(backend, "cobalt") and search(backend, "after")
    with backend.store.transaction() as db:
        db.execute("DELETE FROM message_attachments WHERE id=?", (meta["id"],))
    assert not search(backend, "cobalt")


def test_schema14_upgrade_indexes_existing_text_and_preserves_original(tmp_path):
    attachment = str(uuid4())
    raw = document()
    with sqlite3.connect(tmp_path / "dsgpt.db") as db:
        db.executescript(SCHEMA + "".join(MIGRATIONS[v] for v in range(2, 15)))
        db.execute(f"PRAGMA application_id={APPLICATION_ID}")
        db.execute("PRAGMA user_version=14")
        db.execute(
            "INSERT INTO conversations(id,title,created_at,updated_at) "
            "VALUES('chat','Keep','now','now')"
        )
        db.execute(
            "INSERT INTO messages VALUES('msg','chat','user','Original','completed',1,'now')"
        )
        db.execute(
            "INSERT INTO message_attachments "
            "VALUES(?,'msg','old.docx','saffron',12,'hash','now',0)",
            (attachment,),
        )
        db.execute(
            "INSERT INTO attachment_documents VALUES(?,?,?)", (attachment, raw, '{"format":"docx"}')
        )
    store = Store(tmp_path)
    assert store.one("PRAGMA user_version")["user_version"] == SCHEMA_VERSION
    found = Attachments(store).search("saffron")
    assert len(found) == 1 and found[0]["id"] == attachment
    assert Attachments(store).get("chat", attachment)["original"] == raw
    with sqlite3.connect(next(tmp_path.glob(f"before-v14-to-v{SCHEMA_VERSION}-*.db"))) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 14
        assert db.execute("SELECT original FROM attachment_documents").fetchone()[0] == raw
