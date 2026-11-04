import asyncio
import io
import json
import threading
import time
import zipfile
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from dsgpt.api import create_app
from dsgpt.config import Model, Settings
from dsgpt.project_tools import ProjectAction, ProjectTools, safe_path
from dsgpt.scheduler import InferenceScheduler
from dsgpt.storage import Store


class AgentFixture:
    def __init__(self, actions):
        self.actions = iter(actions)
        self.calls = 0

    async def stream(self, model, messages, response_schema=None):
        self.calls += 1
        action = next(self.actions)
        yield {
            "kind": "delta",
            "data": {"text": action if isinstance(action, str) else json.dumps(action)},
        }


def setup(tmp_path, inference):
    model = Model("local", "Local", "ollama", "http://127.0.0.1:11434", "local")
    settings = Settings(tmp_path, {model.id: model}, allowed_hosts=("testserver",))
    app = create_app(settings, inference)
    auth = app.state.auth.initialize_owner()
    return app, settings, {"Authorization": "Bearer " + auth["token"]}


def start(client, requirements="Draft a Python greeting file"):
    row = client.post(
        "/v1/work/tasks",
        json={"title": "Example", "requirements": requirements, "model_id": "local"},
    ).json()
    response = client.post(
        f"/v1/work/tasks/{row['id']}/actions", json={"action": "start", "revision": row["revision"]}
    )
    assert response.status_code == 200, response.text
    return row["id"]


def wait_task(client, tid, states=("completed", "blocked")):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        row = client.get("/v1/work/tasks/" + tid).json()
        if row["status"] in states:
            return row
        time.sleep(0.005)
    raise AssertionError("Work did not reach expected state")


def test_work_drafts_real_files_repairs_bad_json_and_exports(tmp_path):
    inference = AgentFixture(
        [
            "not valid JSON",
            {
                "tool": "write_file",
                "path": "hello.py",
                "content": "print('hello')\n",
                "summary": "Wrote greeting",
            },
            {
                "tool": "remember",
                "title": "Decision",
                "content": "Use Python",
                "summary": "Greeting uses Python",
            },
            {"tool": "finish", "summary": "Draft ready. No build or test was run."},
        ]
    )
    app, _, headers = setup(tmp_path, inference)
    with TestClient(app, headers=headers) as client:
        tid = start(client)
        row = wait_task(client, tid)
        assert row["status"] == "completed" and row["session"]["step"] == 4
        assert row["code_execution_available"] is False
        steps = client.get(f"/v1/work/tasks/{tid}/steps").json()
        assert steps[0]["result"]["error"] == "invalid_action"
        assert client.get("/v1/memories").json() == []
        assert client.get("/v1/memories", params={"task_id": tid}).json()[0]["source"] == "agent"
        response = client.get(f"/v1/work/tasks/{tid}/export")
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            assert z.read("project/hello.py") == b"print('hello')\n"
            assert json.loads(z.read("manifest.json"))["execution_verified"] is False
        assert not (tmp_path / "hello.py").exists()


@pytest.mark.parametrize(
    "action,code",
    [
        ("invalid", "invalid_action"),
        ({"tool": "read_file", "path": "missing.py", "summary": "Reading"}, "no_progress"),
        ({"tool": "shell", "command": "whoami", "summary": "Forbidden tool"}, "invalid_action"),
    ],
)
def test_work_stops_identical_failures_and_rejects_unknown_tools(tmp_path, action, code):
    inference = AgentFixture([action] * 8)
    app, _, headers = setup(tmp_path, inference)
    with TestClient(app, headers=headers) as client:
        row = wait_task(client, start(client))
        assert row["status"] == "blocked" and row["session"]["error_code"] == code
        assert inference.calls == 3


@pytest.mark.parametrize(
    "path",
    [
        "../escape",
        "/etc/passwd",
        "C:/secret",
        "a\\b",
        "a//b",
        ".git/config",
        "CON.txt",
        "a/nul",
        "a/..",
        "a.",
        "x\nq",
        "a:b",
        "file?",
    ],
)
def test_project_paths_reject_escapes_and_windows_aliases(path):
    with pytest.raises(ValueError):
        safe_path(path)


def test_tool_and_step_rollback_together_and_overwrite_requires_hash(tmp_path):
    app, _, _ = setup(tmp_path, AgentFixture([]))
    tid = app.state.work.create("Draft", "Requirements", "local")["id"]
    action = ProjectAction(tool="write_file", path="main.py", content="original", summary="First")
    with pytest.raises(RuntimeError):
        with app.state.store.transaction() as db:
            ProjectTools.apply(db, tid, action)
            raise RuntimeError("simulated process failure before commit")
    assert app.state.store.all("SELECT * FROM work_files") == []
    with app.state.store.transaction() as db:
        first = ProjectTools.apply(db, tid, action)
        assert ProjectTools.apply(db, tid, action)["error"] == "file_changed_read_before_overwrite"
        changed = action.model_copy(
            update={"content": "changed", "expected_sha256": first["sha256"]}
        )
        assert ProjectTools.apply(db, tid, changed)["revision"] == 2
        conflict = action.model_copy(update={"path": "MAIN.py"})
        assert ProjectTools.apply(db, tid, conflict)["error"] == "case_conflicting_path"


