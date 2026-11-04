import json
import subprocess
from types import SimpleNamespace

import pytest
from conftest import new_chat, send, wait_run

from dsgpt import hardware
from dsgpt.api import create_app
from dsgpt.config import Settings
from dsgpt.storage import canonical, uid, utcnow


def test_gpu_query_is_read_only_and_handles_unsupported_fields(monkeypatch):
    monkeypatch.setattr(hardware, "nvidia_executable", lambda: "/usr/bin/nvidia-smi")

    def run(argv, **kwargs):
        assert argv[1] == "--query-gpu=" + hardware.GPU_FIELDS
        assert argv[2] == "--format=csv,noheader,nounits"
        assert kwargs["timeout"] == 2 and "shell" not in kwargs
        return SimpleNamespace(
            returncode=0,
            stdout=(
                b"NVIDIA GeForce RTX 3080 Ti, 560.01, 12288, 4096, 65, 72, 250.5, 350\n"
                b"NVIDIA GPU, 560.01, N/A, N/A, [Not Supported], nan, inf, -1\n"
            ),
        )

    monkeypatch.setattr(subprocess, "run", run)
    snapshot = hardware.gpu_snapshot()
    assert snapshot["status"] == "collected"
    first, second = snapshot["devices"]
    assert first["vram_total_mib"] == 12288 and first["utilization_percent"] == 65
    assert first["power_watts"] == 250.5
    assert all(
        value is None for key, value in second.items() if key not in {"name", "driver_version"}
    )


@pytest.mark.parametrize("outcome", ["missing", "timeout", "error", "malformed", "oversized"])
def test_unavailable_gpu_never_breaks_export_or_leaks_driver_output(monkeypatch, outcome):
    monkeypatch.setattr(
        hardware,
        "nvidia_executable",
        lambda: None if outcome == "missing" else "/system/nvidia-smi",
    )

    def run(*args, **kwargs):
        if outcome == "timeout":
            raise subprocess.TimeoutExpired("private/path", 2, output=b"PRIVATE_SECRET")
        return SimpleNamespace(
            returncode=1 if outcome == "error" else 0,
            stdout=b"PRIVATE_SECRET" * (6000 if outcome == "oversized" else 1),
        )

    monkeypatch.setattr(subprocess, "run", run)
    result = hardware.gpu_snapshot()
    assert result["status"] == "unavailable" and result["devices"] == []
    assert "PRIVATE_SECRET" not in json.dumps(result)


def test_metrics_and_work_receipts_are_useful_without_private_payloads(backend):
    secret = "PRIVATE_DOCUMENT password=secret /home/private/token"
    run = send(backend, new_chat(backend), secret).json()
    wait_run(backend, run["id"])
    task = backend.client.post(
        "/v1/work/tasks", json={"title": secret, "requirements": secret}
    ).json()
    execution_id = uid()
    with backend.store.transaction() as db:
        db.execute(
            "INSERT INTO events(run_id,kind,payload,created_at) VALUES(?,?,?,?)",
            (
                run["id"],
                "metrics",
                canonical(
                    {
                        "eval_count": 20,
                        "eval_duration": 2e9,
                        "prompt_eval_count": 100,
                        "prompt_eval_duration": 1e9,
                        "prompt_tokens": "PRIVATE_DOCUMENT",
                        "load_duration": float("nan"),
                        "text": secret,
                        "total_tokens": True,
                    }
                ),
                utcnow(),
            ),
        )
        db.execute(
            "INSERT INTO work_executions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                execution_id,
                task["id"],
                1,
                secret,
                "a" * 64,
                None,
                "failed",
                canonical({"exit_code": 1, "stdout": secret, "stderr": secret}),
                0,
                0,
                utcnow(),
                utcnow(),
            ),
        )
    backend.store.log("runtime_unavailable", run["id"])
    preview = backend.client.post("/v1/diagnostics/exports/preview", json={}).json()
    files = preview["files"]
    assert secret not in json.dumps(files)
    assert backend.credentials["token"] not in json.dumps(files)
    data = json.loads(files["desktop/inference-metrics.json"])["recent_requests"][0]
    assert data["request_id"] == run["id"] and data["model"]["runtime"] == "ollama"
    metrics = data["metrics"]
    assert metrics["generation_tokens_per_second"] == 10
    assert metrics["prompt_tokens_per_second"] == 100
    assert metrics["first_text_seconds"] >= 0
    assert not {"text", "load_duration", "total_tokens", "prompt_tokens"} & metrics.keys()
    execution = json.loads(files["desktop/agent-events.json"])["recent_executions"][0]
    assert execution["id"] == execution_id and execution["exit_code"] == 1
    assert "runtime_unavailable" in files["summary.md"]
    assert "Start the configured local inference runtime" in files["summary.md"]


def test_retention_configuration_controls_written_events(tmp_path):
    from fastapi.testclient import TestClient

    settings = Settings(tmp_path, allowed_hosts=("testserver",), diagnostic_event_retention=3)
    app = create_app(settings)
    with TestClient(app):
        for _ in range(8):
            app.state.store.log("runtime_unavailable")
        assert len(app.state.store.all("SELECT * FROM diagnostic_events")) == 3
    for options in ({"diagnostic_event_retention": -1}, {"diagnostic_retention": 0}):
        with pytest.raises(ValueError):
            Settings(tmp_path, **options)


def test_every_export_file_is_in_manifest_and_matches_hash(backend):
    import hashlib

    preview = backend.client.post("/v1/diagnostics/exports/preview", json={}).json()
    files = preview["files"]
    manifest = json.loads(files["manifest.json"])
    assert set(manifest["files"]) == set(files) - {"manifest.json"}
    for name, metadata in manifest["files"].items():
        content = files[name].encode()
        assert metadata == {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
