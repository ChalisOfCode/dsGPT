import json

import httpx
import pytest

from dsgpt.config import Model
from dsgpt.inference import InferenceError, LocalInference
from dsgpt.models import ModelRegistry
from dsgpt.storage import Store


async def test_registration_pins_local_digest_persists_and_never_changes_runtime(tmp_path):
    calls = []
    digest = "a" * 64

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": "local:9b", "size": 9000, "digest": digest}]}
            )
        return httpx.Response(200, json={"model_info": {"general.architecture": "qwen"}})

    store, models = Store(tmp_path), {}
    inference = LocalInference(httpx.MockTransport(handler))
    registry = ModelRegistry(store, models, inference)
    definition = {
        "id": "nine",
        "name": "Nine",
        "runtime": "ollama",
        "endpoint": "http://127.0.0.1:11434",
        "runtime_model": "local:9b",
    }
    result = await registry.register(definition)
    assert result["digest"] == "a" * 64 and not result["weights_modified"]
    assert models["nine"].expected_digest == "a" * 64
    restored = {}
    ModelRegistry(Store(tmp_path), restored)
    assert restored == models
    digest = "b" * 64
    with pytest.raises(InferenceError, match="model_digest_changed"):
        async with inference.client(models["nine"]) as client:
            await inference.validate_local_model(client, models["nine"])
    assert registry.forget("nine")["weights_deleted"] is False
    assert all(p in {"/api/tags", "/api/show"} for _, p in calls)


def test_model_registration_is_owner_only_and_remote_models_are_rejected(backend):
    from conftest import pair

    phone, _ = pair(backend)
    body = {
        "id": "bad",
        "name": "Remote",
        "runtime": "ollama",
        "endpoint": "https://remote.example",
        "runtime_model": "local:9b",
    }
    assert backend.client.post("/v1/models/register", json=body).status_code == 422
    assert (
        backend.client.post(
            "/v1/models/register", json=body, headers={"Authorization": "Bearer " + phone["token"]}
        ).status_code
        == 403
    )
    assert backend.client.delete("/v1/models/test-na").status_code == 409


async def test_structured_actions_are_requested_from_both_local_runtimes():
    from dsgpt.project_tools import action_schema

    bodies = []

    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": "test", "size": 1, "digest": "a" * 64}]}
            )
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"model_info": {"architecture": "test"}})
        if request.url.path == "/api/generate":
            return httpx.Response(200, json={"done": True})
        fixed = {
            "/v1/models": {"data": [{"id": "test"}]},
            "/props": {"default_generation_settings": {"n_ctx": 8192}},
            "/apply-template": {"prompt": "test"},
            "/tokenize": {"tokens": [1, 2]},
        }
        if request.url.path in fixed:
            return httpx.Response(200, json=fixed[request.url.path])
        bodies.append(json.loads(request.content))
        answer = json.dumps({"tool": "list_files", "summary": "Inspect saved project files"})
        return httpx.Response(
            200,
            text=json.dumps({"message": {"content": answer}, "done": True}) + "\n"
            if request.url.path == "/api/chat"
            else "data: "
            + json.dumps({"choices": [{"delta": {"content": answer}}]})
            + "\n\ndata: [DONE]\n\n",
        )

    inference = LocalInference(httpx.MockTransport(handler))
    for runtime in ("ollama", "llama.cpp"):
        model = Model("test", "Test", runtime, "http://127.0.0.1:11434", "test")
        _ = [
            e
            async for e in inference.stream(
                model, [{"role": "user", "content": "draft"}], action_schema()
            )
        ]
    assert bodies[0]["format"] == action_schema() and bodies[0]["keep_alive"] == "5m"
    assert bodies[1]["response_format"]["json_schema"]["schema"] == action_schema()
