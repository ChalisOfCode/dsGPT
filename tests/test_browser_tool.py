import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_builds import SandboxFixture, request_start
from test_stage3_work import AgentFixture, setup, wait_task

from dsgpt.project_tools import ProjectAction, action_schema


def test_browser_tool_runs_only_in_sandbox_and_keeps_artifacts(tmp_path):
    agent = AgentFixture(
        [
            {
                "tool": "write_file",
                "path": "index.html",
                "content": "<button>Test</button>",
                "summary": "Draft",
            },
            {
                "tool": "browser",
                "path": "index.html",
                "browser_steps": [{"action": "click", "selector": "button"}],
                "summary": "Inspect UI",
            },
            {"tool": "finish", "summary": "Inspected fixture"},
        ]
    )
    app, _, headers = setup(tmp_path, agent)
    sandbox = SandboxFixture()
    app.state.builds.sandbox = sandbox
    with TestClient(app, headers=headers) as client:
        assert client.post("/v1/work/sandbox/probe").json()["ready"]
        identifier = request_start(client)
        task = wait_task(client, identifier)
        assert task["status"] == "completed", task
        call = sandbox.calls[0]
        assert call[2] == ["/usr/bin/python3", "-I", ".dsgpt-browser/worker.py"]
        request = json.loads(
            next(f["content"] for f in call[1] if f["path"].endswith("request.json"))
        )
        assert request["steps"][0]["selector"] == "button"
        assert call[3] == [".dsgpt-browser/screenshot.png", ".dsgpt-browser/result.json"]
        assert call[4] == 60
        files = client.get(f"/v1/work/tasks/{identifier}/files").json()
        assert len(files) == 1 and files[0]["path"] == "index.html"
        assert len(client.get(f"/v1/work/tasks/{identifier}/artifacts").json()) == 2


def test_browser_schema_and_paths_restrict_capability():
    assert "browser" not in str(action_schema())
    assert any(
        v["properties"]["tool"]["const"] == "browser"
        for v in action_schema(isolated_execution=True)["oneOf"]
    )
    for path in ["../private.html", "/host/private.html", "https://example.com"]:
        with pytest.raises(ValidationError):
            ProjectAction(tool="browser", path=path, summary="Invalid")
    with pytest.raises(ValidationError):
        ProjectAction(
            tool="browser",
            path="index.html",
            summary="Invalid",
            browser_steps=[{"action": "shell", "selector": "button"}],
        )
