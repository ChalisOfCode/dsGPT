import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx

from dsgpt.security import Auth
from dsgpt.storage import Store


def test_actual_process_kill_preserves_accepted_attachment_and_removal_receipt(tmp_path):
    owner = Auth(Store(tmp_path)).initialize_owner()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    command = [
        sys.executable,
        str(Path(__file__).resolve().parents[1] / "scripts/attachment_recovery_fixture.py"),
        "--data",
        str(tmp_path),
        "--port",
        str(port),
    ]
    child = None
    try:
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}",
            trust_env=False,
            timeout=3,
            headers={"Authorization": "Bearer " + owner["token"]},
        ) as client:

            def wait(path, check):
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    try:
                        response = client.get(path)
                        if response.status_code == 200 and check(response.json()):
                            return response.json()
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.02)
                raise AssertionError("Attachment recovery state not reached")

            def start():
                process = subprocess.Popen(
                    command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                wait("/health", lambda _: True)
                return process

            child = start()
            chat = client.post("/v1/conversations", json={"title": "Attachment recovery"}).json()[
                "id"
            ]
            endpoint = f"/v1/conversations/{chat}/messages"
            body = {
                "request_id": str(uuid4()),
                "content": "Read the file",
                "model_id": "fixture",
                "attachments": [{"name": "private.txt", "text": "RECOVERED_ATTACHMENT_RUBY"}],
            }
            assert client.post(endpoint, json=body).status_code == 202
            wait("/v1/runs/" + body["request_id"], lambda r: r["status"] == "running")
            before = client.get(endpoint).json()[0]["attachments"]
            child.kill()
            child.wait(timeout=5)
            child = start()
            assert client.get("/v1/runs/" + body["request_id"]).json()["status"] == "interrupted"
            assert client.get(endpoint).json()[0]["attachments"] == before
            assert client.post(endpoint, json=body).json()["status"] == "interrupted"
            (tmp_path / "release-inference").write_text("release fixture")
            next_id = str(uuid4())
            client.post(
                endpoint,
                json={
                    "request_id": next_id,
                    "content": "Read the same file again",
                    "model_id": "fixture",
                },
            ).raise_for_status()
            wait("/v1/runs/" + next_id, lambda r: r["status"] == "completed")
            assert client.get(endpoint).json()[-1]["content"] == "RUBY"
            file_path = f"/v1/conversations/{chat}/attachments/{before[0]['id']}"
            client.delete(file_path).raise_for_status()
            child.kill()
            child.wait(timeout=5)
            child = start()
            assert client.post(endpoint, json=body).json()["status"] == "interrupted"
            assert client.get(file_path).status_code == 410
            messages = client.get(endpoint).json()
            assert messages[0]["attachments"][0]["removed"] and len(messages) == 4
            assert len(Store(tmp_path).all("SELECT * FROM message_attachments")) == 1
    finally:
        if child and child.poll() is None:
            child.terminate()
            child.wait(timeout=10)
