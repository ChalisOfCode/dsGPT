import hashlib
import json
import sqlite3
import subprocess
from types import SimpleNamespace

import httpx
import pytest
from conftest import new_chat, pair, send, wait_run
from test_inference import ollama_handler, ollama_model

from dsgpt import network_diagnostics
from dsgpt.cli import load_settings
from dsgpt.diagnostic_logs import redact
from dsgpt.inference import InferenceError, LocalInference
from dsgpt.storage import SCHEMA_VERSION, Store, canonical, uid, utcnow


@pytest.mark.parametrize("streamed", [True, False])
@pytest.mark.parametrize(
    "error,code",
    [
        ("CUDA out of memory password=SECRET", "gpu_out_of_memory"),
        ({"message": "CUDA error illegal memory access SECRET"}, "cuda_error"),
        ("failed to load model /private/SECRET", "model_load_failed"),
        ("out of memory SECRET", "runtime_out_of_memory"),
    ],
)
async def test_runtime_errors_are_classified_without_echoing_private_text(streamed, error, code):
    def handler(request):
        if request.url.path == "/api/chat":
            return httpx.Response(
                200 if streamed else 500,
                text=json.dumps({"error": error}) + "\n",
            )
        return ollama_handler(request)

    adapter = LocalInference(httpx.MockTransport(handler))
    with pytest.raises(InferenceError) as caught:
        _ = [e async for e in adapter.stream(ollama_model(), [{"role": "user", "content": "Hi"}])]
    assert caught.value.code == code
    assert "SECRET" not in str(caught.value)


def test_failed_reply_saves_context_survives_restart_and_excludes_private_text(backend):
    backend.inference.error = InferenceError("gpu_out_of_memory")
    run = send(backend, new_chat(backend, "PRIVATE_TITLE"), "PRIVATE_PROMPT").json()
    assert wait_run(backend, run["id"])["status"] == "failed"
    snapshot = backend.store.one(
        "SELECT * FROM diagnostic_snapshots WHERE correlation_id=?", (run["id"],)
    )
    assert snapshot["reason"] == "gpu_out_of_memory"
    payload = json.loads(snapshot["payload"])
    assert payload["request"]["status"] == "failed"
    assert hashlib.sha256(snapshot["payload"].encode()).hexdigest() == snapshot["sha256"]
    assert (
        Store(backend.settings.data_dir).one(
            "SELECT sha256 FROM diagnostic_snapshots WHERE id=?", (snapshot["id"],)
        )["sha256"]
        == snapshot["sha256"]
    )
    preview = backend.client.post("/v1/diagnostics/exports/preview", json={}).json()
    assert "PRIVATE" not in json.dumps(preview)
    assert backend.credentials["token"] not in json.dumps(preview)
    assert any(name.startswith("desktop/snapshots/") for name in preview["files"])


def test_manual_snapshot_and_size_retention_limits(backend):
    backend.store.diagnostic_snapshot_retention = 2
    backend.store.diagnostic_snapshot_bytes = 4096
    for _ in range(3):
        response = backend.client.post("/v1/diagnostics/snapshots")
        assert response.status_code == 201
    rows = backend.store.all("SELECT * FROM diagnostic_snapshots")
    assert len(rows) == 2 and all(len(r["payload"].encode()) <= 4096 for r in rows)
    phone, _ = pair(backend, ["chat"])
    assert (
        backend.client.post(
            "/v1/diagnostics/snapshots", headers={"Authorization": "Bearer " + phone["token"]}
        ).status_code
        == 403
    )
    for _ in range(7):
        assert backend.client.post("/v1/diagnostics/exports/preview", json={}).status_code == 200
    assert len(backend.store.all("SELECT * FROM exports")) == 5


