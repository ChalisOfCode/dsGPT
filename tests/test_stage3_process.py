import json
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx

from dsgpt.security import Auth
from dsgpt.storage import Store


def test_real_process_kill_preserves_file_and_recovers_queued_chat(tmp_path):
    credentials = Auth(Store(tmp_path)).initialize_owner()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    command = [
        sys.executable,
        str(Path(__file__).resolve().parents[1] / "scripts/work_recovery_fixture.py"),
        "--data",
        str(tmp_path),
        "--port",
        str(port),
    ]
    process = None
    client = httpx.Client(
        base_url=f"http://127.0.0.1:{port}",
        trust_env=False,
        timeout=2,
        headers={"Authorization": "Bearer " + credentials["token"]},
    )

    def ready():
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                if client.get("/health").status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.03)
        raise AssertionError("Subprocess did not start")

    def wait(path, check):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            row = client.get(path).json()
            if check(row):
                return row
            time.sleep(0.01)
        raise AssertionError("Subprocess state not reached")

    try:
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ready()
        task = client.post(
            "/v1/work/tasks",
            json={"title": "Recovery", "requirements": "Draft marker.py", "model_id": "fixture"},
        ).json()
        tid = task["id"]
        client.post(
            f"/v1/work/tasks/{tid}/actions", json={"action": "start", "revision": 1}
        ).raise_for_status()
        wait(
            f"/v1/work/tasks/{tid}",
            lambda r: r["status"] == "running" and r["session"]["step"] == 1,
        )
        chat = client.post("/v1/conversations", json={"title": "Queued during Work"}).json()
        run = client.post(
            f"/v1/conversations/{chat['id']}/messages",
            json={"request_id": str(uuid4()), "content": "Continue", "model_id": "fixture"},
        ).json()
        assert run["status"] == "queued"
        process.kill()
        process.wait(timeout=5)
        (tmp_path / "release-fixture").write_text("resume synthetic fixture")
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ready()
        task = wait(f"/v1/work/tasks/{tid}", lambda r: r["status"] == "completed")
        wait(f"/v1/runs/{run['id']}", lambda r: r["status"] == "completed")
        assert task["session"]["step"] == 2
        files = client.get(f"/v1/work/tasks/{tid}/files").json()
        assert len(files) == 1 and files[0]["revision"] == 1
        steps = client.get(f"/v1/work/tasks/{tid}/steps").json()
        assert [s["action"]["tool"] for s in steps] == ["write_file", "finish"]
    finally:
        client.close()
        if process and process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


def test_process_kill_retries_only_uncommitted_work_reference(tmp_path):
    credentials = Auth(Store(tmp_path)).initialize_owner()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    command = [
        sys.executable,
        str(Path(__file__).resolve().parents[1] / "scripts/work_reference_recovery_fixture.py"),
        "--data",
        str(tmp_path),
        "--port",
        str(port),
    ]
    process = None
    client = httpx.Client(
        base_url=f"http://127.0.0.1:{port}",
        trust_env=False,
        timeout=2,
        headers={"Authorization": "Bearer " + credentials["token"]},
    )

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
        raise AssertionError("Process reference state not reached")

    try:
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wait("/health", lambda _: True)
        urls = ["https://example.org/first", "https://example.org/second"]
        created = client.post(
            "/v1/work/tasks",
            json={
                "title": "Reference recovery",
                "requirements": "Read S2 then draft reference.txt with its marker.",
                "model_id": "fixture",
                "reference_urls": urls,
            },
        )
        created.raise_for_status()
        task_id = created.json()["id"]
        path = f"/v1/work/tasks/{task_id}"
        client.post(path + "/actions", json={"action": "start", "revision": 1}).raise_for_status()
        wait(path, lambda t: t["references"]["retrieved"] == 1 and t["status"] == "running")
        deadline = time.monotonic() + 5
        while len((tmp_path / "reads.jsonl").read_text().splitlines()) < 2:
            assert time.monotonic() < deadline
            time.sleep(0.01)
        before = client.get(path + "/sources").json()
        assert [s["status"] for s in before] == ["retrieved", "pending"]
        process.kill()
        process.wait(timeout=5)
        (tmp_path / "release-read").write_text("Continue only the interrupted synthetic GET")
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        task = wait(path, lambda t: t["status"] == "completed")
        after = client.get(path + "/sources").json()
        assert task["session"]["step"] == 3
        assert task["references"] == {"total": 2, "pending": 0, "retrieved": 2, "failed": 0}
        assert after[0] == before[0]
        reads = [json.loads(line) for line in (tmp_path / "reads.jsonl").read_text().splitlines()]
        assert reads == [urls[0], urls[1], urls[1]]
        checkpoints = client.get(path + "/checkpoints").json()
        retrievals = [c for c in checkpoints if c["state"].get("action") == "reference_retrieval"]
        assert [c["state"]["source_id"] for c in retrievals] == ["S1", "S2"]
        steps = client.get(path + "/steps").json()
        assert [s["action"]["tool"] for s in steps] == ["read_source", "write_file", "finish"]
        assert steps[0]["result"]["text"] == "COBALT"
    finally:
        client.close()
        if process and process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
