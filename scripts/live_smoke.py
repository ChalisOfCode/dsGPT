"""Launch real llama.cpp + dsGPT processes and test inference and crash recovery.

Use only the tiny test model here; these numbers are not RTX 3080 Ti benchmarks.
No inference output, credentials or model binary is sent to a hosted service.
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
    args = parser.parse_args()
    report = {
        "started_at": utcnow(),
        "classification": "real_cpu_inference_in_cloud_workspace",
        "model": "Qwen/Qwen3-0.6B-GGUF Q8_0",
        "target_gpu_benchmark": False,
        "model_sha256": hashlib.sha256(args.model.read_bytes()).hexdigest(),
        "checks": {},
        "runs": [],
    }
    processes = []
    logs = []
    client = httpx.Client(base_url="http://127.0.0.1:18765", trust_env=False, timeout=90)

    def ready(url):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                if httpx.get(url, timeout=1, trust_env=False).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        raise AssertionError("Local process failed to become ready")

    def get(path):
        response = client.get(path)
        response.raise_for_status()
        return response.json()

    def post(path, body):
        response = client.post(path, json=body)
        response.raise_for_status()
        return response.json()

    def chat():
        return post("/v1/conversations", {"title": "Synthetic local integration test"})["id"]

    def send(chat_id, prompt):
        return post(
            f"/v1/conversations/{chat_id}/messages",
            {"request_id": str(uuid4()), "model_id": "cpu-test", "content": prompt},
        )["id"]

    def wait(run_id, states=("completed", "failed", "interrupted")):
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            row = get(f"/v1/runs/{run_id}")
            if row["status"] in states:
                return row
            time.sleep(0.02)
        raise AssertionError("Inference wait timed out")

    def expect_completed(run_id):
        row = wait(run_id)
        assert row["status"] == "completed", row
        messages = get(f"/v1/conversations/{row['conversation_id']}/messages")
        answer = next(m["content"] for m in messages if m["id"] == row["message_id"])
        event_text = client.get(f"/v1/runs/{run_id}/events").text
        report["runs"].append({"id": run_id, "answer": answer, "events": parse_events(event_text)})
        return answer

    temporary = tempfile.TemporaryDirectory(prefix="dsgpt-live-")
    try:
        directory = Path(temporary.name)
        runtime_log = (directory / "llama.log").open("w+")
        logs.append(runtime_log)
        runtime = subprocess.Popen(
            [
                str(args.server.resolve()),
                "-m",
                str(args.model.resolve()),
                "--alias",
                "qwen3-0.6b-test",
                "--host",
                "127.0.0.1",
                "--port",
                "18081",
                "--ctx-size",
                "4096",
                "--parallel",
                "1",
                "--threads",
                "4",
                "--threads-batch",
                "4",
                "--no-ui",
            ],
            stdout=runtime_log,
            stderr=subprocess.STDOUT,
        )
        processes.append(runtime)
        ready("http://127.0.0.1:18081/health")
        props = httpx.get("http://127.0.0.1:18081/props", trust_env=False).json()
        report["runtime_context"] = props.get("default_generation_settings", {}).get("n_ctx")
        report["runtime_version"] = subprocess.check_output(
            [str(args.server.resolve()), "--version"], text=True, stderr=subprocess.STDOUT
        ).strip()
        report["runtime_rss_bytes"] = None
        report["runtime_memory_note"] = (
            "Not measured: launcher PID may differ from runtime PID in managed environments"
        )
        config = directory / "config.toml"
        config.write_text("""[[models]]
