import json
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
import pytest
from conftest import ControlledInference, new_chat, send, wait_run
from fastapi.testclient import TestClient

from dsgpt.api import create_app
from dsgpt.inference import InferenceError, LocalInference


def test_hidden_chats_and_pins_preserve_data(backend):
    chat = new_chat(backend, "Project turbine")
    run = send(backend, chat, "A private needle").json()
    wait_run(backend, run["id"])
    row = backend.client.get("/v1/conversations").json()[0]
    response = backend.client.patch(
        f"/v1/conversations/{chat}",
        json={"revision": row["revision"], "hidden": True, "pinned": True, "pin_order": 4},
    )
    assert response.status_code == 200
    assert backend.client.get("/v1/conversations?q=needle").json() == []
    hidden = backend.client.get("/v1/conversations?hidden=true&q=needle").json()
    assert hidden[0]["id"] == chat
    assert len(backend.client.get(f"/v1/conversations/{chat}/messages").json()) == 2
    response = backend.client.patch(
        f"/v1/conversations/{chat}", json={"revision": hidden[0]["revision"], "hidden": False}
    )
    assert response.json()["pinned"] == 1


def test_pinning_has_no_ten_chat_limit_and_pagination(backend):
    for i in range(12):
        chat = new_chat(backend, f"Pinned {i}")
        assert (
            backend.client.patch(
                f"/v1/conversations/{chat}", json={"revision": 1, "pinned": True, "pin_order": i}
            ).status_code
            == 200
        )
    rows = backend.client.get("/v1/conversations?limit=10&offset=10").json()
    assert len(rows) == 2 and all(row["pinned"] for row in rows)
    assert rows[0]["pin_order"] == 10


def test_revision_conflict_and_literal_search(backend):
    chat = new_chat(backend, "100%_test")
    new_chat(backend, "Another")
    patch = {"revision": 1, "title": "100%_renamed"}
    assert backend.client.patch(f"/v1/conversations/{chat}", json=patch).status_code == 200
    assert backend.client.patch(f"/v1/conversations/{chat}", json=patch).status_code == 409
    assert len(backend.client.get("/v1/conversations", params={"q": "%_"}).json()) == 1


def test_reply_without_open_stream_and_replay_cursor(backend):
    chat = new_chat(backend)
    run = send(backend, chat).json()
    assert wait_run(backend, run["id"])["status"] == "completed"
    messages = backend.client.get(f"/v1/conversations/{chat}/messages").json()
    assert messages[1]["content"] == "Hello world"
    response = backend.client.get(f"/v1/runs/{run['id']}/events")
    assert response.status_code == 200
    assert "event: completed" in response.text
    ids = [int(line[4:]) for line in response.text.splitlines() if line.startswith("id: ")]
    assert len(ids) == len(set(ids))
    replay = backend.client.get(
        f"/v1/runs/{run['id']}/events", headers={"Last-Event-ID": str(ids[2])}
    )
    replay_ids = [int(line[4:]) for line in replay.text.splitlines() if line.startswith("id: ")]
    assert replay_ids == ids[3:]
    assert len(backend.inference.calls) == 1


def test_concurrent_retries_do_not_duplicate_messages(backend):
    chat, request_id = new_chat(backend), str(uuid4())
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: send(backend, chat, request_id=request_id), range(8)))
    assert all(r.status_code == 202 for r in responses)
    wait_run(backend, request_id)
    assert len(backend.inference.calls) == 1
    assert len(backend.client.get(f"/v1/conversations/{chat}/messages").json()) == 2
    assert send(backend, chat, "different", request_id).status_code == 409


def test_conversation_context_and_model_labels(backend):
    chat = new_chat(backend)
    first = send(backend, chat, "Remember that project name is Orchard.").json()
    wait_run(backend, first["id"])
    second = send(backend, chat, "What was the name?").json()
    wait_run(backend, second["id"])
    history = backend.inference.calls[1][1]
    assert [m["role"] for m in history] == ["user", "assistant", "user"]
    assert "Orchard" in history[0]["content"]
    assert backend.client.get("/v1/models").json()[0]["label"] == "Test Model-NA"


def test_single_active_reply_and_explicit_cancellation(backend):
    backend.inference.gate.clear()
    chat = new_chat(backend)
    run = send(backend, chat).json()
    assert backend.inference.started.wait(2)
    assert send(backend, chat).status_code == 409
    result = backend.client.post(f"/v1/runs/{run['id']}/cancel")
    assert result.json()["status"] == "cancelled"
    backend.inference.gate.set()
    next_run = send(backend, chat, "Next").json()
    assert wait_run(backend, next_run["id"])["status"] == "completed"


