"""Synthetic local inference for real-process attachment acceptance/recovery tests."""

import argparse
import asyncio
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
            (args.data / "inference-started").write_text("started")
            while not (args.data / "release-inference").exists():
                await asyncio.sleep(0.01)
            text = (
                "RUBY"
                if any("RECOVERED_ATTACHMENT_RUBY" in m["content"] for m in messages)
                else "No saved marker"
            )
            yield {"kind": "delta", "data": {"text": text}}

    model = Model("fixture", "Fixture", "ollama", "http://127.0.0.1:11434", "fixture")
    app = create_app(Settings(args.data, {model.id: model}), Fixture())
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
