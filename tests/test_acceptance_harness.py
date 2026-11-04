"""Report privacy, failure persistence and bounded debugger transport are release gates."""

import importlib.util
import json
import socket
import sys
import zipfile
from argparse import Namespace
from pathlib import Path

import httpx
import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "scripts/acceptance"
spec = importlib.util.spec_from_file_location("dsgpt_acceptance_test", PACKAGE / "__init__.py")
package = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = package
spec.loader.exec_module(package)
spec = importlib.util.spec_from_file_location(
    "dsgpt_acceptance_test.__main__", PACKAGE / "__main__.py"
)
main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(main)


def make_runner(tmp_path):
    return main.Runner(Namespace(kit=tmp_path, output=tmp_path / "run", ci=True, no_phone=True))


def test_share_archive_excludes_private_state_and_redacts_secrets(tmp_path):
    runner = make_runner(tmp_path)
    secret = 'owner-test-"-credential-é'
    runner.secrets.append(secret)
    (runner.private / "owner-token.json").write_text(secret)
    runner.report["checks"].append(
        {
            "name": "Synthetic",
            "status": "FAIL",
            "detail": {
                "token": secret,
                "path": str(runner.private),
                "url": "https://private.example.ts.net",
            },
        }
    )
    runner.save()
    with zipfile.ZipFile(runner.root / "dsGPT-report.zip") as archive:
        assert set(archive.namelist()) == {"report.json", "Read-this-report.html"}
        result = json.loads(archive.read("report.json"))
        detail = result["checks"][0]["detail"]
        assert secret not in str(detail) and "example.ts.net" not in str(detail)
        assert detail["token"] == "[redacted]"
    runner.http.close()


def test_failure_and_blocker_do_not_stop_independent_check_and_checkpoint(tmp_path):
    runner = make_runner(tmp_path)

    def fail():
        raise AssertionError("Fixture failure")

    def blocked():
        raise main.Blocked("Connect test device")

    runner.check("failed", fail)
    runner.check("blocked", blocked)
    runner.check("independent", lambda: {"finished": True})
    saved = json.loads((runner.share / "report.json").read_text())
    assert [r["status"] for r in saved["checks"]] == ["FAIL", "BLOCKED", "PASS"]
    assert not saved["finished"] and (runner.root / "dsGPT-report.zip").is_file()
    runner.http.close()


def test_integrity_rejects_traversal_without_reading_outside_kit(tmp_path):
    runner = make_runner(tmp_path)
    (tmp_path / "kit-manifest.json").write_text(
        json.dumps(
            {"files": {"../private": {"bytes": 1, "sha256": "0" * 64}}, "source_commit": "test"}
        )
    )
    with pytest.raises(AssertionError, match="Kit file missing"):
        runner.integrity()
    runner.http.close()


def test_cdp_rejects_non_loopback_before_connect():
    with pytest.raises(ValueError, match="loopback"):
        main.CDP("ws://example.com:9222/devtools/page/1")


def test_docker_test_cannot_use_existing_remote_context_or_credentials(tmp_path, monkeypatch):
    runner = make_runner(tmp_path)
    runner.docker = "/usr/bin/docker"
    monkeypatch.setenv("DOCKER_HOST", "tcp://remote.example:2376")
    monkeypatch.setenv("DOCKER_CONTEXT", "production")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "private-test-secret")
    recorded = {}

    def capture(argv, timeout, **kwargs):
        recorded.update(argv=argv, timeout=timeout, **kwargs)

    monkeypatch.setattr(main, "command", capture)
    runner.docker_cli(["info"])
    assert "remote.example" not in str(recorded) and "production" not in str(recorded)
    assert "private-test-secret" not in str(recorded)
    assert recorded["argv"][1:3] == ["--config", runner.private / "docker-config"]
    assert recorded["argv"][3] == "--host"
    runner.http.close()


def test_cdp_handles_fragmented_messages_and_rejects_large_frame():
    left, right = socket.socketpair()
    cdp = main.CDP.__new__(main.CDP)
    cdp.sock = left
    try:
        right.sendall(b'\x01\x05{"a":\x80\x021}')
        assert cdp.receive() == {"a": 1}
        right.sendall(b"\x81\x7f" + (9 * 1024 * 1024).to_bytes(8, "big"))
        with pytest.raises(ValueError, match="Invalid CDP frame"):
            cdp.receive()
    finally:
        left.close()
        right.close()


