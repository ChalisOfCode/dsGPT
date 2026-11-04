"""Local deterministic integration fixture; never packaged into the running backend."""

import asyncio
import hashlib
import io
import json
import tempfile
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import uvicorn

import dsgpt.api
from dsgpt.api import create_app
from dsgpt.catalog import Asset
from dsgpt.config import Model, Settings
from dsgpt.history_archive import read_archive
from dsgpt.inference import InferenceError
from dsgpt.runtime_packages import RuntimeSpec, host_platform
from dsgpt.web_retrieval import ResearchError


class SlowInference:
    async def stream(self, model, messages, response_schema=None):
        if response_schema and "oneOf" in response_schema:
            await asyncio.sleep(2)
            context = json.loads(messages[1]["content"])
            action = (
                {
                    "tool": "write_file",
                    "summary": "Created the fixture source",
                    "path": "hello.txt",
                    "content": "Hello from the Work fixture\n",
                }
                if context["next_step"] == 1
                else {"tool": "finish", "summary": "Source drafting complete; no code was executed"}
            )
            if "reference_sources" in context:
                if any(s["status"] == "failed" for s in context["reference_sources"]["sources"]):
                    action = {"tool": "blocked", "summary": "Retry the failed fixture source"}
                elif context["progress"] == "Read fixture reference":
                    action = {
                        "tool": "write_file",
                        "path": "evidence.txt",
                        "content": "COBALT — https://example.org/reference\n",
                        "summary": "Created fixture reference draft",
                    }
                elif context["progress"] == "Created fixture reference draft":
                    action = {"tool": "finish", "summary": "Reference draft complete"}
                else:
                    action = {
                        "tool": "read_source",
                        "source_id": "S1",
                        "summary": "Read fixture reference",
                    }
            yield {"kind": "delta", "data": {"text": json.dumps(action)}}
            return
        if response_schema:
            yield {
                "kind": "delta",
                "data": {
                    "text": json.dumps(
                        {
                            "findings": [
                                {
                                    "text": "The documented codename is COBALT.",
                                    "inference": False,
                                    "sources": ["S1"],
                                }
                            ],
                            "limitations": [],
                        }
                    )
                },
            }
            return
        if "ATTACHMENT_OVERFLOW" in messages[-1]["content"]:
            raise InferenceError("context_exceeded")
        if "ATTACHMENT_MARKER_VIOLET" in messages[-1]["content"]:
            yield {"kind": "delta", "data": {"text": "Attachment marker: VIOLET"}}
            return
        for index in range(30):
            await asyncio.sleep(0.08)
            yield {"kind": "delta", "data": {"text": f"Word{index} "}}


class FixtureReader:
    def __init__(self):
        self.attempts = {}

    async def read(self, url):
        await asyncio.sleep(0.2)
        self.attempts[url] = self.attempts.get(url, 0) + 1
        if url.endswith("/missing") or (url.endswith("/retry") and self.attempts[url] == 1):
            raise ResearchError("research_source_inaccessible")
        return {
            "url": url,
            "final_url": url,
            "title": "<img src=x onerror=alert(1)> source title",
            "text": "The documented codename is COBALT. " + "é" * 4000,
            "links": [],
            "published_at": None,
            "retrieved_at": "2026-10-19T00:00:00Z",
            "content_sha256": "a" * 64,
            "text_truncated": False,
            "content_type": "text/html",
        }


class FixtureBytes(httpx.AsyncByteStream):
    def __init__(self, data):
        self.data = data

    async def __aiter__(self):
        for offset in range(0, len(self.data), 256 * 1024):
            await asyncio.sleep(0.35)
            yield self.data[offset : offset + 256 * 1024]


class FixtureRegistration:
    @asynccontextmanager
    async def client(self, model):
        yield None

    async def validate_local_model(self, client, model):
        return {"digest": "b" * 64, "bytes": 1024}


