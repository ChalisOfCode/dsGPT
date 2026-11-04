"""Pure harness checks; these are not model, compiler or native-runtime evidence."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "complex_app_model_ci", ROOT / "scripts/live_complex_app_model.py"
)
acceptance = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(acceptance)


def test_declared_source_commit_keeps_actual_checkout_identity():
    declared = "a" * 40
    record = acceptance.provenance(declared)
    assert record["commit"] == declared
    assert record["commit_label_origin"] == "explicit_source_commit"
    assert record["checkout_commit"] == acceptance.provenance()["commit"]
    assert record["python_modules"]


@pytest.mark.parametrize(
    "field", ["python_modules", "harness_sha256", "requirements_sha256", "followup_sha256"]
)
def test_acceptance_rejects_source_or_original_request_drift(monkeypatch, field):
    original = acceptance.provenance()
    changed = {**original, field: "changed"}
    monkeypatch.setattr(acceptance, "provenance", lambda: changed)
    with pytest.raises(AssertionError, match="changed during run"):
        acceptance.verify_source(original)


def test_explicit_cpu_controls_preserve_prompt_schema_and_inference_settings():
    requests = []
    client = acceptance.AcceptanceCPUClient(
        base_url="http://127.0.0.1:11435", cpu_threads=2, batch_size=64,
        runtime_requests=requests, trust_env=False,
    )
    messages = [{"role": "user", "content": "Original long request. " * 500}]
    schema = {"type": "object", "properties": {"tool": {"type": "string"}}}
    request = client.build_request(
        "POST", "/api/chat", json={
            "model": "exact-model:9b", "messages": messages, "format": schema,
            "think": False, "keep_alive": "5m", "stream": True,
            "options": {"temperature": 0, "num_ctx": 16384, "num_predict": 4096},
        }
    )
    payload = json.loads(request.content)
    assert payload["messages"] == messages
    assert payload["format"] == schema
    assert payload["think"] is False and payload["stream"] is True
    assert payload["options"] == {
        "temperature": 0, "num_ctx": 16384, "num_predict": 4096,
        "num_thread": 2, "num_batch": 64, "use_mmap": True,
    }
    assert requests == [{
        "options": payload["options"], "think": False, "keep_alive": "5m",
        "structured_output": True,
    }]


@pytest.mark.parametrize("failure", [RuntimeError("shutdown"), KeyboardInterrupt(), SystemExit(2)])
def test_shutdown_failure_or_interruption_clears_all_completion_claims(
    monkeypatch, tmp_path, failure
):
    report_path = tmp_path / "failed-harness-report.json"
    monkeypatch.setattr(acceptance.sys, "argv", [
        "live_complex_app_model.py", "--image", "unused", "--model", "unused",
        "--state", str(tmp_path / "state"), "--output", str(report_path),
        "--artifacts", str(tmp_path / "artifacts"),
    ])

    def interrupted_shutdown(args, report):
        # Only exercise report failure handling; no model or native acceptance is simulated.
        report.update(
            model_workflow_passed=True, single_backend_source_version=True,
            native_runtime_verified=True, status="completed_model_and_compiler_checks",
            overall_application_acceptance="pending_native_ui_checks",
        )
        raise failure

    monkeypatch.setattr(acceptance, "run", interrupted_shutdown)
    with pytest.raises(type(failure)):
        acceptance.main()
    report = json.loads(report_path.read_text())
    assert report["status"] == "failed"
    assert report["error"]["type"] == type(failure).__name__
    assert report["model_workflow_passed"] is False
    assert report["single_backend_source_version"] is False
    assert report["native_runtime_verified"] is False
    assert report["overall_application_acceptance"] == "not_completed"
