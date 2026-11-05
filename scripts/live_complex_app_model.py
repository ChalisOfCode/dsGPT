"""Fresh real-model Task Ledger acceptance, with actual isolated builds and independent tests.

No model action or command result is synthesized. This requires a prepared local
inference server and the production Docker tool image. Native UI validation is a
separate stage; a successful report from this script does not certify those UIs.
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from dsgpt.api import create_app
from dsgpt.app_builder import project_files
from dsgpt.builds import snapshot_hash
from dsgpt.config import Model, Settings
from dsgpt.inference import LocalInference
from dsgpt.project_tools import ProjectAction, ProjectTools, safe_path
from dsgpt.storage import uid

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/complex-app"
REPAIR_MARKER = "\n#error DSGPT_ACCEPTANCE_REPAIR\n"
ORACLE_XML = (
    "android/app/build/test-results/testDebugUnitTest/TEST-IndependentTaskLedgerAcceptance.xml"
)


def digest(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode()).hexdigest()


def provenance(source_commit=None):
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    return {
        "commit": source_commit or (result.stdout.strip() if result.returncode == 0 else None),
        "checkout_commit": result.stdout.strip() if result.returncode == 0 else None,
        "commit_label_origin": "explicit_source_commit" if source_commit else "local_checkout",
        "python_modules": {
            str(path.relative_to(ROOT)): digest(path.read_bytes())
            for path in sorted((ROOT / "src/dsgpt").glob("*.py"))
        },
        "harness_sha256": digest(Path(__file__).read_bytes()),
        "requirements_sha256": digest((FIXTURES / "request.txt").read_bytes()),
        "followup_sha256": digest((FIXTURES / "followup.txt").read_bytes()),
    }


def verify_source(original):
    current = provenance()
    if any(
        current[key] != original[key]
        for key in (
            "python_modules", "harness_sha256", "requirements_sha256", "followup_sha256"
        )
    ):
        raise AssertionError("Backend, acceptance harness or original requests changed during run")


class AcceptanceCPUClient(httpx.AsyncClient):
    """Record exact resource controls without changing prompts or model decisions."""

    def __init__(self, *args, cpu_threads, batch_size, runtime_requests, **kwargs):
        super().__init__(*args, **kwargs)
        self.cpu_threads, self.batch_size = cpu_threads, batch_size
        self.runtime_requests = runtime_requests

    def build_request(self, method, url, **kwargs):
        payload = kwargs.get("json")
        if str(url).endswith("/api/chat") and isinstance(payload, dict):
            options = payload.setdefault("options", {})
            options.update(num_thread=self.cpu_threads, use_mmap=True, num_batch=self.batch_size)
            self.runtime_requests.append(
                {
                    "options": dict(options),
                    "think": payload.get("think"),
                    "keep_alive": payload.get("keep_alive"),
                    "structured_output": bool(payload.get("format")),
                }
            )
        return super().build_request(method, url, **kwargs)


def save_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


class MeasuredInference(LocalInference):
    """Forward every real event unchanged; optionally release residency before compilation."""

    def __init__(
        self, release_before_build, events, cpu_threads=None, batch_size=64, runtime_requests=None
    ):
        super().__init__()
        self.release_before_build, self.events = release_before_build, events
        self.cpu_threads, self.batch_size = cpu_threads, batch_size
        self.runtime_requests = runtime_requests if runtime_requests is not None else []

    def client(self, model):
        if self.cpu_threads is None or model.runtime != "ollama":
            return super().client(model)
        return AcceptanceCPUClient(
            base_url=model.endpoint.rstrip("/"), trust_env=False, follow_redirects=False,
            timeout=httpx.Timeout(connect=10, read=180, write=30, pool=10),
            cpu_threads=self.cpu_threads, batch_size=self.batch_size,
            runtime_requests=self.runtime_requests,
        )

    async def stream(self, model, messages, response_schema=None):
        fragments = []
        started = time.monotonic()
        async for event in super().stream(model, messages, response_schema=response_schema):
            if event["kind"] == "delta":
                fragments.append(event["data"]["text"])
            yield event
        raw = "".join(fragments)
        self.events.append(
            {
                "seconds": round(time.monotonic() - started, 3),
                "response_bytes": len(raw.encode()),
                "response_sha256": digest(raw),
            }
        )
        try:
            action = json.loads(raw)
        except ValueError:
            return
        if (
            self.release_before_build
            and model.runtime == "ollama"
            and isinstance(action, dict)
            and action.get("tool") in {"build_project", "run"}
        ):
            await self.release_resident()
            self.events[-1]["ollama_residency_released_before_build"] = True


def request(client, method, path, body=None):
    response = client.request(method, path, **({"json": body} if body is not None else {}))
    response.raise_for_status()
    return response.json()


def pause_task(client, app, task_id):
    """Pause normally and wait for the active task's cancellation and cleanup."""
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        task = request(client, "GET", f"/v1/work/tasks/{task_id}")
        if task["status"] == "paused":
            break
        if task["status"] not in {"queued", "running", "blocked"}:
            raise AssertionError("Task became terminal before the planned pause")
        response = client.post(
            f"/v1/work/tasks/{task_id}/actions",
            json={
                "action": "pause",
                "revision": task["revision"],
            },
        )
        if response.status_code == 409:
            continue
        response.raise_for_status()
        break
    else:
        raise TimeoutError("Could not obtain a stable task revision for pause")
    while app.state.work.active_id == task_id and time.monotonic() < deadline:
        time.sleep(0.05)
    if app.state.work.active_id == task_id:
        raise TimeoutError("Paused task did not finish cancellation/cleanup")


