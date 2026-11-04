import time

from conftest import new_chat, send, wait_run


def test_delete_removes_message_files_search_and_stops_active_reply(backend):
    chat = new_chat(backend, "To delete")
    response = backend.client.post(
        f"/v1/conversations/{chat}/messages",
        json={
            "request_id": "dd5139d9-1dda-46e8-a761-b728bb67c5d6",
            "content": "remember this attachment",
            "model_id": "test-na",
            "attachments": [{"name": "test.txt", "text": "private attachment data"}],
        },
    )
    assert response.status_code == 202
    wait_run(backend, response.json()["id"])
    files = backend.client.get(f"/v1/conversations/{chat}/files").json()
    assert len(files) == 1
    backend.inference.gate.clear()
    active = send(backend, chat, "An active reply").json()
    assert backend.client.delete(f"/v1/conversations/{chat}").status_code == 200
    assert backend.client.get(f"/v1/conversations/{chat}").status_code == 404
    assert backend.client.get(f"/v1/runs/{active['id']}").status_code == 404
    for table in (
        "messages",
        "runs",
        "message_attachments",
        "attachment_documents",
        "semantic_jobs",
    ):
        assert not backend.store.one(f"SELECT 1 FROM {table}")
    assert backend.client.delete(f"/v1/conversations/{chat}").json() == {"deleted": True}
    assert not backend.store.all("PRAGMA foreign_key_check")


def test_phone_saved_pairing_is_not_confused_with_online_status(backend):
    c = backend.client
    assert not c.get("/v1/devices/phone-status").json()["paired"]
    code = c.post("/v1/pairings", json={"scopes": ["chat", "work"]}).json()["code"]
    phone = c.post("/v1/pairings/redeem", json={"code": code, "name": "dsGPT Mobile"}).json()
    headers = {"Authorization": "Bearer " + phone["token"]}
    status = c.get("/v1/devices/phone-status").json()
    assert status["paired"] and not status["online"]
    assert (
        c.post("/v1/device/heartbeat", json={"app_version": "0.9.0"}, headers=headers).status_code
        == 200
    )
    assert c.get("/v1/devices/phone-status").json()["online"]
    with backend.store.transaction() as db:
        db.execute("UPDATE device_presence SET last_seen=?", (time.time() - 120,))
    status = c.get("/v1/devices/phone-status").json()
    assert status["paired"] and not status["online"]
    assert c.get("/v1/devices/phone-status", headers=headers).status_code == 403
    c.delete("/v1/devices/" + phone["device_id"])
    assert not c.get("/v1/devices/phone-status").json()["paired"]
