"""Real isolated Chromium interaction, screenshot and network-denial evidence."""

import argparse
import asyncio
import json
import tempfile
from pathlib import Path

import httpx

from dsgpt.builds import WorkBuilds
from dsgpt.project_tools import ProjectAction, ProjectTools
from dsgpt.public_browser import PublicBrowser
from dsgpt.storage import Store
from dsgpt.work import WorkRegistry

PAGE = """<!doctype html><title>Isolated browser fixture</title>
<input id="name"><button id="go" onclick="
document.querySelector('#result').textContent='Hello '+
document.querySelector('#name').value">Greet</button>
<p id="result">Waiting</p><p id="network">Pending</p>
<script>fetch('https://example.com/', {signal:AbortSignal.timeout(2000)}).then(()=>{
document.querySelector('#network').textContent='NETWORK ESCAPE'}).catch(()=>{
document.querySelector('#network').textContent='NETWORK BLOCKED'})</script>"""


async def main(args):
    report = {"image": args.image}
    with tempfile.TemporaryDirectory(prefix="dsgpt-browser-") as directory:
        store = Store(Path(directory))
        task = WorkRegistry(store).create("UI fixture", "Test interaction", build_target="files")
        with store.transaction() as db:
            db.execute("UPDATE work_tasks SET status='running' WHERE id=?", (task["id"],))
            ProjectTools.apply(
                db,
                task["id"],
                ProjectAction(
                    tool="write_file", path="index.html", content=PAGE, summary="Fixture"
                ),
            )
        builds = WorkBuilds(store, image=args.image)
        report["isolation"] = await builds.probe()
        action = ProjectAction(
            tool="browser",
            path="index.html",
            summary="Interact",
            browser_steps=[
                {"action": "type", "selector": "#name", "text": "ORCHID742"},
                {"action": "click", "selector": "#go"},
            ],
        )
        result = await builds.execute(task["id"], 1, action)
        assert "error" not in result, result
        artifacts = store.all(
            "SELECT path,content FROM work_artifacts WHERE task_id=?", (task["id"],)
        )
        image = next(a["content"] for a in artifacts if a["path"].endswith(".png"))
        assert image.startswith(b"\x89PNG\r\n\x1a\n") and len(image) > 1000
        page = json.loads(next(a["content"] for a in artifacts if a["path"].endswith(".json")))
        assert "Hello ORCHID742" in page["text"], page
        assert "NETWORK ESCAPE" not in page["text"]
        assert len(page["steps"]) == 2
        assert not store.all("SELECT * FROM work_executions WHERE cleanup_pending=1")
        report.update(passed=True, screenshot_bytes=len(image), page=page)
        args.output.with_suffix(".png").write_bytes(image)
        seen = []

        class Body(httpx.AsyncByteStream):
            def __init__(self, value):
                self.value = value

            async def __aiter__(self):
                yield self.value

        def resource(request):
            seen.append(str(request.url))
            assert request.method == "GET" and request.url.host == "example.org"
            assert not request.headers.get("cookie") and not request.headers.get("authorization")
            if request.url.path == "/start":
                return httpx.Response(302, headers={"Location": "/app/index.html"})
            if request.url.path == "/app/index.html":
                return httpx.Response(
                    200,
                    headers={"Content-Type": "text/html"},
                    stream=Body(
                        b'<title>Public fixture</title><body><p id="result">Loading</p>'
                        b'<script src="app.js"></script></body>'
                    ),
                )
            if request.url.path == "/app/app.js":
                script = """Promise.all([
                fetch('data.json').then(r=>r.json()),
                fetch('https://127.0.0.1/private').then(()=>false).catch(()=>true),
                fetch('https://example.org/write',{method:'POST',body:'private'}).then(()=>false).catch(()=>true)
                ]).then(([data,privateBlocked,postBlocked])=>{
                document.querySelector('#result').textContent=data.message+
                ' PRIVATE_BLOCKED='+privateBlocked+' POST_BLOCKED='+postBlocked;
                });"""
                return httpx.Response(
                    200,
                    headers={"Content-Type": "application/javascript"},
                    stream=Body(script.encode()),
                )
            if request.url.path == "/app/data.json":
                return httpx.Response(
                    200,
                    headers={"Content-Type": "application/json"},
                    stream=Body(b'{"message":"DYNAMIC ORCHID742"}'),
                )
            return httpx.Response(404)

        rendered = await PublicBrowser(store, builds, lambda: httpx.MockTransport(resource)).render(
            "https://example.org/start"
        )
        assert "DYNAMIC ORCHID742" in rendered["text"], rendered
        assert "PRIVATE_BLOCKED=true" in rendered["text"], rendered
        assert "POST_BLOCKED=true" in rendered["text"], rendered
        assert rendered["final_url"] == "https://example.org/app/index.html", rendered
        assert not any("/write" in url or "127.0.0.1" in url for url in seen), seen
        assert not store.all("SELECT * FROM work_executions WHERE cleanup_pending=1")
        report["public_dynamic_rendering"] = rendered
        report["private_and_post_requests_blocked"] = True
    args.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(main(parser.parse_args()))
