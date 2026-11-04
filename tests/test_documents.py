import base64
import hashlib
import io
import zipfile

import pytest
from conftest import new_chat, wait_run
from fastapi import HTTPException
from test_attachments import path, records, submit

from dsgpt.documents import extract_docx, xml


def document(body="<w:p><w:r><w:t>PRIVATE COBALT</w:t></w:r></w:p>", extras=None):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "[Content_Types].xml",
            '<Types><Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        )
        z.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
            + body
            + "</w:body></w:document>",
        )
        for name, data in (extras or {}).items():
            z.writestr(name, data)
    return out.getvalue()


def item(raw):
    return {"name": "private.docx", "original_base64": base64.b64encode(raw).decode()}


def test_docx_preview_accept_retry_download_context_and_remove(backend):
    raw = document()
    value = item(raw)
    preview = backend.client.post("/v1/documents/preview", json=value)
    assert preview.status_code == 200 and preview.json()["text"] == "PRIVATE COBALT"
    assert backend.store.all("SELECT * FROM attachment_documents") == []
    chat = new_chat(backend)
    accepted = submit(backend, chat, [value])
    assert accepted.status_code == 202, accepted.text
    wait_run(backend, accepted.json()["id"])
    original = records(backend, chat)
    meta = original[0]["attachments"][0]
    assert meta["bytes"] == len(raw) and meta["sha256"] == hashlib.sha256(raw).hexdigest()
    assert meta["document"]["format"] == "docx"
    assert submit(backend, chat, [value], accepted.json()["id"]).status_code == 202
    assert records(backend, chat) == original
    endpoint = path(chat, meta["id"])
    assert backend.client.get(endpoint + "/download").content == raw
    context = backend.inference.calls[0][1][-1]["content"]
    assert "PRIVATE COBALT" in context and "main-body text only" in context
    assert value["original_base64"] not in context
    other = new_chat(backend)
    assert backend.client.get(path(other, meta["id"])).status_code == 404
    assert backend.client.delete(endpoint).status_code == 200
    assert backend.client.get(endpoint + "/download").status_code == 410
    assert backend.store.one("SELECT original FROM attachment_documents")["original"] is None
    assert backend.store.one("SELECT text FROM message_attachments")["text"] is None


def test_docx_visible_text_ignores_deleted_fields_and_drawings():
    raw = document(
        "<w:p><w:r><w:t>Visible</w:t><w:tab/><w:instrText>SECRET_FIELD</w:instrText></w:r>"
        "<w:del><w:r><w:delText>DELETED</w:delText></w:r></w:del>"
        "<w:drawing><w:t>IMAGE_TEXT</w:t></w:drawing>"
        "<w:hyperlink><w:r><w:t>label</w:t></w:r></w:hyperlink></w:p>",
        {
            "word/_rels/document.xml.rels": (
                "<Relationships><Relationship "
                'Target="https://example.com/private" TargetMode="External"/></Relationships>'
            )
        },
    )
    result = extract_docx(**dict(name="x.docx", encoded=item(raw)["original_base64"]))
    assert result["text"] == "Visible\tlabel"
    assert "Links are never opened" in result["document"]["notice"]


@pytest.mark.parametrize(
    "extra",
    [
        {"../escape": "x"},
        {"word/vbaProject.bin": "x"},
        {"word/embeddings/object.bin": "x"},
        {"WORD/DOCUMENT.XML": "x"},
    ],
)
def test_docx_rejects_unsafe_or_active_package(extra):
    with pytest.raises(HTTPException):
        extract_docx("x.docx", item(document(extras=extra))["original_base64"])


@pytest.mark.parametrize(
    "value", [b'<!DOCTYPE a [<!ENTITY x "secret">]><a>&x;</a>', "<a/>".encode("utf-16"), b"<a>"]
)
def test_xml_refuses_entities_utf16_and_malformed(value):
    with pytest.raises(HTTPException):
        xml(value)


def test_docx_rejects_oversized_text_and_no_text():
    for body in ["<w:p><w:r><w:t>" + "x" * 65537 + "</w:t></w:r></w:p>", "<w:p/>"]:
        with pytest.raises(HTTPException):
            extract_docx("x.docx", item(document(body))["original_base64"])


def test_private_docx_stays_out_of_public_research_and_is_supported_in_work(backend):
    chat = new_chat(backend)
    assert submit(backend, chat, [item(document())], research={"enabled": True}).status_code == 422
    response = backend.client.post(
        "/v1/work/tasks",
        json={"title": "Doc", "requirements": "Read", "source_files": [item(document())]},
    )
    assert response.status_code == 201
    task = response.json()
    assert task["public_research"]["public_query"] is None
    assert (
        backend.store.one("SELECT name FROM work_inputs WHERE task_id=?", (task["id"],))["name"]
        == "private.docx"
    )


def test_standard_writer_document_preserves_paragraph_and_table_text():
    import json
    from pathlib import Path

    sample = json.loads((Path(__file__).parent / "fixtures/docx-sample.json").read_text())
    result = extract_docx(sample["name"], sample["original_base64"])
    assert all(s in result["text"] for s in ["DOCX_PRIVATE_JADE", "Left cell", "Right cell"])
    assert result["text"].index("Left cell") < result["text"].index("Right cell")


def test_v12_migration_preserves_original_text_and_creates_backup(tmp_path):
    import sqlite3

    from dsgpt.migrations import MIGRATIONS
    from dsgpt.storage import APPLICATION_ID, SCHEMA, SCHEMA_VERSION, Store

    with sqlite3.connect(tmp_path / "dsgpt.db") as db:
        db.executescript(SCHEMA + "\n".join(MIGRATIONS[n] for n in range(2, 13)))
        db.execute(f"PRAGMA application_id={APPLICATION_ID}")
        db.execute("PRAGMA user_version=12")
        db.execute("INSERT INTO conversations VALUES('c','Kept',NULL,0,0,0,1,'now','now')")
        db.execute("INSERT INTO messages VALUES('m','c','user','Kept','completed',1,'now')")
        db.execute(
            "INSERT INTO message_attachments VALUES('a','m','kept.txt','PRIVATE',7,'hash','now',0)"
        )
    store = Store(tmp_path)
    assert store.one("SELECT text FROM message_attachments")["text"] == "PRIVATE"
    assert store.all("SELECT * FROM attachment_documents") == []
    backup = next(tmp_path.glob(f"before-v12-to-v{SCHEMA_VERSION}-*.db"))
    with sqlite3.connect(backup) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 12
        assert db.execute("SELECT text FROM message_attachments").fetchone()[0] == "PRIVATE"
