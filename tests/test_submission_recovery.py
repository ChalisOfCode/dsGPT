"""Lost-response retries must recover accepted work without repeating private tools."""

from uuid import uuid4

import pytest
from conftest import new_chat, pair, wait_run
from schema_fixtures import remove_project_groups
from test_document_processing import SAMPLES, tools


@pytest.fixture(params=["chat", "work"])
def submission(backend, request):
    kind = request.param
    document = {"name": "scan.pdf", "original_base64": SAMPLES["scan.pdf"]}
    body = {"request_id": str(uuid4()), "model_id": "test-na"}
    if kind == "chat":
        chat = new_chat(backend)
        endpoint = f"/v1/conversations/{chat}/messages"
        body.update(content="Read this document", attachments=[document])
    else:
        endpoint = "/v1/work/tasks"
        body.update(
            title="Recovered task", requirements="Read this document", source_files=[document]
        )
    builds = tools(backend)
    response = backend.client.post(endpoint, json=body)
    assert response.status_code == (202 if kind == "chat" else 201), response.text
    if kind == "chat":
        wait_run(backend, response.json()["id"])
    return kind, endpoint, body, builds, response


def test_retry_after_lost_response_does_not_require_document_tools(backend, submission):
    kind, endpoint, body, builds, accepted = submission
    executions = backend.store.all("SELECT * FROM work_executions")
    builds.ready = False
    # Model removal after acceptance also must not prevent receipt recovery.
    backend.app.state.runs.models.clear()
    retry = backend.client.post(endpoint, json=body)
    assert retry.status_code == accepted.status_code, retry.text
    assert retry.json()["id"] == accepted.json()["id"]
    assert backend.store.all("SELECT * FROM work_executions") == executions
    table = "runs" if kind == "chat" else "work_tasks"
    assert len(backend.store.all(f"SELECT * FROM {table}")) == 1


def test_changed_retry_rejected_before_document_processing(backend, submission):
    kind, endpoint, body, builds, accepted = submission
    builds.ready = False
    key = "content" if kind == "chat" else "requirements"
    changed = {**body, key: "Different instructions"}
    retry = backend.client.post(endpoint, json=changed)
    assert retry.status_code == 409
    assert "already used" in retry.text, retry.text


def test_replay_still_requires_current_scope(backend, submission):
    kind, endpoint, body, builds, accepted = submission
    builds.ready = False
    phone, _ = pair(backend, ["work" if kind == "chat" else "chat"])
    retry = backend.client.post(
        endpoint, json=body, headers={"Authorization": "Bearer " + phone["token"]}
    )
    assert retry.status_code == 403


def test_replay_never_restores_removed_documents_or_overwrites_work(backend, submission):
    kind, endpoint, body, builds, accepted = submission
    if kind == "chat":
        attachment = backend.store.one("SELECT id FROM message_attachments")
        chat = endpoint.split("/")[3]
        path = f"/v1/conversations/{chat}/attachments/{attachment['id']}"
        assert backend.client.delete(path).status_code == 200
    else:
        # Model/user changes after creation must not be replaced by the original upload.
        with backend.store.transaction() as db:
            db.execute("UPDATE work_files SET content='Revised project text'")
    builds.ready = False
    retry = backend.client.post(endpoint, json=body)
    assert retry.status_code == accepted.status_code, retry.text
    if kind == "chat":
        assert backend.client.get(path + "/download").status_code == 410
    else:
        assert (
            backend.store.one("SELECT content FROM work_files")["content"] == "Revised project text"
        )


def test_receipt_survives_backend_restart_without_models_or_tools(backend, submission, tmp_path):
    from fastapi.testclient import TestClient

    from dsgpt.api import create_app
    from dsgpt.config import Settings

    kind, endpoint, body, builds, accepted = submission
    recovered = tmp_path / "recovered"
    recovered.mkdir()
    backend.store.backup(recovered / "dsgpt.db")
    app = create_app(Settings(recovered, allowed_hosts=("testserver",)))
    with TestClient(app, headers=backend.headers) as client:
        retry = client.post(endpoint, json=body)
        assert retry.status_code == accepted.status_code, retry.text
        assert retry.json()["id"] == accepted.json()["id"]
        assert len(app.state.store.all("SELECT * FROM work_executions")) == 1


