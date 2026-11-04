"""Exercise actual local inference through dsGPT's Work scheduler and memory retrieval.

The tiny CPU fixture is an integration test, not a target-model quality benchmark.
"""

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import httpx

from dsgpt.security import Auth
from dsgpt.storage import Store, utcnow


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--expected-sha256",
        default="9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031",
    )
    args = parser.parse_args()
    args.output.with_suffix(".zip").unlink(missing_ok=True)
    report = {
        "started_at": utcnow(),
        "actual_local_inference": True,
        "target_gpu_tested": False,
        "model": args.model.name + " CPU fixture",
        "checks": {},
    }
    source_root = Path(__file__).resolve().parents[1]
    report["backend_source_sha256"] = {
        str(p.relative_to(source_root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((source_root / "src/dsgpt").glob("*.py"))
    }
    report["model_sha256"] = hashlib.sha256(args.model.read_bytes()).hexdigest()
    if report["model_sha256"] != args.expected_sha256:
        raise ValueError("Model checksum mismatch")
    processes = []
    with tempfile.TemporaryDirectory(prefix="dsgpt-stage3-") as temp:
        root = Path(temp)
        log = (root / "process.log").open("w+")
        try:
            runtime = subprocess.Popen(
                [
                    str(args.server.resolve()),
                    "-m",
                    str(args.model.resolve()),
                    "--alias",
                    "fixture",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "18081",
                    "--ctx-size",
                    "8192",
                    "--parallel",
                    "1",
                    "--threads",
                    "4",
                    "--threads-batch",
                    "4",
                    "--no-ui",
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            processes.append(runtime)

            def ready(url):
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline:
                    try:
                        if httpx.get(url, timeout=1, trust_env=False).status_code == 200:
                            return
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                raise AssertionError("Local process failed to start")

            ready("http://127.0.0.1:18081/health")
            config = root / "config.toml"
            config.write_text(
                '[[models]]\nid="fixture"\nname="Fixture"\nruntime="llama.cpp"\n'
                'endpoint="http://127.0.0.1:18081"\nruntime_model="fixture"\n'
                "context=8192\noutput_tokens=512\n"
            )
            credentials = Auth(Store(root / "data")).initialize_owner()
            backend = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "dsgpt.cli",
                    "serve",
                    "--config",
                    str(config),
                    "--data-dir",
                    str(root / "data"),
                    "--port",
                    "18765",
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            processes.append(backend)
            ready("http://127.0.0.1:18765/health")
            with httpx.Client(
                base_url="http://127.0.0.1:18765",
                trust_env=False,
                timeout=30,
                headers={"Authorization": "Bearer " + credentials["token"]},
            ) as client:

                def post(path, data):
                    r = client.post(path, json=data)
                    r.raise_for_status()
                    return r.json()

                task = post(
                    "/v1/work/tasks",
                    {
                        "title": "Tiny fixture draft",
                        "model_id": "fixture",
                        "requirements": "Create only hello.txt containing exactly HELLO LOCAL. "
                        "Use write_file once, then finish. Do not execute anything.",
                    },
                )
                post(f"/v1/work/tasks/{task['id']}/actions", {"action": "start", "revision": 1})
                memory = post(
                    "/v1/memories",
                    {"title": "Project codename", "content": "The codename is COBALT."},
                )
                chat = post("/v1/conversations", {"title": "Synthetic retrieval check"})
                run = post(
                    f"/v1/conversations/{chat['id']}/messages",
                    {
                        "request_id": str(uuid4()),
                        "model_id": "fixture",
                        "content": "What is the project codename? Answer one word from memory.",
                    },
                )
                deadline = time.monotonic() + 180
                while time.monotonic() < deadline:
                    task = client.get("/v1/work/tasks/" + task["id"]).json()
                    run = client.get("/v1/runs/" + run["id"]).json()
                    if task["status"] in {"completed", "blocked"} and run["status"] in {
                        "completed",
                        "failed",
                    }:
                        break
                    time.sleep(0.2)
                files = client.get(f"/v1/work/tasks/{task['id']}/files").json()
                steps = client.get(f"/v1/work/tasks/{task['id']}/steps").json()
                messages = client.get(f"/v1/conversations/{chat['id']}/messages").json()
                answer = next(m["content"] for m in messages if m["role"] == "assistant")
                report.update(
                    {
                        "task_status": task["status"],
                        "task_blocker": task["blocker"],
                        "steps": steps,
                        "files": files,
                        "answer": answer,
                        "scheduler": client.get("/v1/diagnostics/scheduler").json(),
                    }
                )
                events = client.get(f"/v1/runs/{run['id']}/events").text
                report["checks"] = {
                    "chat_completed": run["status"] == "completed",
                    "memory_retrieved": memory["id"] in events,
                    "memory_answer": "COBALT" in answer.upper(),
                    "work_completed": task["status"] == "completed",
                    "work_wrote_file": any(f["path"] == "hello.txt" for f in files),
                    "work_wrote_expected_content": any(
                        f["path"] == "hello.txt"
                        and f["sha256"] == hashlib.sha256(b"HELLO LOCAL").hexdigest()
                        for f in files
                    ),
                    "shared_scheduler": all(
                        report["scheduler"]["grants"][k] > 0 for k in ("chat_grants", "work_grants")
                    ),
                    "no_code_execution": task["code_execution_available"] is False,
                }
                if files:
                    r = client.get(f"/v1/work/tasks/{task['id']}/export")
                    r.raise_for_status()
                    args.output.with_suffix(".zip").write_bytes(r.content)
                assert all(report["checks"].values()), report["checks"]
        finally:
            for p in reversed(processes):
                if p.poll() is None:
                    p.terminate()
                    try:
                        p.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        p.kill()
                        p.wait()
            report["finished_at"] = utcnow()
            args.output.write_text(json.dumps(report, indent=2) + "\n")
            log.close()
    print(json.dumps(report["checks"]))


if __name__ == "__main__":
    main()
