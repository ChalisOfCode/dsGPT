"""Production backend and real loopback HTTP; synthetic SearXNG JSON, no public engines."""

import json
import socket
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

import httpx
import pytest

from dsgpt.search_settings import TEST_QUERY
from dsgpt.security import Auth
from dsgpt.storage import Store


def test_real_http_search_and_backend_kill_preserve_settings_without_query_replay(tmp_path):
    calls, gate, started = [], threading.Event(), threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            calls.append(
                (
                    self.path,
                    dict(self.headers),
                    self.rfile.read(int(self.headers["Content-Length"])),
                )
            )
            if len(calls) == 2:
                started.set()
                gate.wait(10)
            data = json.dumps(
                {
                    "results": [
                        {
                            "url": "https://example.org/search",
                            "content": "Never persist this snippet",
                        }
                    ]
                }
            ).encode()
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

    service = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=service.serve_forever, daemon=True)
    worker.start()
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    owner = Auth(Store(tmp_path / "data")).initialize_owner()
    command = [
        sys.executable,
        "-m",
        "dsgpt.cli",
        "serve",
        "--data-dir",
        str(tmp_path / "data"),
        "--port",
        str(port),
    ]
    child = None
    try:
        with (
            (tmp_path / "backend.log").open("w") as log,
            httpx.Client(
                base_url=f"http://127.0.0.1:{port}",
                trust_env=False,
                timeout=5,
                headers={"Authorization": "Bearer " + owner["token"]},
            ) as client,
        ):

            def start():
                process = subprocess.Popen(command, stdout=log, stderr=log)
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    assert process.poll() is None, (tmp_path / "backend.log").read_text()
                    try:
                        if client.get("/health").status_code == 200:
                            return process
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.03)
                process.terminate()
                process.wait(timeout=5)
                raise AssertionError("Search backend did not start")

            child = start()
            address = f"http://127.0.0.1:{service.server_port}"
            saved = client.put("/v1/research/settings", json={"origin": address, "revision": 0})
            assert saved.status_code == 200 and not calls
            tested = client.post("/v1/research/check", json={"revision": 1}).json()
            assert tested["last_check"]["status"] == "passed"
            assert len(calls) == 1
            path, headers, body = calls[0]
            assert path == "/search" and parse_qs(body.decode()) == {
                "q": [TEST_QUERY],
                "format": ["json"],
            }
            assert not {"authorization", "cookie"} & {key.lower() for key in headers}
            assert "Never persist" not in json.dumps(tested)
            with ThreadPoolExecutor() as pool:
                interrupted = pool.submit(
                    lambda: client.post("/v1/research/check", json={"revision": 1})
                )
                assert started.wait(5)
                assert client.get("/v1/research/settings").json()["check_in_progress"]
                child.kill()
                child.wait(timeout=5)
                gate.set()
                with pytest.raises(httpx.HTTPError):
                    interrupted.result(timeout=5)
            child = start()
            restored = client.get("/v1/research/settings").json()
            assert restored["origin"] == address and restored["revision"] == 1
            assert restored["last_check"] == tested["last_check"]
            assert not restored["check_in_progress"] and len(calls) == 2
            assert client.get("/v1/research/capabilities").json()["search_configured"]
            assert (
                client.put(
                    "/v1/research/settings", json={"origin": None, "revision": 0}
                ).status_code
                == 409
            )
            assert (
                client.put("/v1/research/settings", json={"origin": None, "revision": 1}).json()[
                    "last_check"
                ]
                is None
            )
            assert len(calls) == 2
    finally:
        gate.set()
        if child and child.poll() is None:
            child.terminate()
            child.wait(timeout=10)
        service.shutdown()
        service.server_close()
        worker.join(timeout=2)
