"""Short chat questions must survive real adapter limits after public retrieval."""

import json
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest
from conftest import new_chat, wait_run
from test_inference import ollama_handler
from test_research import Reader

from dsgpt.inference import LocalInference, ollama_input_estimate


@pytest.mark.parametrize("context,output", [(4096, 1024), (8192, 1024), (8192, 4096)])
def test_small_research_question_fits_with_six_pages_and_validation_retry(backend, context, output):
    model = replace(
        backend.settings.models["test-na"],
        runtime_model="test:9b",
        context=context,
        output_tokens=output,
    )
    backend.settings.models[model.id] = model
    research = backend.app.state.research

    class LargeReader(Reader):
        async def read(self, url):
            source = await super().read(url)
            return source | {
                "title": "Résumé of the documented codename and its configuration. " * 5,
                "text": ('The documented codename is "COBALT".\\ Details: café.\n' * 1000),
            }

    payloads = []

    def handler(request):
        if request.url.path == "/api/chat":
            payload = json.loads(request.content)
            payloads.append(payload)
            # Exercise a repair prompt as well as the initial synthesis prompt.
            answer = (
                {
                    "findings": [
                        {"text": "The codename is COBALT.", "inference": False, "sources": ["S1"]}
                    ],
                    "limitations": [],
                }
                if len(payloads) % 3 == 0
                else {"invalid": True}
            )
            return httpx.Response(
                200,
                text=json.dumps({"message": {"content": json.dumps(answer)}, "done": False})
                + '\n{"message":{},"done":true}\n',
            )
        return ollama_handler(request)

    research.reader = LargeReader()
    research.inference = LocalInference(httpx.MockTransport(handler))
    urls = [f"https://example.org/source-{i}?tracking=" + "x" * 700 for i in range(6)]
    chat = new_chat(backend)
    for question in ("What is the documented codename?", "Please explain that answer."):
        run = backend.client.post(
            f"/v1/conversations/{chat}/messages",
            json={
                "request_id": str(uuid4()),
                "content": question,
                "model_id": model.id,
                "research": {"search": False, "urls": urls},
            },
        ).json()
        result = wait_run(backend, run["id"])
        assert result["status"] == "completed", result["error_code"]
        sources = research.sources(run["id"], True)
        assert len(sources) == 6 and all(len(s["text"]) > 20000 for s in sources)
        for payload in payloads[-3:]:
            assert ollama_input_estimate(payload["messages"]) + output <= context
            evidence = json.loads(payload["messages"][1]["content"])
            assert evidence["question"] == question
            assert all("COBALT" in s["excerpt"] for s in evidence["untrusted_evidence"])
        messages = backend.client.get(f"/v1/conversations/{chat}/messages").json()
        assert "COBALT" in messages[-1]["content"]
        assert f"[S1](<{urls[0]}>)" in messages[-1]["content"]
        event = backend.store.one(
            "SELECT payload FROM events WHERE run_id=? AND kind='research_context'", (run["id"],)
        )
        packing = json.loads(event["payload"])
        assert packing["retrieved_sources"] == 6
        assert packing["full_sources_retained"] and packing["question_preserved"]
        if packing["included_sources"] < 6:
            assert "of 6 retrieved pages" in messages[-1]["content"]
    assert len(research.reader.calls) == 12


def test_research_never_truncates_the_question_or_accepts_omitted_citations(backend):
    from dsgpt.research import answer_prompt
    from dsgpt.web_retrieval import ResearchError

    model = replace(backend.settings.models["test-na"], context=4096)
    mapping = {
        f"S{i + 1}": {
            "final_url": f"https://example.org/{i}",
            "title": "Reference " * 30,
            "published_at": "2026-01-01",
            "retrieved_at": "2026-01-02",
            "text": "COBALT is the documented codename. " * 200,
        }
        for i in range(6)
    }
    prompt, visible, report = answer_prompt(model, "What is the codename?", mapping)
    assert len(visible) < 6
    assert set(visible) == {s["id"] for s in json.loads(prompt[1]["content"])["untrusted_evidence"]}
    assert report["source_ids"] == list(visible)
    with pytest.raises(ResearchError, match="^context_exceeded$"):
        answer_prompt(model, "EXACT QUESTION " * 1000, mapping)


def test_prior_image_and_memory_cannot_overfill_a_short_chat_question(backend):
    from dsgpt.memory import chat_context

    model = backend.settings.models["test-na"]
    messages = [
        {"role": "user", "content": "An image", "images": ["placeholder-only-no-inference"]},
        {"role": "assistant", "content": "Previous answer. " * 125},
        {"role": "user", "content": "What about this?"},
    ]
    memory = [{"id": "m", "title": "Reference", "content": "Remember this. " * 90}]
    selected, _ = chat_context(model, messages, backend.app.state.memory, memory)
    assert selected[-1] == messages[-1]
    assert ollama_input_estimate(selected) + model.output_tokens <= model.context