def test_failed_work_records_sanitized_context(backend):
    task = backend.client.post(
        "/v1/work/tasks", json={"title": "PRIVATE", "requirements": "PRIVATE"}
    ).json()
    with backend.store.transaction() as db:
        db.execute("UPDATE work_tasks SET status='running' WHERE id=?", (task["id"],))
    backend.app.state.work._block(task["id"], "work_step_failed")
    row = backend.store.one(
        "SELECT payload FROM diagnostic_snapshots WHERE correlation_id=?", (task["id"],)
    )
    assert "PRIVATE" not in row["payload"]
    assert json.loads(row["payload"])["work_task_counts"][0]["status"] == "blocked"


def test_build_logs_require_opt_in_and_work_scope_then_match_preview(backend):
    execution = uid()
    output = "compiler: unresolved symbol WIDGET\npassword=SECRET\nAuthorization: Bearer OTHER\n"
    with backend.store.transaction() as db:
        db.execute(
            "INSERT INTO work_executions(id,action,snapshot_sha256,status,result,created_at,"
            "updated_at) VALUES(?,?,?,?,?,?,?)",
            (
                execution,
                "{}",
                "a" * 64,
                "failed",
                canonical({"stdout": output}),
                utcnow(),
                utcnow(),
            ),
        )
    default = backend.client.post("/v1/diagnostics/exports/preview", json={}).json()
    assert "WIDGET" not in json.dumps(default)
    phone, _ = pair(backend, ["diagnostics"])
    assert (
        backend.client.post(
            "/v1/diagnostics/exports/preview",
            json={"include_work_logs": True},
            headers={"Authorization": "Bearer " + phone["token"]},
        ).status_code
        == 403
    )
    result = backend.client.post(
        "/v1/diagnostics/exports/preview", json={"include_work_logs": True}
    )
    assert result.status_code == 200, result.text
    preview = result.json()
    assert "WIDGET" in json.dumps(preview)
    assert "SECRET\\n" not in json.dumps(preview) and "OTHER" not in json.dumps(preview)
    manifest = json.loads(preview["files"]["manifest.json"])
    assert manifest["privacy"] == "opt_in_build_logs"
    name = f"desktop/build-logs/{execution}-stdout.log"
    assert (
        hashlib.sha256(preview["files"][name].encode()).hexdigest()
        == manifest["files"][name]["sha256"]
    )
    worker, _ = pair(backend, ["work", "diagnostics"])
    headers = {"Authorization": "Bearer " + worker["token"]}
    reviewed = backend.client.post(
        "/v1/diagnostics/exports/preview", json={"include_work_logs": True}, headers=headers
    ).json()
    endpoint = f"/v1/diagnostics/exports/{reviewed['id']}?sha256={reviewed['sha256']}"
    assert backend.client.get(endpoint, headers=headers).status_code == 200
    with backend.store.transaction() as db:
        db.execute(
            "UPDATE devices SET scopes=? WHERE id=?", ('["diagnostics"]', worker["device_id"])
        )
    assert backend.client.get(endpoint, headers=headers).status_code == 403


def test_known_secret_patterns_and_incomplete_private_keys_are_redacted():
    output = '"api_key": "HIDDEN" token=HIDDEN https://user:HIDDEN@host/path?q=HIDDEN\n'
    output += "-----BEGIN OPENSSH PRIVATE KEY-----\nHIDDEN\n"
    assert "HIDDEN" not in redact(output)


@pytest.mark.parametrize("outcome", ["ok", "bad", "large", "timeout", "unknown", "list"])
def test_tailscale_collects_only_self_state_and_never_peer_identity(monkeypatch, outcome):
    monkeypatch.setattr(network_diagnostics, "tailscale_executable", lambda: "/usr/bin/tailscale")

    def run(argv, **kwargs):
        assert argv == ["/usr/bin/tailscale", "status", "--json", "--peers=false"]
        assert kwargs["timeout"] == 2 and "shell" not in kwargs
        if outcome == "timeout":
            raise subprocess.TimeoutExpired("SECRET", 2, output="SECRET")
        data = {
            "BackendState": "Running" if outcome != "unknown" else "SECRET",
            "Self": {"Online": True, "DNSName": "SECRET", "TailscaleIPs": ["SECRET"]},
            "User": "SECRET",
        }
        raw = json.dumps(data).encode()
        if outcome == "large":
            raw = b"SECRET" * 50000
        if outcome == "bad":
            raw = b"SECRET"
        if outcome == "list":
            raw = b"[]"
        return SimpleNamespace(returncode=0, stdout=raw)

    monkeypatch.setattr(subprocess, "run", run)
    report = network_diagnostics.tailscale_status()
    assert report["status"] == ("measured" if outcome == "ok" else "unavailable")
    assert "SECRET" not in json.dumps(report)