async def test_scheduler_fairness_exclusion_and_waiter_cancellation(tmp_path):
    scheduler = InferenceScheduler(Store(tmp_path))
    order, tasks = [], []

    async def job(kind, name):
        async with scheduler.acquire(kind, name):
            order.append(name)
            await asyncio.sleep(0)
            assert scheduler.active["request_id"] == name

    async with scheduler.acquire("chat", "holding"):
        tasks = [asyncio.create_task(job("chat", f"c{i}")) for i in range(4)]
        tasks += [asyncio.create_task(job("work", "w0"))]
        cancelled = asyncio.create_task(job("work", "cancelled"))
        await asyncio.sleep(0)
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled
        assert scheduler.snapshot()["waiting"] == {"chat": 4, "work": 1}
    await asyncio.gather(*tasks)
    assert order == ["c0", "w0", "c1", "c2", "c3"]
    assert scheduler.active is None and scheduler.snapshot()["waiting"] == {"chat": 0, "work": 0}


def test_restart_recovers_running_turn_without_repeating_committed_file(tmp_path):
    first = AgentFixture([])
    app, settings, headers = setup(tmp_path, first)
    task = app.state.work.create("Recover", "Keep previous code", "local")
    tid = task["id"]
    with app.state.store.transaction() as db:
        ProjectTools.apply(
            db,
            tid,
            ProjectAction(tool="write_file", path="first.py", content="keep", summary="First"),
        )
        db.execute("UPDATE work_tasks SET status='running' WHERE id=?", (tid,))
        db.execute(
            "UPDATE work_sessions SET step=1,summary='first.py was saved' WHERE task_id=?", (tid,)
        )
        db.execute("INSERT INTO work_steps VALUES(?,1,'{}','{}','now')", (tid,))
    restored = create_app(
        settings, AgentFixture([{"tool": "finish", "summary": "Retained prior draft"}])
    )
    with TestClient(restored, headers=headers) as client:
        row = wait_task(client, tid)
        assert row["status"] == "completed" and row["session"]["step"] == 2
        assert client.get(f"/v1/work/tasks/{tid}/files").json()[0]["revision"] == 1
        assert any(
            c["state"].get("action") == "recover"
            for c in client.get(f"/v1/work/tasks/{tid}/checkpoints").json()
        )


def test_pause_cancels_generation_and_stays_paused_across_restart(tmp_path):
    started = threading.Event()

    class WaitingInference:
        async def stream(self, model, messages, response_schema=None):
            if response_schema:
                started.set()
                while True:
                    await asyncio.sleep(0.01)
            yield {"kind": "delta", "data": {"text": "Chat after pause"}}

    app, settings, headers = setup(tmp_path, WaitingInference())
    with TestClient(app, headers=headers) as client:
        tid = start(client)
        assert started.wait(2)
        row = client.get("/v1/work/tasks/" + tid).json()
        paused = client.post(
            f"/v1/work/tasks/{tid}/actions", json={"action": "pause", "revision": row["revision"]}
        )
        assert paused.json()["status"] == "paused"
        chat = client.post("/v1/conversations", json={"title": "After pause"}).json()
        run = client.post(
            f"/v1/conversations/{chat['id']}/messages",
            json={"request_id": str(uuid4()), "model_id": "local", "content": "Reply"},
        ).json()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if client.get(f"/v1/runs/{run['id']}").json()["status"] == "completed":
                break
            time.sleep(0.01)
        assert client.get(f"/v1/runs/{run['id']}").json()["status"] == "completed"
        assert client.get(f"/v1/work/tasks/{tid}/files").json() == []
    never_called = AgentFixture([])
    restored = create_app(settings, never_called)
    with TestClient(restored, headers=headers) as client:
        assert client.get(f"/v1/work/tasks/{tid}").json()["status"] == "paused"
        assert never_called.calls == 0


def test_retrying_task_creation_does_not_duplicate_and_notes_preserve_original(backend):
    body = {
        "title": "Idempotent",
        "requirements": "Original requirement",
        "request_id": str(uuid4()),
    }
    first = backend.client.post("/v1/work/tasks", json=body).json()
    second = backend.client.post("/v1/work/tasks", json=body).json()
    assert first["id"] == second["id"]
    assert (
        backend.client.post("/v1/work/tasks", json={**body, "title": "different"}).status_code
        == 409
    )
    edited = backend.client.patch(
        f"/v1/work/tasks/{first['id']}",
        json={"revision": 1, "note": "Additional requirement", "model_id": "test-na"},
    ).json()
    assert edited["requirements"].startswith("Original requirement")
    assert "Additional requirement" in edited["requirements"]
    assert edited["execution_available"]
    assert backend.client.post("/v1/work/tasks", json=body).json()["id"] == first["id"]
    assert (
        backend.client.patch(
            f"/v1/work/tasks/{first['id']}", json={"revision": 1, "note": "Stale edit"}
        ).status_code
        == 409
    )


def test_empty_finish_is_not_reported_as_completed(tmp_path):
    action = {"tool": "finish", "summary": "Pretend everything is done"}
    app, _, headers = setup(tmp_path, AgentFixture([action] * 4))
    with TestClient(app, headers=headers) as client:
        row = wait_task(client, start(client))
        assert row["status"] == "blocked" and row["session"]["error_code"] == "no_progress"


def test_alternating_failed_actions_do_not_loop_indefinitely(tmp_path):
    actions = [
        {"tool": "read_file", "path": f"missing{i}.py", "summary": "Try another missing file"}
        for i in range(8)
    ]
    fixture = AgentFixture(actions)
    app, _, headers = setup(tmp_path, fixture)
    with TestClient(app, headers=headers) as client:
        row = wait_task(client, start(client))
        assert row["session"]["error_code"] == "no_progress"
        assert fixture.calls == 3
        saved = app.state.store.one(
            "SELECT payload FROM diagnostic_snapshots WHERE reason='work_no_progress'"
        )
        assert saved and json.loads(saved["payload"])["correlation_id"] == row["id"]