def saved_sources(store, task_id):
    return store.all(
        "SELECT path,content,sha256 FROM work_files WHERE task_id=? ORDER BY path", (task_id,)
    )


def steps(store, task_id):
    return [
        {**row, "action": json.loads(row["action"]), "result": json.loads(row["result"])}
        for row in store.all("SELECT * FROM work_steps WHERE task_id=? ORDER BY step", (task_id,))
    ]


def progress_event(phase, task, history):
    """Expose recorded action categories, never request/source/credential text."""
    event = {"phase": phase, "status": task["status"], "step": task["session"]["step"]}
    if not history:
        return event
    latest = history[-1]
    action, result = latest["action"], latest["result"]
    allowed = set(ProjectAction.model_json_schema()["properties"]["tool"]["enum"])
    allowed.update({"review_specification", "review_image"})
    event["last_action"] = (
        "invalid_response" if "invalid_output" in action
        else action.get("tool") if action.get("tool") in allowed else "unknown"
    )
    event["last_result"] = (
        "validation_rejected" if result.get("error") == "invalid_action"
        else "tool_error" if result.get("error") or result.get("exit_code") not in (None, 0)
        else "recorded"
    )
    if "invalid_output" in action:
        event["rejected_response_characters"] = len(action["invalid_output"])
    repeated = 0
    for previous in reversed(history):
        if previous["action"] != action:
            break
        repeated += 1
    event["consecutive_identical_actions"] = repeated
    return event


def restart_snapshot(store, task_id):
    task = store.one("SELECT requirements FROM work_tasks WHERE id=?", (task_id,))
    return {
        "requirements_sha256": digest(task["requirements"]),
        "source_sha256": snapshot_hash(saved_sources(store, task_id)),
        "artifacts": store.all(
            "SELECT id,sha256 FROM work_artifacts WHERE task_id=? ORDER BY id", (task_id,)
        ),
        "signing_key_sha256": (
            store.one("SELECT sha256 FROM work_signing_keys WHERE task_id=?", (task_id,)) or {}
        ).get("sha256"),
    }