def test_configured_retention_is_loaded_and_validated(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        "[diagnostics]\nevent_retention=10\nsnapshot_retention=2\nsnapshot_bytes=4096\nexport_bytes=262144\n"
    )
    settings = load_settings(path, tmp_path / "data")
    assert settings.diagnostic_snapshot_retention == 2
    assert settings.diagnostic_event_retention == 10
    path.write_text("[diagnostics]\nsnapshot_retention=1000\n")
    with pytest.raises(ValueError):
        load_settings(path, tmp_path / "data")


def test_v20_upgrade_preserves_data_and_backups_before_creating_journal(tmp_path):
    store = Store(tmp_path)
    with store.transaction() as db:
        for table in (
            "account_browser_profiles",
            "account_browser_writes",
            "account_grants",
            "account_sessions",
            "device_presence",
            "work_uploads",
            "work_web_calls",
            "work_specs",
            "work_spec_sections",
            "work_signing_keys",
        ):
            db.execute("DROP TABLE " + table)
        db.execute("DROP TABLE generation_options")
        db.execute("DROP TABLE diagnostic_snapshots")
        db.execute("PRAGMA user_version=20")
    upgraded = Store(tmp_path)
    assert upgraded.one("PRAGMA user_version")["user_version"] == SCHEMA_VERSION
    (backup,) = tmp_path.glob("before-v20-*.db")
    with sqlite3.connect(backup) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 20
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_mobile_health_protocol_is_bounded_and_requires_review_consent(backend):
    body = {
        "consent": True,
        "captured_at": utcnow(),
        "app_version": "0.5.1",
        "android_api": 35,
        "device_model": "Pixel",
        "startup_ms": 21.5,
        "startup_measurement": "application_to_first_frame",
        "frames_observed": 25,
        "frames_over_32ms": 2,
        "battery_session_delta_percent": -3,
        "backend_reachability": "reachable",
        "last_http_status": 200,
        "timed_events": [{"code": "sync_failed", "captured_at": utcnow()}],
        "failure_snapshots": [{"code": "app_crash", "captured_at": utcnow(), "memory_bytes": 1024}],
        "limitations": ["battery_delta_not_app_energy"],
    }
    assert backend.client.post("/v1/diagnostics/mobile", json=body).status_code == 201
    for update in [
        {"consent": False},
        {"device_model": "name@example.com"},
        {"timed_events": body["timed_events"] * 101},
        {"frames_over_32ms": -1},
        {"failure_snapshots": [{"code": "SECRET", "captured_at": utcnow()}]},
        {"limitations": ["arbitrary SECRET"]},
    ]:
        assert (
            backend.client.post("/v1/diagnostics/mobile", json={**body, **update}).status_code
            == 422
        )


@pytest.mark.parametrize(
    "error,code",
    [(RuntimeError, "backend_exception"), (sqlite3.OperationalError, "database_failed")],
)
def test_backend_exception_saves_only_registered_error_context(backend, error, code):
    from fastapi.testclient import TestClient

    @backend.app.get("/test/fault")
    async def fault():
        raise error("PRIVATE_EXCEPTION token=HIDDEN")

    client = TestClient(backend.app, raise_server_exceptions=False, headers=backend.headers)
    response = client.get("/test/fault")
    assert response.status_code == 503 and response.json()["code"] == code
    row = backend.store.one("SELECT payload FROM diagnostic_snapshots WHERE reason=?", (code,))
    assert row is not None and "PRIVATE_EXCEPTION" not in row["payload"]
    assert "HIDDEN" not in response.text
