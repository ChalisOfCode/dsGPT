"""Benign protocol fixtures: empty replies must not become retrying JSON actions."""

import json

import httpx
import pytest
from test_inference import ollama_handler

from dsgpt.config import Model
from dsgpt.inference import InferenceError, LocalInference
from dsgpt.project_tools import ProjectAction
from dsgpt.scheduler import InferenceScheduler
from dsgpt.storage import Store
from dsgpt.work import WorkRegistry


@pytest.mark.parametrize("runtime", ["ollama", "llama.cpp"])
@pytest.mark.parametrize(
    "reason,error", [("stop", "empty_model_response"), ("length", "output_limit")]
)
@pytest.mark.parametrize("content", ["", " \n\t"])
async def test_completed_empty_stream_classifies_error_without_reasoning_leak(
    runtime, reason, error, content
):
    secret = "PRIVATE_REASONING_NEVER_RETURN"
    model = Model("local", "Fixture", runtime, "http://127.0.0.1:11434", "test:9b")

    def handler(request):
        if request.url.path == "/api/chat":
            chunks = [
                {"message": {"thinking": secret, "content": content}, "done": False},
                {"message": {}, "done": True, "done_reason": reason, "eval_count": 1024},
            ]
            return httpx.Response(200, text="\n".join(json.dumps(chunk) for chunk in chunks))
        if runtime == "ollama":
            return ollama_handler(request)
        bodies = {
            "/v1/models": {"data": [{"id": "test:9b"}]},
            "/props": {"default_generation_settings": {"n_ctx": 8192}},
            "/apply-template": {"prompt": "fixture"},
            "/tokenize": {"tokens": [1, 2]},
        }
        if request.url.path in bodies:
            return httpx.Response(200, json=bodies[request.url.path])
        chunks = [
            {"choices": [{"delta": {"reasoning_content": secret, "content": content}}]},
            {
                "choices": [{"delta": {}, "finish_reason": reason}],
                "usage": {"completion_tokens": 1024},
            },
        ]
        return httpx.Response(
            200,
            text="".join("data: " + json.dumps(c) + "\n\n" for c in chunks) + "data: [DONE]\n\n",
        )

    events = []
    with pytest.raises(InferenceError, match=error):
        async for event in LocalInference(httpx.MockTransport(handler)).stream(
            model,
            [{"role": "user", "content": "Reply with READY."}],
            response_schema={"type": "object"},
        ):
            events.append(event)
    assert secret not in json.dumps(events)
    assert any(event["kind"] == "metrics" for event in events)
    assert [event["data"]["code"] for event in events if event["kind"] == "warning"] == (
        ["output_limit"] if reason == "length" else []
    )


@pytest.mark.parametrize("phase", ["action", "specification", "inline_specification", "image"])
@pytest.mark.parametrize("limited", [False, True])
@pytest.mark.parametrize("reply", ["", " \n"])
async def test_work_blocks_first_empty_reply_without_rewriting_prior_evidence(
    tmp_path, phase, limited, reply
):
    class Empty:
        calls = 0

        async def stream(self, *args, **kwargs):
            self.calls += 1
            yield {"kind": "context", "data": {"method": "runtime_tokenizer", "input_tokens": 19}}
            if reply:
                yield {"kind": "delta", "data": {"text": reply}}
            if limited:
                yield {"kind": "warning", "data": {"code": "output_limit"}}
            yield {"kind": "metrics", "data": {"eval_count": 3, "thinking_chunks": 2}}

    store = Store(tmp_path)
    model = Model("local", "Fixture", "ollama", "http://127.0.0.1:11434", "local")
    inference = Empty()
    work = WorkRegistry(
        store, models={"local": model}, inference=inference, scheduler=InferenceScheduler(store)
    )
    task = work.create("Greeting", "Create a simple greeting text file.", "local", start=True)
    tid = task["id"]
    with store.transaction() as db:
        db.execute("UPDATE work_tasks SET status='running' WHERE id=?", (tid,))
    session = store.one("SELECT * FROM work_sessions WHERE task_id=?", (tid,))
    work._commit(
        tid,
        session,
        ProjectAction(
            tool="write_file", path="greeting.txt", content="Hello", summary="Saved greeting"
        ),
    )
    if phase != "action":
        with store.transaction() as db:
            work.specs.initialize(db, tid, task["requirements"])
            if phase == "image":
                db.execute("UPDATE work_spec_sections SET notes='Reviewed' WHERE task_id=?", (tid,))
                db.execute(
                    "INSERT INTO work_inputs VALUES(?,?,?,?,?)",
                    (tid, "reference.png", b"fixture", "h", '{"image":true}'),
                )
    before = store.all("SELECT * FROM work_steps WHERE task_id=?", (tid,))
    await work._step(
        store.one("SELECT * FROM work_tasks WHERE id=?", (tid,)),
        inline_original=phase != "specification",
    )
    current = work.get(tid)
    code = "output_limit" if limited else "empty_model_response"
    assert current["status"] == "blocked" and current["session"]["error_code"] == code
    assert current["session"]["summary"] == "Saved greeting" and current["session"]["step"] == 1
    assert current["blocker"].startswith(code + ": ") and len(current["blocker"]) > len(code) + 30
    assert inference.calls == 1
    assert store.all("SELECT * FROM work_steps WHERE task_id=?", (tid,)) == before
    assert store.one("SELECT content FROM work_files WHERE task_id=?", (tid,))["content"] == "Hello"
    assert store.one("SELECT code FROM diagnostic_events ORDER BY id DESC LIMIT 1")["code"] == code
    assert not store.all("SELECT * FROM work_executions WHERE task_id=?", (tid,))
    from dsgpt.work_inference import recent

    attempt, = recent(store, tid)
    assert attempt["phase"] == {
        "image": "input_image", "inline_specification": "action"
    }.get(phase, phase)
    assert attempt["next_step"] == 2 and attempt["error_code"] == code
    assert attempt["context"]["input_tokens"] == 19
    assert attempt["metrics"]["thinking_chunks"] == 2
    assert attempt["output_bytes"] == len(reply.encode())