def test_run_evidence_replays_only_numeric_metrics_and_registered_warnings(tmp_path):
    runner = make_runner(tmp_path)
    runner.origin, runner.token = "http://127.0.0.1:12345", "fixture-token"
    runner.http.close()
    runner.http = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                text='event: delta\ndata: {"text":"PRIVATE_ANSWER"}\n\n'
                'event: metrics\ndata: {"eval_count":1024,"thinking_chunks":8,'
                '"text":"PRIVATE_REASONING","load_duration":true}\n\n'
                'event: timing\ndata: {"elapsed_seconds":14.2}\n\n'
                'event: warning\ndata: {"code":"output_limit"}\n\n'
                'event: warning\ndata: {"code":"PRIVATE_ERROR"}\n\n'
                'event: failed\ndata: {"code":"output_limit"}\n\n',
            )
        )
    )
    try:
        result = runner.run_evidence(
            {"id": "fixture-run", "status": "failed", "error_code": "output_limit"}
        )
        assert result["metrics"] == {
            "eval_count": 1024,
            "thinking_chunks": 8,
            "elapsed_seconds": 14.2,
        }
        assert result["warnings"] == ["output_limit"]
        assert result["error_code"] == "output_limit"
        assert "PRIVATE" not in json.dumps(result)
    finally:
        runner.http.close()


@pytest.mark.parametrize(
    "status,build,timeout,passed",
    [
        ("completed", "running", False, True),
        ("failed", "running", False, False),
        ("completed", "completed", False, False),
        ("running", "running", True, False),
    ],
)
def test_concurrent_probe_requires_completed_chat_and_overlapping_build(
    tmp_path, monkeypatch, status, build, timeout, passed
):
    runner = make_runner(tmp_path)
    calls = []
    run = {
        "id": "fixture-chat",
        "status": status,
        "error_code": "output_limit" if status == "failed" else None,
    }
    monkeypatch.setattr(runner, "submit", lambda model, prompt: ({}, {}, run))

    def wait(*args):
        if timeout:
            raise AssertionError("Generation exceeded its acceptance time limit")
        return run

    def api(method, path, *args):
        calls.append((method, path))
        return {"id": "fixture-build", "status": build}

    monkeypatch.setattr(runner, "wait_run", wait)
    monkeypatch.setattr(runner, "api", api)
    monkeypatch.setattr(runner, "run_evidence", lambda reply: {"metrics": {"eval_count": 1024}})
    try:
        result = runner.chat_during_build(
            "local", "/v1/work/tasks/fixture", {"id": "fixture-build", "status": "running"}
        )
        runner.local_work_evidence = {"concurrent_chat": result}
        assert result["attempted"] and result["run_id"] == "fixture-chat"
        assert result["completed_during_build"] is passed
        if passed:
            assert runner.local_work_chat() == result
        else:
            with pytest.raises(AssertionError, match="Concurrent Chat did not pass"):
                runner.local_work_chat()
        if timeout:
            assert ("POST", "/v1/runs/fixture-chat/cancel") in calls
        else:
            assert result["run_status"] == status and result["build_status_after"] == build
            assert result["error_code"] == run["error_code"]
    finally:
        runner.http.close()


def test_successful_repair_is_preserved_when_concurrent_chat_fails(tmp_path, monkeypatch):
    runner = make_runner(tmp_path)
    runner.config = tmp_path / "backend.json"
    runner.config.write_text("{}")
    runner.models = [{"id": "local", "name": "Local model"}]
    runner.image, runner.origin, runner.token = (
        "fixture-image",
        "http://127.0.0.1:12345",
        "fixture-token",
    )
    monkeypatch.setattr(runner, "stop", lambda process: None)
    monkeypatch.setattr(runner, "start_backend", lambda: None)
    monkeypatch.setattr(main.time, "sleep", lambda seconds: None)
    artifact = b"MZ-fixture-built-executable"
    runner.http.close()
    runner.http = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=artifact))
    )
    task_reads = 0

    def api(method, path, *args, **kwargs):
        nonlocal task_reads
        if path.endswith("/steps"):
            return [{"action": {"tool": "run"}, "result": {"exit_code": code}} for code in (1, 0)]
        if path.endswith("/artifacts"):
            return [{"id": "exe", "sha256": main.hashlib.sha256(artifact).hexdigest()}]
        if path.endswith("/executions"):
            return [{"id": "build", "status": "running"}] if task_reads == 1 else []
        if method == "GET":
            task_reads += 1
        return {
            "id": "task",
            "revision": 1,
            "status": "running" if task_reads < 2 else "completed",
            "session": {"step": task_reads},
        }

    monkeypatch.setattr(runner, "api", api)
    monkeypatch.setattr(
        runner,
        "chat_during_build",
        lambda *args: {
            "attempted": True,
            "completed_during_build": False,
            "run_status": "failed",
            "error_code": "output_limit",
        },
    )
    try:
        runner.check("Real local model compiler repair", runner.local_work)
        runner.check("Chat completes during the local model build", runner.local_work_chat)
        assert [check["status"] for check in runner.report["checks"]] == ["PASS", "FAIL"]
        evidence = json.loads((runner.share / "local-model-work.json").read_text())
        assert evidence["checks"]["artifact_verified"] and evidence["checks"]["repaired_compile"]
        assert not evidence["checks"]["chat_completed_during_build"]
        assert evidence["concurrent_chat"]["error_code"] == "output_limit"
        assert len(evidence["steps"]) == 2 and evidence["task_status"] == "completed"
    finally:
        runner.http.close()
