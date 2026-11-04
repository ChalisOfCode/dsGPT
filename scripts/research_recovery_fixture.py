"""TEST ONLY: deterministic local HTTP pages and synthesis for process-recovery testing."""

import argparse
import json
from pathlib import Path

import httpx
import uvicorn

from dsgpt.api import create_app
from dsgpt.config import Model, Settings
from dsgpt.web_retrieval import PublicReader, local_search_origin


class FixtureTransport(httpx.AsyncBaseTransport):
    def __init__(self, origin):
        self.origin = httpx.URL(local_search_origin(origin))
        self.pool = httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request):
        target = request.url.copy_with(scheme="http", host=self.origin.host, port=self.origin.port)
        return await self.pool.handle_async_request(
            httpx.Request(
                request.method,
                target,
                headers=request.headers,
                stream=request.stream,
                extensions=request.extensions,
            )
        )

    async def aclose(self):
        await self.pool.aclose()


class FixtureInference:
    async def stream(self, model, messages, response_schema=None):
        answer = {
            "findings": [
                {
                    "text": "The documented codename is COBALT.",
                    "inference": False,
                    "sources": ["S1"],
                }
            ],
            "limitations": [],
        }
        yield {"kind": "delta", "data": {"text": json.dumps(answer)}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--pages-origin", required=True)
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args()
    model = Model("fixture", "Fixture", "llama.cpp", "http://127.0.0.1:18081", "fixture")
    app = create_app(Settings(args.data, {model.id: model}), FixtureInference())
    app.state.research.reader = PublicReader(lambda: FixtureTransport(args.pages_origin))
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False, proxy_headers=False)


if __name__ == "__main__":
    main()
