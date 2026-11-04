"""Synthetic source retrieval/agent fixture for a real backend process-kill test."""

import argparse
import asyncio
import json
from pathlib import Path

import uvicorn

from dsgpt.api import create_app
from dsgpt.config import Model, Settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()

    class Reader:
        async def read(self, url):
            with (args.data / "reads.jsonl").open("a") as log:
                log.write(json.dumps(url) + "\n")
            if url.endswith("/second"):
                while not (args.data / "release-read").exists():
                    await asyncio.sleep(0.01)
            return {
                "url": url,
                "final_url": url,
                "title": "Process fixture",
                "text": "COBALT",
                "retrieved_at": "2026-10-19T00:00:00Z",
                "content_sha256": "a" * 64,
                "links": [],
            }

    class Agent:
        async def stream(self, model, messages, response_schema=None):
            step = json.loads(messages[1]["content"])["next_step"]
            action = {
                1: {"tool": "read_source", "source_id": "S2", "summary": "Read saved source"},
                2: {
                    "tool": "write_file",
                    "path": "reference.txt",
                    "content": "COBALT",
                    "summary": "Saved reference marker",
                },
            }.get(step, {"tool": "finish", "summary": "Draft complete after retrieval recovery"})
            yield {"kind": "delta", "data": {"text": json.dumps(action)}}

    model = Model("fixture", "Fixture", "ollama", "http://127.0.0.1:11434", "fixture")
    app = create_app(Settings(args.data, {model.id: model}), Agent())
    app.state.work.references.reader = Reader()
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