def test_runtime_errors_are_honest_and_sanitized(backend):
    backend.inference.error = InferenceError("runtime_unavailable")
    run = send(backend, new_chat(backend)).json()
    result = wait_run(backend, run["id"])
    assert result["status"] == "failed"
    assert result["error_code"] == "runtime_unavailable"
    backend.inference.error = RuntimeError("password=super-secret-private-conversation")
    second = send(backend, new_chat(backend)).json()
    wait_run(backend, second["id"])
    assert "super-secret" not in json.dumps(backend.store.all("SELECT * FROM diagnostic_events"))
    assert "super-secret" not in backend.client.get(f"/v1/runs/{second['id']}/events").text


@pytest.mark.parametrize(
    "reason,answer,status,error",
    [
        ("length", "", "failed", "output_limit"),
        ("length", "Partial answer", "completed", None),
        ("stop", "", "failed", "empty_model_response"),
    ],
)
def test_reasoning_only_output_limit_preserves_metrics_without_exposing_reasoning(
    backend, reason, answer, status, error
):
    secret = "PRIVATE_REASONING_DO_NOT_EXPORT"

    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": "test:1b", "size": 1, "digest": "a" * 64}]}
            )
        if request.url.path == "/api/show":
            return httpx.Response(
                200,
                json={"model_info": {"architecture": "fixture"}, "thinking": {"values": [True]}},
            )
        assert request.url.path == "/api/chat"
        assert json.loads(request.content)["think"] is None  # No unsupported off switch.
        chunks = [
            {"message": {"thinking": secret, "content": ""}, "done": False},
            {"message": {"thinking": secret, "content": answer}, "done": False},
            {"message": {}, "done": True, "done_reason": reason, "eval_count": 1024},
        ]
        return httpx.Response(200, text="\n".join(json.dumps(chunk) for chunk in chunks) + "\n")

    backend.app.state.runs.inference = LocalInference(httpx.MockTransport(handler))
    run = send(backend, new_chat(backend), "Reply with READY only.").json()
    terminal = wait_run(backend, run["id"])
    assert (terminal["status"], terminal["error_code"]) == (status, error)
    messages = backend.client.get(f"/v1/conversations/{run['conversation_id']}/messages").json()
    assert messages[-1]["content"] == answer
    events = backend.store.all("SELECT kind,payload FROM events WHERE run_id=?", (run["id"],))
    assert secret not in json.dumps(events)
    warnings = [json.loads(e["payload"]) for e in events if e["kind"] == "warning"]
    assert warnings == ([{"code": "output_limit"}] if reason == "length" else [])
    files = backend.client.post("/v1/diagnostics/exports/preview", json={}).json()["files"]
    assert secret not in json.dumps(files)
    evidence = json.loads(files["desktop/inference-metrics.json"])["recent_requests"][0]
    assert evidence["error_code"] == error
    assert evidence["metrics"]["eval_count"] == 1024
    assert evidence["metrics"]["thinking_chunks"] == 2
    assert evidence["metrics"]["elapsed_seconds"] >= 0
    assert ("first_text_seconds" in evidence["metrics"]) == bool(answer)


def test_restart_recovers_queued_and_marks_running_interrupted(backend):
    # Seed persistent accepted state while main worker is deliberately blocked.
    backend.inference.gate.clear()
    first = send(backend, new_chat(backend)).json()
    assert backend.inference.started.wait(2)
    second = send(backend, new_chat(backend), "queued").json()
    # Simulate the database state at process death in a separate database backup.
    recovery_dir = backend.settings.data_dir.parent / "recovery"
    recovery_dir.mkdir()
    backend.store.backup(recovery_dir / "dsgpt.db")
    from dataclasses import replace

    recovered = create_app(replace(backend.settings, data_dir=recovery_dir), ControlledInference())
    with TestClient(recovered, headers=backend.headers) as client:
        assert client.get(f"/v1/runs/{first['id']}").json()["status"] == "interrupted"
        with client.stream("GET", f"/v1/runs/{second['id']}/events") as response:
            assert "event: completed" in response.read().decode()
        assert client.get(f"/v1/runs/{second['id']}").json()["status"] == "completed"
        assert len(recovered.state.runs.inference.calls) == 1
