# ruff: noqa: F811
# Pytest imports the shared index fixture by name.
import sqlite3

import pytest
from fastapi import HTTPException
from test_semantic import VECTOR, FixtureEmbedder, drain, history_message, index  # noqa: F401

from dsgpt.attachments import Attachments, prepare
from dsgpt.migrations import MIGRATIONS
from dsgpt.storage import APPLICATION_ID, SCHEMA, SCHEMA_VERSION, Store


def attach(semantic, hidden=0):
    chat, message = history_message(semantic.store, hidden=hidden)
    with semantic.store.transaction() as db:
        Attachments(semantic.store).insert(
            db, message, prepare([{"name": "private.txt", "text": "Orchid evidence"}])
        )
    return chat, semantic.store.one("SELECT id FROM message_attachments ORDER BY rowid DESC")["id"]


async def test_attachment_opt_in_scopes_removal_and_coverage(index):
    semantic, _ = index
    chat, identifier = attach(semantic)
    _, hidden = attach(semantic, 1)
    await semantic.configure(0, True, False)
    await drain(semantic)
    with pytest.raises(HTTPException):
        await semantic.search("flower", "attachment")
    await semantic.configure(1, True, False, True)
    await drain(semantic)
    response = await semantic.search("flower", "attachment")
    assert [r["id"] for r in response["results"]] == [identifier]
    assert response["results"][0]["conversation_id"] == chat
    assert response["results"][0]["name"] == "private.txt"
    assert len((await semantic.search("flower", "attachment", hidden=True))["results"]) == 2
    Attachments(semantic.store).remove(chat, identifier)
    assert not (await semantic.search("flower", "attachment"))["results"]
    assert not semantic.store.one("SELECT 1 FROM semantic_jobs WHERE source_id=?", (identifier,))
    await semantic.configure(2, True, False, False)
    assert not semantic.store.one("SELECT 1 FROM semantic_chunks WHERE kind='attachment'")


async def test_attachment_removed_during_index_or_query_cannot_escape(index, monkeypatch):
    semantic, _ = index
    chat, identifier = attach(semantic)
    await semantic.configure(0, True, False, True)
    original = semantic._engine().document

    def deleting(text):
        result = original(text)
        Attachments(semantic.store).remove(chat, identifier)
        return result

    monkeypatch.setattr(semantic.engine, "document", deleting)
    await drain(semantic)
    assert not (await semantic.search("flower", "attachment"))["results"]
    monkeypatch.setattr(semantic.engine, "document", original)
    chat, identifier = attach(semantic)
    await drain(semantic)
    rank = semantic._rank

    def remove_after_rank(*args):
        result = rank(*args)
        Attachments(semantic.store).remove(chat, identifier)
        return result

    monkeypatch.setattr(semantic, "_rank", remove_after_rank)
    assert not (await semantic.search("flower", "attachment"))["results"]


def test_schema15_upgrade_preserves_existing_vectors(tmp_path):
    with sqlite3.connect(tmp_path / "dsgpt.db") as db:
        db.executescript(SCHEMA + "".join(MIGRATIONS[v] for v in range(2, 16)))
        db.execute(f"PRAGMA application_id={APPLICATION_ID}")
        db.execute("PRAGMA user_version=15")
        db.execute("INSERT INTO semantic_jobs VALUES('memory','old',7,'indexed',0,NULL)")
        db.execute("INSERT INTO semantic_chunks VALUES('memory','old',0,7,0,3,?)", (VECTOR,))
    store = Store(tmp_path)
    assert store.one("PRAGMA user_version")["user_version"] == SCHEMA_VERSION
    assert store.one("SELECT vector,generation FROM semantic_chunks") == {
        "vector": VECTOR,
        "generation": 7,
    }
    assert next(tmp_path.glob(f"before-v15-to-v{SCHEMA_VERSION}-*.db"))
