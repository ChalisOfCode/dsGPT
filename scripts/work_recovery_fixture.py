"""Deterministic subprocess fixture for crash recovery; no production credential route."""

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

    class Fixture:
        async def stream(self, model, messages, response_schema=None):
            if response_schema:
                context = json.loads(messages[1]["content"])
                if context["next_step"] == 1:
                    value = {
                        "tool": "write_file",
                        "path": "marker.py",
                        "content": "marker = 1\n",
                        "summary": "marker.py committed; finish next",
                    }
                else:
                    while not (args.data / "release-fixture").exists():
                        await asyncio.sleep(0.01)
                    value = {"tool": "finish", "summary": "Draft retained after restart"}
                text = json.dumps(value)
            else:
                text = "Recovered chat"
            yield {"kind": "delta", "data": {"text": text}}

    model = Model("fixture", "Fixture", "ollama", "http://127.0.0.1:11434", "fixture")
    app = create_app(Settings(args.data, {model.id: model}), Fixture())
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