def setup_model_fixture(app):
    """Synthetic bytes exercise real transfer/install/registration state; never executed."""
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("llama-server", b"Not an executable; UI fixture only")
    payloads = {"ui-model": b"GGUF" + b"fixture " * (256 * 1024), "ui-runtime": archive.getvalue()}
    catalog = {}
    for key, data in payloads.items():
        is_model = key == "ui-model"
        catalog[key] = Asset(
            key,
            "UI model fixture" if is_model else "UI runtime fixture",
            "https://huggingface.co/test/test/resolve/" + "a" * 40 + "/test.gguf"
            if is_model
            else "https://github.com/ggml-org/llama.cpp/releases/download/b1/ui.zip",
            hashlib.sha256(data).hexdigest(),
            len(data),
            "Test fixture only",
            "https://example.org/fixture",
            "Synthetic UI verification; never run for inference",
            ".gguf" if is_model else ".zip",
            "model" if is_model else "runtime",
        )

    def handler(request):
        asset = next(a for a in catalog.values() if a.url == str(request.url))
        data = payloads[asset.id]
        start = int(request.headers.get("range", "bytes=0-")[6:-1])
        headers = {"content-length": str(len(data) - start)}
        if start:
            headers["content-range"] = f"bytes {start}-{len(data) - 1}/{len(data)}"
        return httpx.Response(
            206 if start else 200, headers=headers, stream=FixtureBytes(data[start:])
        )

    dsgpt.api.CATALOG = catalog
    app.state.downloads.catalog = catalog
    app.state.downloads.reserve = 0
    app.state.downloads.transport_factory = lambda: httpx.MockTransport(handler)
    app.state.runtime.packages.specs = {
        "ui-runtime": RuntimeSpec("ui-runtime", host_platform(), ("ui-runtime",), "llama-server")
    }
    app.state.models.validator = FixtureRegistration()


def main():
    with tempfile.TemporaryDirectory(prefix="dsgpt-ui-test-") as directory:
        model = Model("test-na", "Integration model", "ollama", "http://127.0.0.1:11434", "test")
        app = create_app(
            Settings(
                Path(directory), {model.id: model}, allowed_origins=("http://127.0.0.1:1420",)
            ),
            SlowInference(),
        )
        # UI fixtures must not provision real Docker tools when CI happens to have
        # Docker installed. Auto-target tasks block deterministically; real toolchain
        # setup is exercised by the separate acceptance workflows.
        app.state.work.tool_setup = None
        credential = app.state.auth.initialize_owner()["token"]
        app.state.research.reader = FixtureReader()
        app.state.work.references.reader = FixtureReader()
        setup_model_fixture(app)

        def search_response(request):
            # Synthetic local service: never sends a query outside the test process.
            payload = (
                {"results": [{"url": "https://example.org/doc", "title": "Fixture result"}]}
                if request.url.port == 8888
                else {"results": [], "unresponsive_engines": [["fixture", "timeout"]]}
            )
            return httpx.Response(200, stream=FixtureBytes(json.dumps(payload).encode()))

        app.state.research.search.transport_factory = lambda: httpx.MockTransport(search_response)

        @app.get("/test-credential")
        def test_credential():
            return {"token": credential}

        @app.post("/test-history-import")
        def test_history_import():
            # Synthetic fixture only; no export-upload endpoint exists in production.
            from dsgpt.storage import uid

            sample = [
                {
                    "id": "browser-import-source",
                    "title": "Imported garden notes",
                    "create_time": 1700000000,
                    "update_time": 1700000010,
                    "current_node": "b",
                    "mapping": {
                        "a": {
                            "parent": None,
                            "message": {
                                "author": {"role": "user"},
                                "create_time": 1700000001,
                                "content": {
                                    "content_type": "text",
                                    "parts": ["SAPPHIRE garden <svg onload=alert(1)>"],
                                },
                            },
                        },
                        "b": {
                            "parent": "a",
                            "message": {
                                "author": {"role": "assistant"},
                                "create_time": 1700000002,
                                "content": {
                                    "content_type": "text",
                                    "parts": ["Saved original reply."],
                                },
                            },
                        },
                    },
                }
            ]
            path = Path(directory) / "synthetic-export.json"
            path.write_text(json.dumps(sample))
            value = read_archive(path)
            return app.state.history.apply(value, uid(), value["archive_sha256"])

        uvicorn.run(app, host="127.0.0.1", port=8766, access_log=False)


if __name__ == "__main__":
    main()
