from conftest import new_chat, send, wait_run


def test_latest_run_snapshot_has_content_and_matching_replay_cursor(backend):
    chat = new_chat(backend)
    assert backend.client.get(f"/v1/conversations/{chat}/latest-run").json() is None
    run = send(backend, chat).json()
    wait_run(backend, run["id"])
    snapshot = backend.client.get(f"/v1/conversations/{chat}/latest-run").json()
    assert snapshot["message"]["content"] == "Hello world"
    assert snapshot["run"]["status"] == "completed"
    assert snapshot["cursor"] > 0
    replay = backend.client.get(f"/v1/runs/{run['id']}/events?after={snapshot['cursor']}")
    assert replay.text == ""
    second = send(backend, chat, "again").json()
    wait_run(backend, second["id"])
    snapshot = backend.client.get(f"/v1/conversations/{chat}/latest-run").json()
    assert snapshot["run"]["id"] == second["id"]


def test_running_snapshot_then_replay_reconstructs_exact_reply(backend):
    backend.inference.gate.clear()
    chat = new_chat(backend)
    run = send(backend, chat).json()
    wait_run(backend, run["id"], ("running",))
    snapshot = backend.client.get(f"/v1/conversations/{chat}/latest-run").json()
    assert snapshot["run"]["status"] == "running"
    backend.inference.gate.set()
    wait_run(backend, run["id"])
    rows = backend.store.all(
        "SELECT kind,payload FROM events WHERE run_id=? AND id>? ORDER BY id",
        (run["id"], snapshot["cursor"]),
    )
    import json

    content = snapshot["message"]["content"] + "".join(
        json.loads(row["payload"])["text"] for row in rows if row["kind"] == "delta"
    )
    assert content == "Hello world"


def test_disallowed_browser_origin_is_rejected_before_preflight(backend):
    response = backend.client.options(
        "/v1/models",
        headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert response.status_code == 403
    assert "access-control-allow-origin" not in response.headers
