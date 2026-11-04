import json

from conftest import new_chat, pair, wait_run


def test_identity_exposes_only_own_nonsecret_metadata(backend):
    phone, _ = pair(backend, ["chat", "models"])
    headers = {"Authorization": "Bearer " + phone["token"]}
    response = backend.client.get("/v1/device", headers=headers)
    assert response.status_code == 200
    identity = response.json()
    assert set(identity) == {"id", "name", "role", "scopes", "created_at"}
    assert identity["id"] == phone["device_id"]
    assert identity["role"] == "client"
    assert identity["scopes"] == ["chat", "models"]
    assert phone["token"] not in response.text
    assert backend.client.get("/v1/devices", headers=headers).status_code == 403
    assert backend.client.get("/v1/device", headers={"Authorization": ""}).status_code == 401


def test_owner_device_pages_preserve_scopes_and_exclude_secrets(backend):
    ordinary, _ = pair(backend)
    manager, _ = pair(backend, ["models"])
    rows = []
    for offset in range(3):
        batch = backend.client.get(f"/v1/devices?limit=1&offset={offset}").json()
        assert len(batch) == 1
        rows += batch
    assert len({row["id"] for row in rows}) == 3
    assert backend.client.get("/v1/devices?limit=1&offset=3").json() == []
    assert backend.client.get("/v1/devices?limit=0").status_code == 422
    assert backend.client.get("/v1/devices?offset=-1").status_code == 422
    for row in rows:
        assert set(row) == {"id", "name", "role", "scopes", "created_at", "revoked"}
        assert isinstance(row["scopes"], list)
    assert next(row for row in rows if row["id"] == manager["device_id"])["scopes"] == ["models"]
    assert next(row for row in rows if row["id"] == ordinary["device_id"])["scopes"] == [
        "chat",
        "diagnostics",
        "work",
    ]
    for credential in [ordinary, manager, backend.credentials]:
        assert credential["token"] not in json.dumps(rows)
    assert "token_hash" not in json.dumps(rows)


def test_repair_is_separate_from_revocation_and_cannot_reactivate_old_credentials(backend):
    old, _ = pair(backend)
    new, _ = pair(backend, ["chat", "work", "diagnostics", "models"])
    old_headers = {"Authorization": "Bearer " + old["token"]}
    new_headers = {"Authorization": "Bearer " + new["token"]}
    assert old["device_id"] != new["device_id"]
    assert backend.client.get("/v1/device", headers=old_headers).status_code == 200
    for _ in range(2):
        assert backend.client.delete("/v1/devices/" + old["device_id"]).status_code == 200
    assert backend.client.get("/v1/device", headers=old_headers).status_code == 401
    assert backend.client.get("/v1/device", headers=new_headers).status_code == 200
    assert backend.client.get("/v1/model-catalog", headers=new_headers).status_code == 200
    rows = backend.client.get("/v1/devices").json()
    assert next(row for row in rows if row["id"] == old["device_id"])["revoked"] == 1


def test_revoking_device_blocks_new_requests_but_preserves_accepted_work(backend):
    phone, _ = pair(backend, ["chat"])
    headers = {"Authorization": "Bearer " + phone["token"]}
    chat = new_chat(backend)
    backend.inference.gate.clear()
    # Accepted requests belong to the backend, not the lifetime of a client credential.
    from uuid import uuid4

    response = backend.client.post(
        f"/v1/conversations/{chat}/messages",
        headers=headers,
        json={
            "request_id": str(uuid4()),
            "content": "Continue this accepted reply",
            "model_id": "test-na",
        },
    )
    assert response.status_code == 202
    run = response.json()["id"]
    assert backend.inference.started.wait(2)
    assert backend.client.delete("/v1/devices/" + phone["device_id"]).status_code == 200
    assert backend.client.get("/v1/runs/" + run, headers=headers).status_code == 401
    backend.inference.gate.set()
    assert wait_run(backend, run)["status"] == "completed"
    assert backend.client.get("/v1/conversations/" + chat).status_code == 200
