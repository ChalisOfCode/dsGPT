import json

import httpx
import pytest

from dsgpt.config import Model
from dsgpt.inference import LOCAL_INFERENCE_READ_TIMEOUT, InferenceError, LocalInference


def ollama_handler(request):
    path = request.url.path
    if path == "/api/tags":
        return httpx.Response(
            200, json={"models": [{"name": "test:9b", "size": 6000, "digest": "123456"}]}
        )
    if path == "/api/show":
        return httpx.Response(200, json={"model_info": {"general.architecture": "qwen"}})
    if path == "/api/chat":
        return httpx.Response(
            200,
            text='{"message":{"content":"Hi"},"done":false}\n'
            '{"message":{},"done":true,"eval_count":1}\n',
        )
    raise AssertionError(path)


def ollama_model():
    return Model("local", "Test", "ollama", "http://127.0.0.1:11434", "test:9b")


async def test_local_cpu_generation_has_bounded_long_prompt_read_timeout():
    adapter = LocalInference(httpx.MockTransport(ollama_handler))
    async with adapter.client(ollama_model()) as client:
        assert client.timeout.connect == 10
        assert client.timeout.read == LOCAL_INFERENCE_READ_TIMEOUT == 900
        assert client.timeout.write == 30
        assert client.timeout.pool == 10


async def test_ollama_real_protocol_contract():
    adapter = LocalInference(httpx.MockTransport(ollama_handler))
    events = [e async for e in adapter.stream(ollama_model(), [{"role": "user", "content": "Hi"}])]
    assert events[0]["data"]["method"] == "utf8_safety_estimate"
    assert events[1]["data"]["text"] == "Hi"
    assert events[2]["data"]["eval_count"] == 1


@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize(
    "thinking,expected",
    [
        (None, False),  # Legacy /api/show, including the affected Qwen model.
        ({"values": [True, False], "default": True}, False),
        ({"values": [False], "default": False}, False),
        ({"values": ["low", "medium", "high"], "default": "medium"}, None),
        ({"values": [True], "default": True}, None),
    ],
)
async def test_ollama_requests_answers_without_unsupported_thinking_controls(
    thinking, expected, structured
):
    def handler(request):
        if request.url.path == "/api/show":
            info = {"model_info": {"general.architecture": "qwen"}}
            if thinking is not None:
                info["thinking"] = thinking
            return httpx.Response(200, json=info)
        if request.url.path == "/api/chat":
            payload = json.loads(request.content)
            assert "think" in payload and payload["think"] is expected
            assert payload["options"]["num_predict"] == 1024
            assert payload["messages"] == [{"role": "user", "content": "Reply with READY only."}]
            assert payload["keep_alive"] == "5m"
        return ollama_handler(request)

    events = [
        event
        async for event in LocalInference(httpx.MockTransport(handler)).stream(
            ollama_model(),
            [{"role": "user", "content": "Reply with READY only."}],
            response_schema={"type": "object"} if structured else None,
        )
    ]
    assert events[-1]["data"]["thinking_chunks"] == 0


@pytest.mark.parametrize(
    "change", ["remote_host", "remote_model", "missing_weights", "missing_info"]
)
async def test_ollama_cloud_proxy_and_missing_weights_rejected(change):
    called_chat = False

    def handler(request):
        nonlocal called_chat
        if request.url.path == "/api/chat":
            called_chat = True
        if request.url.path == "/api/show":
            if change == "missing_info":
                return httpx.Response(200, json={})
            if change in {"remote_host", "remote_model"}:
                return httpx.Response(200, json={"model_info": {"a": 1}, change: "cloud"})
        if request.url.path == "/api/tags" and change == "missing_weights":
            return httpx.Response(200, json={"models": []})
        return ollama_handler(request)

    adapter = LocalInference(httpx.MockTransport(handler))
    with pytest.raises(InferenceError, match="local_model_required"):
        _ = [e async for e in adapter.stream(ollama_model(), [{"role": "user", "content": "Hi"}])]
    assert not called_chat


