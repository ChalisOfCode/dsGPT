"""Actual pinned runtime install, Chat/Work inference, switching and backend-kill recovery.

Pre-downloaded publisher files seed the durable download manager's final-file
recovery path. This is not a new network transport or target-GPU benchmark.
"""

import argparse
import ctypes
import hashlib
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from uuid import uuid4

import httpx

from dsgpt.catalog import CATALOG
from dsgpt.downloads import DownloadManager
from dsgpt.security import Auth
from dsgpt.storage import Store, utcnow


def wait_for(predicate, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError("Timed out waiting for integration state")


def gone(pid):
    try:
        os.kill(pid, 0)
        return False
    except ProcessLookupError:
        return True


def adopted_child_reaped(pid):
    try:
        result, _ = os.waitpid(pid, os.WNOHANG)
        return result == pid
    except ChildProcessError:
        return gone(pid)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--restricted-host-tcp-fixture", action="store_true")
    parser.add_argument("--work-reference-fixture", action="store_true")
    parser.add_argument("--chat-attachment-fixture", action="store_true")
    args = parser.parse_args()
    if args.work_reference_fixture and not args.restricted_host_tcp_fixture:
        parser.error("Synthetic Work references require the explicit test-only backend fixture")
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:
        raise RuntimeError("Test requires child subreaper for exact crash-reaping proof")
    report = {
        "started_at": utcnow(),
        "actual_local_inference": True,
        "target_gpu_tested": False,
        "windows_native_tested": False,
        "download_fixture": "publisher files seeded; full manager hash recovery",
        "listener_ownership": "test substitute"
        if args.restricted_host_tcp_fixture
        else "production private Unix socket",
        "production_listener_boundary_validated": not args.restricted_host_tcp_fixture,
        "checks": {},
    }
    root = Path(__file__).resolve().parents[1]
    report["backend_source_sha256"] = {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((root / "src/dsgpt").glob("*.py"))
    }
    report["fixture_source_sha256"] = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [Path(__file__), root / "scripts/runtime_recovery_fixture.py"]
    }
    processes = []
    with tempfile.TemporaryDirectory(prefix="dsgpt-managed-live-") as temp:
        directory = Path(temp)
        store = Store(directory / "data")
        credential = Auth(store).initialize_owner()
        downloads = DownloadManager(store)
        for key in ("qwen3-1-7b-q8-0", "llama-b11718-linux-x64"):
            asset = CATALOG[key]
            row = downloads.submit(key)
            source = args.inputs / asset.url.rsplit("/", 1)[1]
            shutil.copyfile(source, downloads.paths(asset)[1])
            downloads.update(row["id"], "verifying", asset.size)
        log = (directory / "backend.log").open("w+")
        command = [
            sys.executable,
            "-m",
            "dsgpt.cli",
            "serve",
            "--data-dir",
            str(directory / "data"),
            "--port",
            "18765",
        ]
        if args.restricted_host_tcp_fixture:
            command = [
                sys.executable,
                str(root / "scripts/runtime_recovery_fixture.py"),
                "--data-dir",
                str(directory / "data"),
            ]
            if args.work_reference_fixture:
                command.append("--work-reference-fixture")
        client = httpx.Client(
            base_url="http://127.0.0.1:18765",
            trust_env=False,
            timeout=60,
            headers={"Authorization": "Bearer " + credential["token"]},
        )

        def start_backend():
            process = subprocess.Popen(command, stdout=log, stderr=log)
            processes.append(process)

            def ready():
                assert process.poll() is None, "Backend exited during startup"
                try:
                    return client.get("/health").status_code == 200
                except httpx.HTTPError:
                    return False

            wait_for(ready, 30)
            return process

        def post(path, body=None):
            response = client.post(path, json=body)
            response.raise_for_status()
            return response.json()

        def get(path):
            response = client.get(path)
            response.raise_for_status()
            return response.json()

        def chat(model="managed-a", prompt="Reply with only READY."):
            conversation = post("/v1/conversations", {"title": "Synthetic integration fixture"})
            run = post(
                f"/v1/conversations/{conversation['id']}/messages",
                {
                    "request_id": str(uuid4()),
                    "model_id": model,
                    "content": prompt,
                },
            )
            return conversation, run

        def finish(run):
            def terminal():
                row = get("/v1/runs/" + run["id"])
                return row if row["status"] in {"completed", "failed", "cancelled"} else None

            return wait_for(terminal)

        try:
            backend = start_backend()
            wait_for(lambda: all(r["status"] == "downloaded" for r in get("/v1/downloads")), 60)
            installed = post("/v1/runtimes/llama-b11718-linux-x64/install")
            print("Verified runtime installed", flush=True)
            report["checks"]["publisher_runtime_installed"] = installed["files_verified"] > 30
            for identifier in ("managed-a", "managed-b"):
                post(
                    "/v1/models/managed",
                    {
                        "id": identifier,
                        "name": "Qwen CPU fixture",
                        "asset_id": "qwen3-1-7b-q8-0",
                        "runtime_id": "llama-b11718-linux-x64",
                        "context": 8192,
                        "output_tokens": 512,
                        "gpu_layers": 0,
                    },
                )
            memory_request = {
                "request_id": str(uuid4()),
                "title": "Project codename",
                "content": "The project codename is COBALT.",
            }
            memory = post("/v1/memories", memory_request)
            report["checks"]["memory_creation_retry_returns_same_record"] = (
                post("/v1/memories", memory_request) == memory and len(get("/v1/memories")) == 1
            )
            task = post(
                "/v1/work/tasks",
                {
                    "title": "Managed runtime draft",
                    "model_id": "managed-a",
                    "requirements": "Create only hello.txt containing exactly HELLO LOCAL. "
                    "Use write_file once, then finish. Do not execute anything.",
                },
            )
            post(f"/v1/work/tasks/{task['id']}/actions", {"action": "start", "revision": 1})
            conversation, run = chat(
                prompt="What is the project codename? Answer one word from memory."
            )
            run = finish(run)
            print("First Chat turn: " + run["status"], flush=True)
            wait_for(
                lambda: get("/v1/work/tasks/" + task["id"])["status"] in {"completed", "blocked"}
            )
            task = get("/v1/work/tasks/" + task["id"])
            files = get(f"/v1/work/tasks/{task['id']}/files")
            steps = get(f"/v1/work/tasks/{task['id']}/steps")
            messages = get(f"/v1/conversations/{conversation['id']}/messages")
            answer = " ".join(m["content"] for m in messages if m["role"] == "assistant")
            events = client.get(f"/v1/runs/{run['id']}/events").text
            report.update(task_status=task["status"], files=files, steps=steps, answer=answer)
            scheduler = get("/v1/diagnostics/scheduler")
            report["checks"].update(
                chat_completed=run["status"] == "completed",
                memory_retrieved=memory["id"] in events and "COBALT" in answer.upper(),
                work_completed=task["status"] == "completed",
                work_file_correct=any(
                    f["path"] == "hello.txt"
                    and f["sha256"] == hashlib.sha256(b"HELLO LOCAL").hexdigest()
                    for f in files
                ),
                scheduler_shared=all(
                    scheduler["grants"][k] > 0 for k in ("chat_grants", "work_grants")
                ),
                code_execution_disabled=task["code_execution_available"] is False,
            )
            assert run["status"] == "completed", run
            if args.work_reference_fixture:
                report["work_reference_input"] = "Synthetic reader text; actual 1.7B CPU agent"
                reference_task = post(
                    "/v1/work/tasks",
                    {
                        "title": "Saved source integration",
                        "model_id": "managed-a",
                        "requirements": "Use read_source to read S1. Create only reference.txt "
                        "containing exactly the reference marker (one word, no newline) from S1. "
                        "Use write_file once, then finish. Do not execute anything.",
                        "reference_urls": ["https://example.org/dsgpt-fixture"],
                    },
                )
                reference_path = f"/v1/work/tasks/{reference_task['id']}"
                post(reference_path + "/actions", {"action": "start", "revision": 1})
                wait_for(lambda: get(reference_path)["status"] in {"completed", "blocked"})
                reference_task = get(reference_path)
                reference_sources = get(reference_path + "/sources")
                reference_steps = get(reference_path + "/steps")
                exported = client.get(reference_path + "/export")
                exported.raise_for_status()
                with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
                    source_export = json.loads(archive.read("sources.json"))
                    reference_content = (
                        archive.read("project/reference.txt").decode()
                        if "project/reference.txt" in archive.namelist()
                        else None
                    )
                report["work_reference_task"] = reference_task
                report["work_reference_steps"] = reference_steps
                report["work_reference_sources"] = reference_sources
                report["work_reference_file"] = reference_content
                report["checks"].update(
                    work_reference_completed=reference_task["status"] == "completed",
                    work_reference_snapshot_saved=reference_sources[0]["status"] == "retrieved",
                    work_reference_tool_read=any(
                        s["action"].get("tool") == "read_source"
                        and "AMBER" in s["result"].get("text", "")
                        for s in reference_steps
                    ),
                    work_reference_file_correct=reference_content == "AMBER",
                    work_reference_export_provenance=source_export["sources"][0]["text_sha256"]
                    == hashlib.sha256(source_export["sources"][0]["text"].encode()).hexdigest(),
                )
                print("Reference Work: " + reference_task["status"], flush=True)
            status = get("/v1/runtime/status")
            old_pid = status["process_id"]
            runtime_socket = directory / "data/runtime-sockets/llama.sock"
            with httpx.Client(
                trust_env=False,
                timeout=3,
                transport=None
                if args.restricted_host_tcp_fixture
                else httpx.HTTPTransport(uds=str(runtime_socket)),
            ) as anonymous:
                response = anonymous.get(f"http://127.0.0.1:{status['port'] or 18766}/v1/models")
                report["checks"]["runtime_requires_private_auth"] = response.status_code == 401
            if args.chat_attachment_fixture:
                attachment_chat = post(
                    "/v1/conversations", {"title": "Synthetic private attachment fixture"}
                )
                attachment_endpoint = f"/v1/conversations/{attachment_chat['id']}/messages"
                attachment_text = "\ufeffThe attachment verification marker is VIOLET.\r\n"
                attachment_request = {
                    "request_id": str(uuid4()),
                    "model_id": "managed-a",
                    "content": "Read the attached file. Reply with only its verification marker.",
                    "attachments": [{"name": "verification.txt", "text": attachment_text}],
                }
                attachment_run = finish(post(attachment_endpoint, attachment_request))
                attachment_messages = get(attachment_endpoint)
                attachment_metadata = attachment_messages[0]["attachments"]
                attachment_path = (
                    f"/v1/conversations/{attachment_chat['id']}/attachments/"
                    + attachment_metadata[0]["id"]
                )
                attachment_answer = attachment_messages[-1]["content"]
                report["chat_attachment"] = {
                    "input_kind": "synthetic UTF-8 file",
                    "metadata": attachment_metadata,
                    "answer": attachment_answer,
                    "run": attachment_run,
                }
                report["checks"].update(
                    attachment_chat_completed=attachment_run["status"] == "completed",
                    attachment_marker_read_by_real_model="VIOLET" in attachment_answer.upper(),
                    attachment_exact_download=client.get(attachment_path + "/download").content
                    == attachment_text.encode("utf-8"),
                    attachment_acceptance_retry_preserved=post(
                        attachment_endpoint, attachment_request
                    )["id"]
                    == attachment_run["id"]
                    and get(attachment_endpoint) == attachment_messages,
                )
                print("Attachment Chat: " + attachment_run["status"], flush=True)
            _, another = chat("managed-b")
            another = finish(another)
            new_pid = get("/v1/runtime/status")["process_id"]
            print("Model switch: " + another["status"], flush=True)
            report["checks"]["model_switch_replaced_only_owned_process"] = (
                another["status"] == "completed" and old_pid != new_pid and gone(old_pid)
            )
            report["switch_result"] = another
            assert another["status"] == "completed", another
            backend.kill()
            backend.wait(timeout=5)
            wait_for(lambda: adopted_child_reaped(new_pid), 10)
            report["checks"]["backend_kill_reaped_inference"] = True
            backend = start_backend()
            if args.work_reference_fixture:
                report["checks"]["work_reference_survived_restart"] = (
                    get(reference_path + "/sources") == reference_sources
                    and get(reference_path + "/steps") == reference_steps
                )
            if args.chat_attachment_fixture:
                report["checks"]["attachment_survived_restart"] = get(attachment_endpoint)[0][
                    "attachments"
                ] == attachment_metadata and client.get(
                    attachment_path + "/download"
                ).content == attachment_text.encode("utf-8")
                client.delete(attachment_path).raise_for_status()
                post(attachment_endpoint, attachment_request)
                report["checks"]["attachment_removal_not_resurrected"] = (
                    client.get(attachment_path).status_code == 410
                    and get(attachment_endpoint)[0]["attachments"][0]["removed"] is True
                )
            report["checks"]["memory_creation_receipt_survived_restart"] = (
                post("/v1/memories", memory_request) == memory and len(get("/v1/memories")) == 1
            )
            report["checks"]["registration_and_work_survived_restart"] = (
                len(get("/v1/runtime/status")["models"]) == 2
                and get(f"/v1/work/tasks/{task['id']}/files") == files
                and get(f"/v1/work/tasks/{task['id']}/steps") == steps
            )
            _, run = chat("managed-b")
            report["checks"]["inference_resumed_after_restart"] = (
                finish(run)["status"] == "completed"
            )
            loaded = get("/v1/runtime/status")["process_id"]
            post("/v1/runtime/unload")
            report["checks"]["explicit_unload"] = gone(loaded)
            with socket.socket() as external_listener:
                external_listener.bind(("127.0.0.1", 18766))
                external_listener.listen()
                _, run = chat()
                completed = finish(run)
                report["checks"]["existing_listener_preserved"] = (
                    completed["status"] == "completed"
                    and external_listener.getsockname()[1] == 18766
                    and get("/v1/runtime/status")["port"] != 18766
                )
            previous_pid = get("/v1/runtime/status")["process_id"]
            _, run = chat()
            report["checks"]["subsequent_turn_reused_runtime"] = (
                finish(run)["status"] == "completed"
                and get("/v1/runtime/status")["process_id"] == previous_pid
            )
            loaded = get("/v1/runtime/status")["process_id"]
            backend.terminate()
            backend.wait(timeout=15)
            wait_for(lambda: gone(loaded), 10)
            report["checks"]["graceful_shutdown_reaped_inference"] = True
            assert all(report["checks"].values()), report["checks"]
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
            client.close()
            log.close()
            report["finished_at"] = utcnow()
            args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["checks"]))


if __name__ == "__main__":
    main()
