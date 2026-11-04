import json
import sqlite3
import time

import pytest
from conftest import pair
from fastapi import HTTPException

from dsgpt.config import Model
from dsgpt.storage import APPLICATION_ID, InstanceLock, Store


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://api.openai.com",
        "http://192.168.1.5:11434",
        "http://localhost:11434",
        "http://127.0.0.1.evil.example:11434",
        "http://127.1:11434",
        "http://2130706433:11434",
        "http://user:secret@127.0.0.1:11434",
        "http://127.0.0.1:11434/v1",
        "http://127.0.0.1:11434?q=1",
        "http://127.0.0.1:11434/#remote",
        "http://127.0.0.1",
    ],
)
def test_inference_endpoints_fail_closed(endpoint):
    with pytest.raises(ValueError):
        Model("m", "Model", "ollama", endpoint, "local:9b")


def test_cloud_identifier_and_unknown_runtime_rejected():
    with pytest.raises(ValueError):
        Model("m", "Model", "ollama", "http://127.0.0.1:11434", "model:cloud")
    with pytest.raises(ValueError):
        Model("m", "Model", "hosted", "http://127.0.0.1:11434", "model")


@pytest.mark.parametrize(
    "path",
    [
        "/v1/conversations",
        "/v1/devices",
        "/v1/models",
        "/v1/work/tasks",
        "/v1/diagnostics/overview",
        "/v1/schema",
    ],
)
def test_api_requires_authentication(backend, path):
    response = backend.client.get(path, headers={"Authorization": ""})
    assert response.status_code == 401


def test_pairing_is_single_use_expires_and_scoped(backend):
    phone, code = pair(backend, ["chat"])
    response = backend.client.post("/v1/pairings/redeem", json={"code": code, "name": "Again"})
    assert response.status_code == 401
    headers = {"Authorization": "Bearer " + phone["token"]}
    assert backend.client.get("/v1/conversations", headers=headers).status_code == 200
    assert backend.client.get("/v1/devices", headers=headers).status_code == 403
    assert backend.client.get("/v1/diagnostics/overview", headers=headers).status_code == 403
    new_code = backend.app.state.auth.create_pairing(["chat"])["code"]
    with backend.store.transaction() as db:
        db.execute("UPDATE pairings SET expires=?", (time.time() - 1,))
    with pytest.raises(HTTPException) as exc:
        backend.app.state.auth.redeem(new_code, "Expired")
    assert exc.value.status_code == 401


def test_tokens_hashed_and_revocation_enforced(backend):
    phone, _ = pair(backend)
    rows = backend.store.all("SELECT * FROM devices")
    assert phone["token"] not in json.dumps(rows)
    assert backend.credentials["token"] not in json.dumps(rows)
    headers = {"Authorization": "Bearer " + phone["token"]}
    assert backend.client.get("/v1/models", headers=headers).status_code == 200
    assert backend.client.delete("/v1/devices/" + phone["device_id"]).status_code == 200
    assert backend.client.get("/v1/models", headers=headers).status_code == 401


def test_no_remote_owner_escalation_or_owner_overwrite(backend):
    assert backend.client.post("/v1/pairings", json={"scopes": ["admin"]}).status_code == 422
    with pytest.raises(ValueError, match="already initialized"):
        backend.app.state.auth.initialize_owner()
    assert (
        backend.client.delete("/v1/devices/" + backend.credentials["device_id"]).status_code == 409
    )


def test_origin_host_and_request_size_boundaries(backend):
    assert (
        backend.client.get("/health", headers={"Origin": "https://evil.example"}).status_code == 403
    )
    assert backend.client.get("/health", headers={"Host": "evil.example"}).status_code == 400
    response = backend.client.post("/v1/conversations", content=b"a" * 2_000_001)
    assert response.status_code == 413
    assert backend.client.get("/health").headers["cache-control"] == "no-store"


def test_validation_does_not_echo_credentials(backend):
    secret = "Bearer top-secret-PRIVATE-KEY"
    response = backend.client.post("/v1/pairings/redeem", json={"code": secret, "name": "test"})
    assert response.status_code == 422
    assert secret not in response.text


def test_foreign_database_not_modified(tmp_path):
    path = tmp_path / "dsgpt.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE precious(data TEXT)")
        db.execute("INSERT INTO precious VALUES('do not overwrite')")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="Not a dsGPT"):
        Store(tmp_path)
    assert path.read_bytes() == before


def test_downgrade_refused(tmp_path):
    with sqlite3.connect(tmp_path / "dsgpt.db") as db:
        db.execute(f"PRAGMA application_id={APPLICATION_ID}")
        db.execute("PRAGMA user_version=99")
    with pytest.raises(ValueError, match="newer"):
        Store(tmp_path)


def test_second_process_lock_denied_and_released(tmp_path):
    first, second = InstanceLock(tmp_path), InstanceLock(tmp_path)
    first.acquire()
    with pytest.raises(RuntimeError, match="Another"):
        second.acquire()
    first.release()
    second.acquire()
    second.release()


def test_backup_includes_wal_and_never_overwrites(backend, tmp_path):
    target = tmp_path / "backup.db"
    backend.store.backup(target)
    with sqlite3.connect(target) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("SELECT COUNT(*) FROM devices").fetchone()[0] == 1
    with pytest.raises(FileExistsError):
        backend.store.backup(target)
