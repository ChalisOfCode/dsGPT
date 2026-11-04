import base64
import json
import subprocess
from pathlib import Path

import pytest
from conftest import new_chat, pair, wait_run
from test_attachments import records, submit

from dsgpt import document_worker
from dsgpt.attachments import Attachments
from dsgpt.config import Model
from dsgpt.inference import InferenceError, LocalInference

SAMPLES = json.loads((Path(__file__).parent / "fixtures/document-samples.json").read_text())


class DocumentFixture:
    """Deterministic transport boundary fixture; real isolation is tested separately in CI."""

    async def execute(self, identifier, files, argv, artifacts, timeout):
        request = json.loads(files[0]["content"])
        assert argv == ["/usr/bin/python3", "-I", "worker.py"]
        assert artifacts == ["result.json"] and timeout == 120
        image = request["extension"] in {"png", "jpg", "webp"}
        body = json.dumps(
            {
                "text": "PRIVATE ORCHID",
                "pages": [{"page": 1, "method": "ocr"}],
                "format": request["extension"],
                "image": image,
                "dimensions": [900, 180],
            }
        )
        return {"exit_code": 0, "artifacts": [{"content": body.encode()}]}


def tools(backend):
    builds = backend.app.state.builds
    builds.sandbox = DocumentFixture()
    builds.ready = True
    return builds


@pytest.mark.parametrize("name", list(SAMPLES))
def test_preview_preservation_scoping_and_original_download(backend, name):
    tools(backend)
    body = {"name": name, "original_base64": SAMPLES[name]}
    preview = backend.client.post("/v1/documents/preview", json=body)
    assert preview.status_code == 200, preview.text
    assert preview.json()["document"]["pages"][0]["page"] == 1
    assert "original_base64" not in preview.json()
    chat = new_chat(backend)
    result = submit(backend, chat, [body])
    assert result.status_code == 202, result.text
    wait_run(backend, result.json()["id"])
    meta = records(backend, chat)[0]["attachments"][0]
    endpoint = f"/v1/conversations/{chat}/attachments/{meta['id']}"
    assert backend.client.get(endpoint + "/download").content == base64.b64decode(SAMPLES[name])
    rows = backend.store.all(
        "SELECT * FROM messages WHERE conversation_id=? ORDER BY ordinal", (chat,)
    )
    model = Model("vision", "Vision", "ollama", "http://127.0.0.1:11434", "local", context=16384)
    context, _ = Attachments(backend.store).context(rows[:1], model)
    assert bool(context[0].get("images")) == (name in {"image.png", "image.jpg", "image.webp"})
    assert backend.client.delete(endpoint).status_code == 200
    context, _ = Attachments(backend.store).context(rows[:1], model)
    assert not context[0].get("images")
    assert backend.client.get(endpoint + "/download").status_code == 410


def test_unconfigured_tools_and_permission_are_explicit(backend):
    body = {"name": "scan.pdf", "original_base64": SAMPLES["scan.pdf"]}
    response = backend.client.post("/v1/documents/preview", json=body)
    assert response.status_code == 409 and "document_tools_not_ready" in response.text
    phone, _ = pair(backend, ["work"])
    response = backend.client.post(
        "/v1/documents/preview", json=body, headers={"Authorization": "Bearer " + phone["token"]}
    )
    assert response.status_code == 403
    assert not backend.store.all("SELECT * FROM message_attachments")


@pytest.mark.parametrize(
    "name,marker", [(name, "COBALT" if name == "text.pdf" else "ORCHID") for name in SAMPLES]
)
def test_actual_decoder_on_generated_fixtures(tmp_path, name, marker):
    # Synthetic local fixture only. Production is exclusively DockerSandbox.execute.
    (tmp_path / "request.json").write_text(
        json.dumps({"extension": name.split(".")[-1], "original_base64": SAMPLES[name]})
    )
    result = subprocess.run(
        ["/usr/bin/python3", "-I", document_worker.__file__],
        cwd=tmp_path,
        capture_output=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    result = json.loads((tmp_path / "result.json").read_text())
    assert "error" not in result, result
    assert marker in result["text"]
    assert result["pages"][0]["method"] == (
        "text" if name in {"text.pdf", "sheet.xlsx", "deck.pptx"} else "ocr"
    )


async def test_vision_request_never_silently_uses_text_only_model():
    import httpx

    seen = []

    def handler(request):
        seen.append(request.url.path)
        if request.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": "local", "size": 100, "digest": "abc"}]}
            )
        return httpx.Response(
            200, json={"model_info": {"architecture": "test"}, "capabilities": ["completion"]}
        )

    adapter = LocalInference(httpx.MockTransport(handler))
    model = Model("vision", "Vision", "ollama", "http://127.0.0.1:11434", "local", context=16384)
    with pytest.raises(InferenceError, match="local_vision_model_required"):
        _ = [
            x
            async for x in adapter.stream(
                model, [{"role": "user", "content": "Describe", "images": [SAMPLES["image.png"]]}]
            )
        ]
    assert "/api/chat" not in seen


async def test_public_pdf_uses_offline_processor_and_preserves_source_hash(backend):
    import hashlib

    import httpx
    from test_web_retrieval import Bytes

    from dsgpt.document_processing import DocumentProcessor
    from dsgpt.web_retrieval import PublicReader

    raw = base64.b64decode(SAMPLES["scan.pdf"])
    requests = []

    def respond(request):
        requests.append(request)
        assert not request.headers.get("authorization") and not request.headers.get("cookie")
        return httpx.Response(200, headers={"Content-Type": "application/pdf"}, stream=Bytes(raw))

    reader = PublicReader(
        lambda: httpx.MockTransport(respond), DocumentProcessor(backend.store, tools(backend))
    )
    result = await reader.read("https://example.org/scan.pdf")
    assert result["text"] == "PRIVATE ORCHID"
    assert result["extraction"]["pages"][0]["method"] == "ocr"
    assert result["content_sha256"] == hashlib.sha256(raw).hexdigest()
    assert result["final_url"] == "https://example.org/scan.pdf" and len(requests) == 1
    assert not backend.store.all("SELECT * FROM message_attachments")


async def test_vision_pixels_reach_only_verified_local_ollama():
    import httpx

    seen = []

    def respond(request):
        assert request.url.host == "127.0.0.1"
        if request.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": "local", "size": 100, "digest": "abc"}]}
            )
        if request.url.path == "/api/show":
            return httpx.Response(
                200,
                json={
                    "model_info": {"architecture": "fixture"},
                    "capabilities": ["vision", "completion"],
                },
            )
        seen.append(json.loads(request.content))
        return httpx.Response(
            200, text=json.dumps({"message": {"content": "Observed image"}, "done": True}) + "\n"
        )

    adapter = LocalInference(httpx.MockTransport(respond))
    model = Model("vision", "Vision", "ollama", "http://127.0.0.1:11434", "local", context=16384)
    events = [
        e
        async for e in adapter.stream(
            model, [{"role": "user", "content": "Describe", "images": [SAMPLES["image.png"]]}]
        )
    ]
    assert seen[0]["messages"][0]["images"] == [SAMPLES["image.png"]]
    assert seen[0]["keep_alive"] == "5m"
    assert any(e["kind"] == "delta" for e in events)