async def test_context_overflow_never_silently_truncates_or_calls_chat():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return ollama_handler(request)

    adapter = LocalInference(httpx.MockTransport(handler))
    with pytest.raises(InferenceError, match="context_exceeded"):
        _ = [
            e
            async for e in adapter.stream(ollama_model(), [{"role": "user", "content": "x" * 9000}])
        ]
    assert "/api/chat" not in calls


@pytest.mark.parametrize("reply", ["not json\n", '{"message":{"content":"partial"}}\n'])
async def test_invalid_or_incomplete_stream_is_an_error(reply):
    def handler(request):
        if request.url.path == "/api/chat":
            return httpx.Response(200, text=reply)
        return ollama_handler(request)

    with pytest.raises(InferenceError, match="runtime_protocol_error"):
        _ = [
            e
            async for e in LocalInference(httpx.MockTransport(handler)).stream(
                ollama_model(), [{"role": "user", "content": "Hi"}]
            )
        ]


async def test_local_redirect_not_followed():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://cloud.example/api"})

    with pytest.raises(InferenceError, match="runtime_unavailable"):
        _ = [
            e
            async for e in LocalInference(httpx.MockTransport(handler)).stream(
                ollama_model(), [{"role": "user", "content": "Hi"}]
            )
        ]
    assert len(seen) == 1 and seen[0].startswith("http://127.0.0.1:")


async def test_llama_tokenizer_contract_and_context_validation():
    model = Model("tiny", "Tiny", "llama.cpp", "http://127.0.0.1:18081", "tiny", context=4096)
    paths = []

    def handler(request):
        paths.append(request.url.path)
        bodies = {
            "/v1/models": {"data": [{"id": "tiny"}]},
            "/props": {"default_generation_settings": {"n_ctx": 4096}},
            "/apply-template": {"prompt": "formatted prompt"},
            "/tokenize": {"tokens": [1, 2, 3]},
        }
        if request.url.path in bodies:
            return httpx.Response(200, json=bodies[request.url.path])
        assert json.loads(request.content)["stream_options"]["include_usage"]
        return httpx.Response(
            200,
            text='data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
            'data: {"choices":[],"usage":{"completion_tokens":1}}\n\n'
            "data: [DONE]\n\n",
        )

    events = [
        e
        async for e in LocalInference(httpx.MockTransport(handler)).stream(
            model, [{"role": "user", "content": "Hello"}]
        )
    ]
    assert events[0]["data"] == {"input_tokens": 3, "method": "runtime_tokenizer"}
    assert paths[-1] == "/v1/chat/completions"


@pytest.mark.parametrize("runtime", ["ollama", "llama.cpp"])
async def test_structured_actions_use_greedy_sampling_without_changing_chat(runtime):
    model = Model("local", "Local", runtime, "http://127.0.0.1:11434", "test:9b")
    requests = []

    def handler(request):
        path = request.url.path
        if path in {"/api/chat", "/v1/chat/completions"}:
            requests.append(json.loads(request.content))
            if runtime == "ollama":
                return ollama_handler(request)
            return httpx.Response(
                200, text='data: {"choices":[{"delta":{"content":"{}"}}]}\n\ndata: [DONE]\n\n'
            )
        if runtime == "ollama":
            return ollama_handler(request)
        bodies = {
            "/v1/models": {"data": [{"id": "test:9b"}]},
            "/props": {"default_generation_settings": {"n_ctx": 8192}},
            "/apply-template": {"prompt": "fixture prompt"},
            "/tokenize": {"tokens": [1, 2, 3]},
        }
        return httpx.Response(200, json=bodies[path])

    adapter = LocalInference(httpx.MockTransport(handler))
    schema = {"type": "object", "properties": {}}
    for response_schema in [None, schema]:
        _ = [
            event
            async for event in adapter.stream(
                model, [{"role": "user", "content": "Fixture"}], response_schema=response_schema
            )
        ]
    ordinary, structured = requests
    if runtime == "ollama":
        assert "temperature" not in ordinary["options"]
        assert structured["options"]["temperature"] == 0
        assert structured["format"] == schema
    else:
        assert "temperature" not in ordinary
        assert structured["temperature"] == 0
        assert structured["response_format"]["json_schema"]["schema"] == schema