def test_version19_upgrade_verifies_legacy_hash_before_adding_receipt(
    backend, submission, tmp_path
):
    import sqlite3

    from fastapi.testclient import TestClient

    from dsgpt.api import create_app
    from dsgpt.config import Settings
    from dsgpt.storage import SCHEMA_VERSION

    kind, endpoint, body, builds, accepted = submission
    upgraded = tmp_path / "upgraded"
    upgraded.mkdir()
    backend.store.backup(upgraded / "dsgpt.db")
    # Exact v19 layout, with real accepted messages/documents/work input from the API.
    with sqlite3.connect(upgraded / "dsgpt.db") as db:
        remove_project_groups(db)
        for table in (
            "account_browser_profiles",
            "account_browser_writes",
            "account_grants",
            "account_sessions",
            "device_presence",
            "work_uploads",
            "work_web_calls",
            "work_specs",
            "work_spec_sections",
            "work_signing_keys",
        ):
            db.execute("DROP TABLE " + table)
        db.execute("DROP TABLE generation_options")
        db.execute("DROP TABLE diagnostic_snapshots")
        db.execute("DROP TABLE chat_submission_receipts")
        db.execute("DROP TABLE work_submission_receipts")
        db.execute("PRAGMA user_version=19")
    app = create_app(
        Settings(upgraded, dict(backend.settings.models), allowed_hosts=("testserver",))
    )
    with TestClient(app, headers=backend.headers) as client:
        app.state.builds.sandbox = builds.sandbox
        app.state.builds.ready = True
        key = "content" if kind == "chat" else "requirements"
        assert client.post(endpoint, json={**body, key: "Different"}).status_code == 409
        table = f"{kind}_submission_receipts"
        assert not app.state.store.all(f"SELECT * FROM {table}")
        retry = client.post(endpoint, json=body)
        assert retry.status_code == accepted.status_code, retry.text
        app.state.builds.ready = False
        assert client.post(endpoint, json=body).status_code == accepted.status_code
        receipt = app.state.store.one(f"SELECT * FROM {table}")
        assert len(receipt["request_hash"]) == 64
        assert "PRIVATE" not in str(receipt)
        assert app.state.store.one("PRAGMA user_version")["user_version"] == SCHEMA_VERSION
        assert not app.state.store.all("PRAGMA foreign_key_check")
    backups = list(upgraded.glob("before-v19-*.db"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 19
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        table = "runs" if kind == "chat" else "work_tasks"
        assert db.execute(f"SELECT id FROM {table}").fetchone()[0] == accepted.json()["id"]


def test_receipt_cannot_be_replayed_into_another_conversation(backend):
    from conftest import send

    first, second = new_chat(backend), new_chat(backend)
    request_id = str(uuid4())
    accepted = send(backend, first, request_id=request_id)
    wait_run(backend, accepted.json()["id"])
    assert send(backend, second, request_id=request_id).status_code == 409
    assert backend.store.all("SELECT * FROM messages WHERE conversation_id=?", (second,)) == []


def test_failed_work_acceptance_does_not_leave_a_receipt(backend, monkeypatch):
    from dsgpt.project_tools import ProjectTools

    monkeypatch.setattr(ProjectTools, "apply", lambda *args: {"error": "Injected write failure"})
    response = backend.client.post(
        "/v1/work/tasks",
        json={
            "request_id": str(uuid4()),
            "title": "Task",
            "requirements": "Import project",
            "source_files": [{"name": "app.py", "text": "print('hello')"}],
        },
    )
    assert response.status_code == 422
    assert backend.store.all("SELECT * FROM work_tasks") == []
    assert backend.store.all("SELECT * FROM work_submission_receipts") == []


def test_research_replay_preserves_equivalent_url_normalization(backend):
    from test_research import Answer, Reader, research_run

    research = backend.app.state.research
    research.reader, research.inference = Reader(), Answer()
    chat, request_id = new_chat(backend), str(uuid4())
    result = research_run(
        backend,
        {"search": False, "urls": ["https://example.org/a#one", "https://example.org/a#two"]},
        request_id,
        chat,
    )
    assert result.status_code == 202
    wait_run(backend, request_id)
    backend.app.state.runs.models.clear()
    retry = research_run(
        backend, {"search": False, "urls": ["https://example.org/a"]}, request_id, chat
    )
    assert retry.status_code == 202, retry.text
    assert retry.json()["id"] == request_id
    assert research.reader.calls == ["https://example.org/a"]
    changed = research_run(
        backend, {"search": False, "urls": ["https://example.org/b"]}, request_id, chat
    )
    assert changed.status_code == 409


def test_work_replay_preserves_query_whitespace_normalization(backend):
    body = {
        "title": "Task",
        "requirements": "Reference",
        "request_id": str(uuid4()),
        "public_query": "  Public documentation  ",
        "reference_urls": ["https://example.org/a#one", "https://example.org/a#two"],
    }
    first = backend.client.post("/v1/work/tasks", json=body)
    assert first.status_code == 201
    retry = backend.client.post(
        "/v1/work/tasks",
        json={
            **body,
            "public_query": "Public documentation",
            "reference_urls": ["https://example.org/a"],
        },
    )
    assert retry.status_code == 201, retry.text
    assert retry.json()["id"] == first.json()["id"]
    assert len(backend.store.all("SELECT * FROM work_sources")) == 1
    changed = backend.client.post(
        "/v1/work/tasks", json={**body, "public_query": "Different query"}
    )
    assert changed.status_code == 409
