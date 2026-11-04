import json
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import httpx

from dsgpt.security import Auth
from dsgpt.storage import Store


def test_actual_backend_kill_preserves_first_research_source_and_resumes_pending_source(tmp_path):
    counts, gate = {"/a": 0, "/b": 0}, threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            counts[self.path] += 1
            data = b"<title>Fixture source</title><p>The documented codename is COBALT.</p>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if self.path == "/b" and counts["/b"] == 1:
                gate.wait(20)
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

    pages = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=pages.serve_forever, daemon=True)
    thread.start()
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    root = Path(__file__).resolve().parents[1]
    store = Store(tmp_path / "data")
    owner = Auth(store).initialize_owner()
    command = [
        sys.executable,
        str(root / "scripts/research_recovery_fixture.py"),
        "--data",
        str(store.directory),
        "--pages-origin",
        f"http://127.0.0.1:{pages.server_port}",
        "--port",
        str(port),
    ]
    child = None

    def wait(predicate):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            value = predicate()
            if value:
                return value
            time.sleep(0.02)
        raise AssertionError("Research recovery timed out")

    try:
        with (
            (tmp_path / "backend.log").open("w") as log,
            httpx.Client(
                base_url=f"http://127.0.0.1:{port}",
                trust_env=False,
                timeout=3,
                headers={"Authorization": "Bearer " + owner["token"]},
            ) as client,
        ):

            def start():
                process = subprocess.Popen(command, stdout=log, stderr=log)

                def ready():
                    assert process.poll() is None, (tmp_path / "backend.log").read_text()
                    try:
                        return client.get("/health").status_code == 200
                    except httpx.HTTPError:
                        return False

                wait(ready)
                return process

            child = start()
            chat = client.post("/v1/conversations", json={"title": "Recovery"}).json()
            identifier = str(uuid4())
            response = client.post(
                f"/v1/conversations/{chat['id']}/messages",
                json={
                    "request_id": identifier,
                    "content": "What is the documented codename?",
                    "model_id": "fixture",
                    "research": {
                        "search": False,
                        "urls": ["https://example.org/a", "https://example.org/b"],
                    },
                },
            )
            assert response.status_code == 202
            wait(
                lambda: (
                    counts["/b"] == 1
                    and store.one("SELECT id FROM web_sources WHERE status='retrieved'")
                )
            )
            first = store.one("SELECT document FROM web_sources WHERE status='retrieved'")[
                "document"
            ]
            child.kill()
            child.wait(timeout=5)
            gate.set()
            child = start()

            def finished():
                run = client.get("/v1/runs/" + identifier).json()
                return run if run["status"] in {"completed", "failed"} else None

            run = wait(finished)
            assert run["status"] == "completed", run
            assert counts == {"/a": 1, "/b": 2}
            assert (
                store.one("SELECT document FROM web_sources WHERE url LIKE '%/a'")["document"]
                == first
            )
            assert json.loads(first)["content_sha256"]
            assert len(store.all("SELECT * FROM web_sources")) == 2
    finally:
        gate.set()
        if child and child.poll() is None:
            child.terminate()
            child.wait(timeout=10)
        pages.shutdown()
        pages.server_close()
        thread.join(timeout=2)