def confirm_oracle(result, minimum_cases):
    """Require the external suite itself to have executed, not a model's success statement."""
    if result.get("exit_code") != 0 or result.get("error"):
        raise AssertionError("Independent app compilation/behavior suite failed")
    if "DSGPT_TASK_LEDGER_ORACLE_OK" not in result.get("stdout", ""):
        raise AssertionError("Independent portable C++ behavior suite did not report completion")
    artifacts = {item["path"]: item for item in result.get("artifacts", [])}
    if ORACLE_XML not in artifacts:
        raise AssertionError("Independent Android JUnit suite report is missing")
    suite = ET.fromstring(artifacts[ORACLE_XML]["content"])
    if (
        int(suite.attrib.get("tests", "0")) != minimum_cases
        or any(int(suite.attrib.get(key, "0")) for key in ("failures", "errors", "skipped"))
        or len(suite.findall("testcase")) != minimum_cases
    ):
        raise AssertionError("Independent Android cases did not all execute successfully")
    return {"kotlin_cases": minimum_cases, "cpp_behavior_suite": "passed"}


def independent_validation(client, app, task_id, phase, output):
    # Load only the reviewed sibling. Its implementations are never supplied to the model.
    sys.path.insert(0, str(ROOT / "scripts"))
    from complex_app_fixture import (
        FOLLOWUP_ORACLE_CASE_COUNT,
        ORACLE_CASE_COUNT,
        independent_tests,
    )

    sources = saved_sources(app.state.store, task_id)
    by_path = {item["path"]: item["content"] for item in sources}
    scaffold = project_files("android", "Task Ledger", task_id)
    for path in ("android/settings.gradle", "android/build.gradle", "android/gradle.properties"):
        if by_path.get(path) != scaffold[path]:
            raise AssertionError("Offline acceptance build configuration changed: " + path)
    expected_app = scaffold["android/app/build.gradle"]
    actual_app = by_path.get("android/app/build.gradle", "")
    if phase == "followup":
        import re

        version = re.search(r"versionCode\s+(\d+)", actual_app)
        if not version or int(version[1]) <= 1:
            raise AssertionError("Follow-up must increase Android versionCode")
        actual_app = re.sub(r"versionCode\s+\d+", "versionCode 1", actual_app)
        actual_app = re.sub(r"versionName\s+'[^']*'", "versionName '1.0'", actual_app)
    if actual_app != expected_app:
        raise AssertionError("Offline acceptance dependencies or test configuration changed")
    by_path.update(independent_tests(task_id, followup=phase == "followup"))
    files = [
        {"path": path, "content": body, "sha256": digest(body)}
        for path, body in sorted(by_path.items())
    ]

    async def run():
        await app.state.work.inference.release_resident()
        return await app.state.builds.sandbox.execute(
            uid(),
            files,
            ["python3", "-I", "/opt/dsgpt/app_build_worker.py", "apps"],
            ["dist/build-report.json", ORACLE_XML],
            900,
        )

    result = client.portal.call(run)
    checks = confirm_oracle(
        result, FOLLOWUP_ORACLE_CASE_COUNT if phase == "followup" else ORACLE_CASE_COUNT
    )
    receipts = []
    for item in result["artifacts"]:
        destination = output / "independent-tests" / safe_path(item["path"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(item["content"])
        receipts.append({key: item[key] for key in ("path", "sha256")})
    if saved_sources(app.state.store, task_id) != sources:
        raise AssertionError("Independent checks changed the saved model project")
    return {
        "status": "passed",
        **checks,
        "model_source_sha256": snapshot_hash(sources),
        "artifacts": receipts,
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
        "generated_code_execution": "production Docker",
    }


def record_phase(client, app, task, phase, output):
    identifier, store = task["id"], app.state.store
    source = saved_sources(store, identifier)
    history = steps(store, identifier)
    if task["status"] != "completed":
        raise AssertionError("Model did not complete " + phase + ": " + str(task.get("blocker")))
    if not history or history[-1]["action"]["tool"] != "finish":
        raise AssertionError("Completion lacks an actual model finish action")
    finish = history[-1]["result"]
    if finish.get("snapshot_sha256") != snapshot_hash(source):
        raise AssertionError("Completed artifacts do not match the current model source")
    kinds = {item["kind"] for item in finish.get("artifacts", [])}
    if not {"apk", "exe"}.issubset(kinds):
        raise AssertionError("The actual completion result must contain both APK and EXE")
    output.mkdir(parents=True, exist_ok=True)
    for item in source:
        destination = output / "source" / safe_path(item["path"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(item["content"])
    artifacts = []
    for item in finish["artifacts"]:
        response = client.get(f"/v1/work/tasks/{identifier}/artifacts/{item['id']}")
        response.raise_for_status()
        if digest(response.content) != item["sha256"]:
            raise AssertionError("Downloaded artifact hash differs from its receipt")
        destination = output / "artifacts" / safe_path(item["path"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(response.content)
        artifacts.append(item)
    executions = store.all(
        "SELECT id,status,result,snapshot_sha256 FROM work_executions "
        "WHERE task_id=? ORDER BY step",
        (identifier,),
    )
    certificates = []
    for execution in executions:
        receipt = json.loads(execution["result"] or "{}")
        certificate = (
            receipt.get("verification", {})
            .get("checks", {})
            .get("android", {})
            .get("certificate_sha256")
        )
        if execution["status"] == "completed" and certificate:
            certificates.append(certificate)
    if not certificates or len(set(certificates)) != 1:
        raise AssertionError("Actual Android builds did not preserve one project signing identity")
    return {
        "status": "completed",
        "source_sha256": snapshot_hash(source),
        "requirement_characters": len(task["requirements"]),
        "requirement_sha256": digest(task["requirements"]),
        "steps": history,
        "artifacts": artifacts,
        "execution_results": {
            execution["id"]: json.loads(execution["result"] or "{}") for execution in executions
        },
        "android_certificate_sha256": certificates[0],
        "independent_tests": independent_validation(client, app, identifier, phase, output),
        "native_android_ui": "not_run",
        "native_windows_ui": "not_run",
    }


def inject_user_fault(store, task_id):
    """A recorded user-side broken edit, never represented as a model decision."""
    row = store.one(
        "SELECT content,sha256 FROM work_files WHERE task_id=? AND path='windows/main.cpp'",
        (task_id,),
    )
    if not row or REPAIR_MARKER in row["content"]:
        raise AssertionError("Expected one unchanged model Windows main.cpp before fault injection")
    with store.transaction() as db:
        result = ProjectTools.apply(
            db,
            task_id,
            ProjectAction(
                tool="edit_file",
                summary="Acceptance user-side compile fault, not a model action",
                path="windows/main.cpp",
                expected_sha256=row["sha256"],
                old_text=row["content"],
                new_text=row["content"] + REPAIR_MARKER,
            ),
        )
    if result.get("error"):
        raise AssertionError(result["error"])
    return {
        "path": "windows/main.cpp",
        "before_sha256": row["sha256"],
        "after_sha256": result["sha256"],
        "marker": REPAIR_MARKER.strip(),
    }


def repair_observed(history, after, execution_results=None):
    failed = None
    for step in history:
        if step["step"] <= after or step["action"].get("tool") not in {"build_project", "run"}:
            continue
        result = step["result"]
        result = (execution_results or {}).get(result.get("execution_id"), result)
        text = result.get("stdout", "") + result.get("stderr", "")
        if result.get("exit_code", 0) != 0 and "DSGPT_ACCEPTANCE_REPAIR" in text:
            failed = step["step"]
        elif failed is not None and result.get("exit_code") == 0:
            return {"failure_step": failed, "repaired_build_step": step["step"]}
    raise AssertionError(
        "No actual marker compiler failure followed by a successful repaired build"
    )


def run(args, report):
    if args.state.exists():
        raise ValueError(
            "Fresh acceptance requires a new state directory; existing tasks are not reused"
        )
    original = provenance(args.source_commit)
    report["source"] = original
    model = Model(
        "acceptance-local",
        "Actual Task Ledger model",
        args.runtime,
        args.endpoint,
        args.model,
        abliterated=args.abliterated,
        context=args.context,
        output_tokens=args.output_tokens,
        expected_digest=args.model_digest,
    )
    report["model"] = {
        "runtime": model.runtime,
        "runtime_model": model.runtime_model,
        "context": model.context,
        "output_tokens": model.output_tokens,
        "expected_digest": model.expected_digest,
        "abliterated": model.abliterated,
        "cpu_threads": args.cpu_threads,
        "num_batch": args.batch_size if args.cpu_threads is not None else None,
        "use_mmap": True if args.cpu_threads is not None else None,
        "release_before_build": args.release_before_build,
    }
    report["execution_budget"] = {
        "timeout_seconds": args.timeout,
        "max_steps": args.max_steps,
        "restart_after_step": args.restart_after_step,
    }
    settings = Settings(
        args.state, {model.id: model}, allowed_hosts=("testserver",), sandbox_image=args.image
    )
    token, task_id, phase, restart = None, None, "initial", None
    deadline, prior_step, followup_start = time.monotonic() + args.timeout, None, None
    initial_request = (FIXTURES / "request.txt").read_text()
    followup = (FIXTURES / "followup.txt").read_text()
    while True:
        verify_source(original)
        inference = MeasuredInference(
            args.release_before_build, report["inference_calls"], args.cpu_threads,
            args.batch_size, report["runtime_requests"],
        )
        app = create_app(settings, inference=inference)
        if token is None:
            token = app.state.auth.initialize_owner()["token"]
        with TestClient(app, headers={"Authorization": "Bearer " + token}) as client:
            if task_id is None:
                report["isolation_probe"] = request(client, "POST", "/v1/work/sandbox/probe")
                task = request(
                    client,
                    "POST",
                    "/v1/work/tasks",
                    {
                        "title": "Task Ledger fresh multi-feature acceptance",
                        "model_id": model.id,
                        "requirements": initial_request,
                        "build_target": "apps",
                        "web_mode": "off",
                        "start": True,
                    },
                )
                task_id = report["task_id"] = task["id"]
            elif restart is not None and not restart.get("verified"):
                after = restart_snapshot(app.state.store, task_id)
                if after != restart["before"]:
                    raise AssertionError(
                        "Backend restart changed saved requirements, sources or artifacts"
                    )
                restart["after"], restart["verified"] = after, True
                task = request(client, "GET", f"/v1/work/tasks/{task_id}")
                task = request(
                    client,
                    "POST",
                    f"/v1/work/tasks/{task_id}/actions",
                    {
                        "action": "resume",
                        "revision": task["revision"],
                    },
                )
            while True:
                task = request(client, "GET", f"/v1/work/tasks/{task_id}")
                step = task["session"]["step"]
                state = (phase, task["status"], step)
                if state != prior_step:
                    history = steps(app.state.store, task_id)
                    print(
                        json.dumps(progress_event(phase, task, history)),
                        flush=True,
                    )
                    prior_step = state
                    report["last_task"] = task
                    report["last_steps"] = history
                    save_report(args.output, report)
                if task["status"] in {"completed", "blocked", "stopped"}:
                    break
                if time.monotonic() > deadline or step > args.max_steps:
                    pause_task(client, app, task_id)
                    raise TimeoutError(
                        "Acceptance budget reached; task paused without inventing completion"
                    )
                if (
                    phase == "initial"
                    and restart is None
                    and step >= args.restart_after_step
                    and saved_sources(app.state.store, task_id)
                ):
                    pause_task(client, app, task_id)
                    # Closing TestClient invokes normal Work shutdown; no task state is patched.
                    restart = report["backend_restart"] = {
                        "method": "normal pause, backend close/reopen, normal resume",
                        "before": restart_snapshot(app.state.store, task_id),
                        "verified": False,
                    }
                    break
                time.sleep(0.25)
            if restart is not None and not restart.get("verified"):
                continue
            result = record_phase(client, app, task, phase, args.artifacts / phase)
            report["phases"][phase] = result
            if phase == "initial":
                if not restart or not restart.get("verified"):
                    raise AssertionError(
                        "Initial task completed before the required backend restart"
                    )
                if task["requirements"] != initial_request:
                    raise AssertionError("The exact original long request changed")
                report["user_side_fault"] = inject_user_fault(app.state.store, task_id)
                followup_start = task["session"]["step"]
                request(
                    client,
                    "PATCH",
                    f"/v1/work/tasks/{task_id}",
                    {
                        "revision": task["revision"],
                        "note": followup,
                        "resume": True,
                    },
                )
                phase = "followup"
                # Keep this backend alive for the actual user follow-up.
                report["followup_submitted"] = True
                save_report(args.output, report)
                return continue_followup(
                    args, report, client, app, task_id, deadline, followup_start
                )


def continue_followup(args, report, client, app, task_id, deadline, after):
    previous = None
    while True:
        task = request(client, "GET", f"/v1/work/tasks/{task_id}")
        step = task["session"]["step"]
        state = (task["status"], step)
        if state != previous:
            history = steps(app.state.store, task_id)
            print(json.dumps(progress_event("followup", task, history)), flush=True)
            previous = state
            report["last_task"] = task
            report["last_steps"] = history
            save_report(args.output, report)
        if task["status"] in {"completed", "blocked", "stopped"}:
            break
        if time.monotonic() > deadline or step > args.max_steps:
            pause_task(client, app, task_id)
            raise TimeoutError("Follow-up acceptance budget reached")
        time.sleep(0.25)
    result = record_phase(client, app, task, "followup", args.artifacts / "followup")
    report["phases"]["followup"] = result
    report["observed_compiler_repair"] = repair_observed(
        result["steps"], after, result["execution_results"]
    )
    if (
        result["android_certificate_sha256"]
        != report["phases"]["initial"]["android_certificate_sha256"]
    ):
        raise AssertionError("Follow-up changed Android signing identity")
    verify_source(report["source"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--image", required=True, help="Prepared immutable production Docker image ID"
    )
    parser.add_argument("--runtime", choices=("ollama", "llama.cpp"), default="ollama")
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434")
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-digest")
    parser.add_argument(
        "--source-commit", help="Exact tested remote source commit; local checkout is recorded too"
    )
    parser.add_argument("--abliterated", action="store_true")
    parser.add_argument("--context", type=int, default=16384)
    parser.add_argument("--output-tokens", type=int, default=4096)
    parser.add_argument("--cpu-threads", type=int, help="Explicit Ollama CPU inference threads")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=10800)
    parser.add_argument("--max-steps", type=int, default=240)
    parser.add_argument("--restart-after-step", type=int, default=8)
    parser.add_argument(
        "--release-before-build", action=argparse.BooleanOptionalAction, default=True
    )
    args = parser.parse_args()
    if args.source_commit and not re.fullmatch(
        r"[a-fA-F0-9]{40}|[a-fA-F0-9]{64}", args.source_commit
    ):
        parser.error("--source-commit must be a full hexadecimal commit ID")
    if args.cpu_threads is not None and (args.cpu_threads < 1 or args.runtime != "ollama"):
        parser.error("--cpu-threads must be positive and is supported only for Ollama")
    if args.batch_size < 1:
        parser.error("--batch-size must be positive")
    report = {
        "format": "dsgpt-complex-app-model-v1",
        "status": "running",
        "fresh_start": True,
        "model_workflow_passed": False,
        "single_backend_source_version": False,
        "native_runtime_verified": False,
        "overall_application_acceptance": "not_completed",
        "phases": {},
        "inference_calls": [],
        "runtime_requests": [],
        "scope": "Actual local inference and production Docker; no mocked model actions/results",
        "limitations": [
            "One bounded multi-feature fixture is not proof of arbitrary-task reliability",
            "Native Android and Windows UI acceptance runs separately on the produced artifacts",
            "The follow-up compiler fault is a declared user-side edit "
            "after initial model delivery",
        ],
    }
    started = time.monotonic()
    try:
        run(args, report)
        # run() only returns after the TestClient has completed backend shutdown.
        verify_source(report["source"])
        report.update(
            model_workflow_passed=True,
            single_backend_source_version=True,
            status="completed_model_and_compiler_checks",
            native_runtime_verified=False,
            overall_application_acceptance="pending_native_ui_checks",
        )
    except BaseException as exc:
        report.update(
            status="failed",
            error={"type": type(exc).__name__, "message": str(exc)},
            model_workflow_passed=False,
            single_backend_source_version=False,
            native_runtime_verified=False,
            overall_application_acceptance="not_completed",
        )
        raise
    finally:
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        save_report(args.output, report)
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "model_workflow_passed": report["model_workflow_passed"],
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
