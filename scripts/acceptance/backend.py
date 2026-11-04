import asyncio
import json
from pathlib import Path

import uvicorn

from dsgpt.api import create_app
from dsgpt.config import Model, Settings
from dsgpt.inference import LocalInference


class AcceptanceInference:
    """Fixtures test application behavior; other model IDs use real local inference."""

    async def stream(self, model, messages, response_schema=None):
        if model.id != "acceptance-fixture":
            async for item in LocalInference().stream(model, messages, response_schema):
                yield item
            return
        if response_schema:
            action = {"tool": "finish", "summary": "Acceptance fixture; no LLM quality claim"}
            yield {"kind": "delta", "data": {"text": json.dumps(action)}}
            return
        for _ in range(40):
            await asyncio.sleep(0.1)
            yield {"kind": "delta", "data": {"text": "ACCEPTANCE "}}


def serve(config_path):
    config = json.loads(Path(config_path).read_text())
    models = {v["id"]: Model(**v) for v in config["models"]}
    app = create_app(
        Settings(
            Path(config["data"]),
            models,
            allowed_hosts=tuple(config["hosts"]),
            sandbox_image=config.get("image"),
        ),
        AcceptanceInference(),
    )
    uvicorn.run(app, host="127.0.0.1", port=config["port"], access_log=False, log_level="error")
