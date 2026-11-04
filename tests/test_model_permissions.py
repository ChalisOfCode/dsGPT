"""A model manager is explicitly delegated, and never becomes a device owner."""

from uuid import uuid4

import pytest
from conftest import pair

OPERATIONS = [
    ("GET", "/v1/model-catalog", None),
    ("GET", "/v1/runtimes", None),
    ("GET", "/v1/runtime/status", None),
    ("POST", "/v1/runtimes/unknown/install", None),
    ("DELETE", "/v1/runtimes/unknown", None),
    ("POST", "/v1/runtime/unload", None),
    (
        "POST",
        "/v1/models/managed",
        {
            "id": "managed",
            "name": "Managed",
            "asset_id": "unknown",
            "runtime_id": "unknown",
        },
    ),
    ("GET", "/v1/downloads", None),
    ("POST", "/v1/downloads", {"asset_id": "unknown"}),
    ("GET", f"/v1/downloads/{uuid4()}", None),
    ("POST", f"/v1/downloads/{uuid4()}/actions", {"action": "pause"}),
    ("DELETE", f"/v1/downloads/{uuid4()}", None),
    (
        "POST",
        "/v1/models/register",
        {
            "id": "external",
            "name": "External",
            "runtime": "ollama",
            "endpoint": "https://example.com",
            "runtime_model": "test",
        },
    ),
    ("DELETE", "/v1/models/test-na", None),
]


@pytest.mark.parametrize("method,path,body", OPERATIONS)
def test_existing_phone_cannot_manage_models(backend, method, path, body):
    phone, _ = pair(backend)
    headers = {"Authorization": "Bearer " + phone["token"]}
    response = backend.client.request(method, path, json=body, headers=headers)
    assert response.status_code == 403
    assert backend.store.all("SELECT * FROM downloads") == []
    assert backend.store.all("SELECT * FROM runtime_installations") == []


def test_explicit_models_permission_is_limited_and_revocable(backend):
    phone, _ = pair(backend, ["models"])
    headers = {"Authorization": "Bearer " + phone["token"]}
    cap = backend.client.get("/v1/capabilities", headers=headers).json()
    assert cap["permissions"] == {
        "chat": False,
        "work": False,
        "model_management": True,
        "search_administration": False,
    }
    assert backend.client.get("/v1/models", headers=headers).json()[0]["configuration_owned"]
    for method, path, body in OPERATIONS:
        response = backend.client.request(method, path, json=body, headers=headers)
        assert response.status_code in {200, 404, 409, 422}, response.text
    for method, path, body in [
        ("GET", "/v1/schema", None),
        ("GET", "/v1/devices", None),
        ("DELETE", f"/v1/devices/{phone['device_id']}", None),
        ("POST", "/v1/pairings", {"scopes": ["models"]}),
        ("POST", "/v1/conversations", {"title": "Forbidden"}),
        ("GET", "/v1/work/tasks", None),
        ("GET", "/v1/diagnostics/overview", None),
    ]:
        assert backend.client.request(method, path, json=body, headers=headers).status_code == 403
    assert backend.client.post("/v1/pairings", json={"scopes": ["admin"]}).status_code == 422
    assert backend.client.delete(f"/v1/devices/{phone['device_id']}").status_code == 200
    assert backend.client.get("/v1/model-catalog", headers=headers).status_code == 401


def test_existing_owner_without_new_scope_keeps_model_management(backend):
    # Pre-upgrade owners keep admin, but are never rewritten to add scopes.
    with backend.store.transaction() as db:
        db.execute("UPDATE devices SET scopes='[\"admin\"]' WHERE role='owner'")
    assert backend.client.get("/v1/model-catalog").status_code == 200
    assert backend.client.get("/v1/models").status_code == 200
    assert backend.client.get("/v1/capabilities").json()["permissions"]["model_management"]
