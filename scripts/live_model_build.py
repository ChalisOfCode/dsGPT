"""Real local CPU-model repair/build with a simultaneous Chat turn.

The initial broken C file and requested compiler command are explicit fixtures.
Every agent decision and repair comes from the pinned local model. Generated
commands execute only through the production Docker boundary. No native EXE run.
"""

import argparse
import hashlib
import json
import shutil
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import psutil
from fastapi.testclient import TestClient

from dsgpt.api import create_app
from dsgpt.catalog import CATALOG
from dsgpt.config import Settings
from dsgpt.project_tools import ProjectAction, ProjectTools

BAD = '#include <stdio.h>\nint main(void) { puts("DSGPT_LOCAL_MODEL_BUILD") return 0; }\n'
COMMAND = "sleep 45; x86_64-w64-mingw32-gcc hello.c -o hello.exe"


def wait_for(check, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError("Timed out waiting for local integration state")


def main(args, report):
    root = Path(__file__).resolve().parents[1]
    report["backend_source_sha256"] = {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((root / "src/dsgpt").glob("*.py"))
    }
    with tempfile.TemporaryDirectory(prefix="dsgpt-model-build-") as directory:
        app = create_app(
            Settings(Path(directory), {}, allowed_hosts=("testserver",), sandbox_image=args.image)
        )
        credential = app.state.auth.initialize_owner()
        report["download_mode"] = "prepared_inputs" if args.inputs else "production_public_https"
        for key in ("qwen3-1-7b-q8-0", "llama-b11718-linux-x64"):
            asset = CATALOG[key]
            row = app.state.downloads.submit(key)
            if args.inputs:
                shutil.copyfile(
                    args.inputs / asset.url.rsplit("/", 1)[1], app.state.downloads.paths(asset)[1]
                )
                app.state.downloads.update(row["id"], "verifying", asset.size)
        with TestClient(app, headers={"Authorization": "Bearer " + credential["token"]}) as client:

            def post(path, body=None):
                response = client.post(path, json=body)
                response.raise_for_status()
                return response.json()

            def get(path):
                response = client.get(path)
                response.raise_for_status()
                return response.json()

            def chat():
                conversation = post("/v1/conversations", {"title": "Concurrent build fixture"})
                return post(
                    f"/v1/conversations/{conversation['id']}/messages",
                    {
                        "request_id": str(uuid4()),
                        "model_id": "cpu-coding",
                        "content": "Reply with only READY.",
                    },
                )

            def finish_chat(run):
                def completed():
                    row = get("/v1/runs/" + run["id"])
                    return row if row["status"] in {"completed", "failed", "cancelled"} else None

                return wait_for(completed)

            def downloads_complete():
                rows = get("/v1/downloads")
                report["downloads"] = rows
                assert all(x["status"] != "failed" for x in rows), rows
                return len(rows) == 2 and all(x["status"] == "downloaded" for x in rows)

            print("Verifying model/runtime inputs via " + report["download_mode"], flush=True)
            wait_for(downloads_complete, timeout=600)
            report["input_verification"] = []
            for key in ("qwen3-1-7b-q8-0", "llama-b11718-linux-x64"):
                asset = CATALOG[key]
                path = app.state.downloads.paths(asset)[1]
                with path.open("rb") as source:
                    digest = hashlib.file_digest(source, "sha256").hexdigest()
                assert digest == asset.sha256 and path.stat().st_size == asset.size
                report["input_verification"].append(
                    {"asset_id": key, "url": asset.url, "sha256": digest, "bytes": asset.size}
                )
            if not args.inputs:
                report["checks"]["production_public_downloads_verified"] = True
            print("Both input digests verified; installing the owned local runtime", flush=True)
            post("/v1/runtimes/llama-b11718-linux-x64/install")
            post(
                "/v1/models/managed",
                {
                    "id": "cpu-coding",
                    "name": "Qwen actual CPU build",
                    "asset_id": "qwen3-1-7b-q8-0",
                    "runtime_id": "llama-b11718-linux-x64",
                    "context": 8192,
                    "output_tokens": 1024,
                    "gpu_layers": 0,
                },
            )
            report["probe"] = post("/v1/work/sandbox/probe")
            warm = finish_chat(chat())
            report["warm_chat"] = warm
            report["runner_diagnostics"] = get("/v1/diagnostics/overview")
            report["checks"]["actual_local_chat"] = warm["status"] == "completed"
            assert report["checks"]["actual_local_chat"], warm
            report["checks"]["production_private_listener_verified"] = (
                app.state.runtime.status()["transport"] == "private_unix_socket"
                and app.state.runtime.owns_listener()
            )
            print("Real warm Chat completed; starting the model's isolated repair task", flush=True)
            requirements = (
                "Repair and compile the existing hello.c as a Windows EXE. First compile the "
                "existing source unchanged so you observe its real compiler diagnostic. "
                'For each compile use run with argv ["sh", "-c", '
                + json.dumps(COMMAND)
                + '] and artifacts ["hello.exe"]. The sleep is intentional for a concurrency test. '
                "After observing the error, read hello.c if needed, correct the C syntax with "
                "write_file and its current expected_sha256, and compile again. Preserve the "
                "DSGPT_LOCAL_MODEL_BUILD output text. Once the real EXE is collected, finish "
                "and explain that native Windows execution is untested. "
                "Do not repeat a successful build."
            )
            task = post(
                "/v1/work/tasks",
                {
                    "title": "Actual local-model compiler repair",
                    "requirements": requirements,
                    "model_id": "cpu-coding",
                    "build_target": "exe",
                },
            )
            with app.state.store.transaction() as db:
                ProjectTools.apply(
                    db,
                    task["id"],
                    ProjectAction(
                        tool="write_file",
                        summary="Deliberate initial broken source fixture",
                        path="hello.c",
                        content=BAD,
                    ),
                )
            post(
                f"/v1/work/tasks/{task['id']}/actions",
                {"action": "start", "revision": task["revision"]},
            )
            deadline = time.monotonic() + 900
            simultaneous = None
            last_progress = None
            while time.monotonic() < deadline:
                task = get(f"/v1/work/tasks/{task['id']}")
                progress = (task["status"], task.get("session", {}).get("step", 0))
                if progress != last_progress:
                    print(f"Work status={progress[0]}, step={progress[1]}", flush=True)
                    last_progress = progress
                executions = get(f"/v1/work/tasks/{task['id']}/executions")
                active = next((x for x in executions if x["status"] == "running"), None)
                if active and simultaneous is None:
                    process = psutil.Process(app.state.runtime.status()["process_id"])
                    before_cpu = process.cpu_times()
                    report["model_rss_before_chat_bytes"] = process.memory_info().rss
                    started = time.monotonic()
                    simultaneous = finish_chat(chat())
                    report["concurrent_chat_seconds"] = time.monotonic() - started
                    after_cpu = process.cpu_times()
                    report["model_cpu_seconds_during_chat"] = (
                        after_cpu.user + after_cpu.system - before_cpu.user - before_cpu.system
                    )
                    report["model_rss_after_chat_bytes"] = process.memory_info().rss
                    report["concurrent_chat"] = simultaneous
                    still_active = get(f"/v1/work/tasks/{task['id']}/executions/{active['id']}")
                    report["checks"]["chat_completed_during_build"] = (
                        simultaneous["status"] == "completed"
                        and still_active["status"] == "running"
                    )
                    print("Concurrent Chat measured; waiting for the model's repair", flush=True)
                if task["status"] in {"completed", "blocked", "stopped"}:
                    break
                if task.get("session", {}).get("step", 0) > 24:
                    break
                time.sleep(0.1)
            report["task"] = task
            report["steps"] = get(f"/v1/work/tasks/{task['id']}/steps")
            report["executions"] = get(f"/v1/work/tasks/{task['id']}/executions")
            report["checks"]["task_completed"] = task["status"] == "completed"
            commands = [x["result"] for x in report["steps"] if x["action"]["tool"] == "run"]
            report["checks"]["compiler_error_observed"] = bool(
                commands
                and commands[0].get("exit_code", 0) > 0
                and "error:" in commands[0].get("stderr", "")
            )
            report["checks"]["repaired_compile_succeeded"] = bool(
                len(commands) >= 2 and commands[-1].get("exit_code") == 0
            )
            artifacts = get(f"/v1/work/tasks/{task['id']}/artifacts")
            report["checks"]["artifact_hash_verified"] = False
            if artifacts:
                artifact = artifacts[0]
                response = client.get(f"/v1/work/tasks/{task['id']}/artifacts/{artifact['id']}")
                response.raise_for_status()
                report["checks"]["artifact_hash_verified"] = (
                    hashlib.sha256(response.content).hexdigest() == artifact["sha256"]
                )
                args.output.with_suffix(".exe").write_bytes(response.content)
                report["artifact"] = artifact
            report["checks"]["no_cleanup_pending"] = get("/v1/work/sandbox")["cleanup_pending"] == 0
            sample = json.loads(
                (
                    Path(__file__).resolve().parents[1] / "tests/fixtures/docx-sample.json"
                ).read_text()
            )
            document_chat = post("/v1/conversations", {"title": "Private DOCX fixture"})
            document_run = finish_chat(
                post(
                    f"/v1/conversations/{document_chat['id']}/messages",
                    {
                        "request_id": str(uuid4()),
                        "model_id": "cpu-coding",
                        "content": "Return only the exact first paragraph of the attached file.",
                        "attachments": [
                            {"name": sample["name"], "original_base64": sample["original_base64"]}
                        ],
                    },
                )
            )
            document_messages = get(f"/v1/conversations/{document_chat['id']}/messages")
            answer = next(
                (m["content"] for m in reversed(document_messages) if m["role"] == "assistant"), ""
            )
            report["private_docx"] = {
                "run_status": document_run["status"],
                "answer": answer,
                "fixture": "python-docx generated paragraph/table",
            }
            report["checks"]["actual_local_docx_text_answer"] = (
                document_run["status"] == "completed" and "DOCX_PRIVATE_JADE" in answer
            )
            report["passed"] = all(report["checks"].values()) and simultaneous is not None


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument(
        "--inputs", type=Path, help="Optional already verified offline fixture inputs"
    )
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    result = {
        "actual_local_model": "qwen3-1-7b-q8-0",
        "hosted_inference": False,
        "production_listener": "private_unix_socket",
        "target_gpu_tested": False,
        "native_windows_execution": False,
        "checks": {},
        "passed": False,
    }
    try:
        main(arguments, result)
    except Exception as exc:
        result["error"] = type(exc).__name__ + ": " + str(exc)
    arguments.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k not in {"steps", "executions", "task"}}))
    raise SystemExit(0 if result["passed"] else 1)