id = "cpu-test"
name = "Qwen3 0.6B test only"
runtime = "llama.cpp"
endpoint = "http://127.0.0.1:18081"
runtime_model = "qwen3-0.6b-test"
context = 4096
output_tokens = 768
""")
        data = directory / "data"
        owner = Auth(Store(data)).initialize_owner()
        client.headers["Authorization"] = "Bearer " + owner["token"]

        def start_backend():
            log = (directory / f"backend-{len(logs)}.log").open("w+")
            logs.append(log)
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "dsgpt.cli",
                    "serve",
                    "--data-dir",
                    str(data),
                    "--config",
                    str(config),
                    "--port",
                    "18765",
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            processes.append(process)
            ready("http://127.0.0.1:18765/health")
            return process

        backend = start_backend()
        conversation = chat()
        run = send(conversation, "Reply with exactly READY. /no_think")
        answer = expect_completed(run)
        assert "ready" in answer.casefold(), answer
        report["checks"]["actual_local_generation_without_subscriber"] = "passed"
        print("PASS local generation", flush=True)

        remember = send(conversation, "The project code is ORCHARD42. Remember it. /no_think")
        expect_completed(remember)
        recall = send(conversation, "What is the project code? Reply with only the code. /no_think")
        assert "ORCHARD42" in expect_completed(recall)
        report["checks"]["multi_turn_context"] = "passed"
        print("PASS multi-turn context", flush=True)

        stream_run = send(
            chat(), "List the integers from 1 through 40, separated by commas. /no_think"
        )
        last_id = 0
        with client.stream("GET", f"/v1/runs/{stream_run}/events") as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line.startswith("id: "):
                    last_id = int(line[4:])
                if line.startswith("event: delta"):
                    break  # Real HTTP disconnect while inference continues.
        expect_completed(stream_run)
        replay = client.get(
            f"/v1/runs/{stream_run}/events", headers={"Last-Event-ID": str(last_id)}
        )
        ids = [int(line[4:]) for line in replay.text.splitlines() if line.startswith("id: ")]
        assert ids and all(i > last_id for i in ids)
        assert "event: completed" in replay.text
        report["checks"]["http_disconnect_and_event_replay"] = "passed"
        print("PASS disconnect and replay", flush=True)

        interrupted = send(chat(), "Write a detailed 700 word story about a library. /no_think")
        wait(interrupted, ("running",))
        queued = send(chat(), "Reply with exactly RESTORED. /no_think")
        assert get(f"/v1/runs/{queued}")["status"] == "queued"
        backend.kill()
        backend.wait(timeout=10)
        backend = start_backend()
        assert get(f"/v1/runs/{interrupted}")["status"] == "interrupted"
        assert "restored" in expect_completed(queued).casefold()
        report["checks"]["real_process_kill_restart_and_queue_recovery"] = "passed"
        print("PASS process crash recovery", flush=True)

        preview = post("/v1/diagnostics/exports/preview", {})
        exported = client.get(
            f"/v1/diagnostics/exports/{preview['id']}", params={"sha256": preview["sha256"]}
        )
        assert exported.status_code == 200 and exported.content.startswith(b"PK")
        assert "ORCHARD42" not in json.dumps(preview)
        assert owner["token"] not in json.dumps(preview)
        report["checks"]["diagnostic_export_after_real_inference"] = "passed"
        report["status"] = "passed"
    except Exception as exc:
        report["status"] = "failed"
        report["failure"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
        for index, log in enumerate(logs):
            if report.get("status") == "failed":
                log.flush()
                log.seek(0)
                args.output.with_name(f"live-failure-process-{index}.txt").write_text(log.read())
            log.close()
        client.close()
        temporary.cleanup()
        report["finished_at"] = utcnow()
        args.output.write_text(json.dumps(report, indent=2) + "\n")
        print("Live integration report:", args.output, flush=True)


def parse_events(text):
    result = []
    for frame in text.split("\n\n"):
        kind = next((line[7:] for line in frame.splitlines() if line.startswith("event: ")), None)
        if kind not in {"context", "metrics", "timing", "completed", "failed"}:
            continue
        data = next(
            (json.loads(line[6:]) for line in frame.splitlines() if line.startswith("data: ")), {}
        )
        result.append({"kind": kind, "data": data})
    return result


if __name__ == "__main__":
    main()
