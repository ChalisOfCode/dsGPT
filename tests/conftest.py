import asyncio
import threading
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from dsgpt.api import create_app
from dsgpt.config import Model, Settings


class ControlledInference:
    def __init__(self):
        self.calls = []
        self.gate = threading.Event()
        self.gate.set()
        self.error = None
        self.started = threading.Event()

    async def stream(self, model, messages):
        self.calls.append((model.id, messages))
        self.started.set()
        while not self.gate.is_set():
            await asyncio.sleep(0.005)
        yield {"kind": "delta", "data": {"text": "Hello "}}
        await asyncio.sleep(0.01)
        if self.error:
            raise self.error
        yield {"kind": "delta", "data": {"text": "world"}}


@pytest.fixture
def backend(tmp_path):
    model = Model("test-na", "Test Model", "ollama", "http://127.0.0.1:11434", "test:1b")
    settings = Settings(tmp_path / "data", {model.id: model}, allowed_hosts=("testserver",))
    inference = ControlledInference()
    app = create_app(settings, inference)
    credentials = app.state.auth.initialize_owner()
    headers = {"Authorization": "Bearer " + credentials["token"]}
    with TestClient(app, headers=headers) as client:
        yield SimpleNamespace(
            app=app,
            client=client,
            headers=headers,
            settings=settings,
            credentials=credentials,
            inference=inference,
            store=app.state.store,
        )


def new_chat(backend, title="New chat"):
    response = backend.client.post("/v1/conversations", json={"title": title})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def send(backend, chat_id, text="Hello", request_id=None):
    return backend.client.post(
        f"/v1/conversations/{chat_id}/messages",
        json={"request_id": request_id or str(uuid4()), "content": text, "model_id": "test-na"},
    )


def wait_run(backend, run_id, states=("completed", "failed", "interrupted", "cancelled")):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        row = backend.client.get(f"/v1/runs/{run_id}").json()
        if row["status"] in states:
            return row
        time.sleep(0.01)
    raise AssertionError("Run did not reach expected state")


def pair(backend, scopes=None):
    scopes = scopes if scopes is not None else ["chat", "work", "diagnostics"]
    response = backend.client.post("/v1/pairings", json={"scopes": scopes})
    assert response.status_code == 200
    code = response.json()["code"]
    response = backend.client.post("/v1/pairings/redeem", json={"code": code, "name": "Test phone"})
    assert response.status_code == 200
    return response.json(), code
