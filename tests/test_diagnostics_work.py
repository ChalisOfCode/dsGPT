import io
import json
import zipfile

import pytest
from conftest import new_chat, pair, send, wait_run

from dsgpt.storage import utcnow


def snapshot(**updates):
    value = {
        "consent": True,
        "captured_at": utcnow(),
        "app_version": "0.1.0",
        "android_api": 37,
        "memory_bytes": 20_000_000,
        "latency_ms": 12.3,
        "thermal_status": 0,
        "events": ["app_started", "stream_interrupted"],
    }
    value.update(updates)
    return value


def test_diagnostic_export_omits_private_data_and_matches_preview(backend):
    secret = "password=do-not-export bearer=abc123 My secret conversation"
    run = send(backend, new_chat(backend, secret), secret).json()
    wait_run(backend, run["id"])
    preview = backend.client.post("/v1/diagnostics/exports/preview", json={}).json()
    assert secret not in json.dumps(preview)
    assert backend.credentials["token"] not in json.dumps(preview)
    response = backend.client.get(
        f"/v1/diagnostics/exports/{preview['id']}", params={"sha256": preview["sha256"]}
    )
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert set(archive.namelist()) == set(preview["files"])
        for name in archive.namelist():
            assert archive.read(name).decode() == preview["files"][name]
    bad = backend.client.get(
        f"/v1/diagnostics/exports/{preview['id']}", params={"sha256": "0" * 64}
    )
    assert bad.status_code == 409


def test_mobile_diagnostic_consent_and_combined_cached_report(backend):
    phone, _ = pair(backend)
    headers = {"Authorization": "Bearer " + phone["token"]}
    collection = backend.client.post("/v1/diagnostics/collections/" + phone["device_id"]).json()
    pending = backend.client.get("/v1/diagnostics/collections", headers=headers).json()
    assert pending[0]["id"] == collection["id"]
    assert (
        backend.client.post(
            "/v1/diagnostics/mobile", headers=headers, json=snapshot(consent=False)
        ).status_code
        == 422
    )
    uploaded = backend.client.post(
        "/v1/diagnostics/mobile",
        headers=headers,
        json=snapshot(),
        params={"collection_id": collection["id"]},
    )
    assert uploaded.status_code == 201, uploaded.text
    assert backend.client.get("/v1/diagnostics/collections", headers=headers).json() == []
    preview = backend.client.post(
        "/v1/diagnostics/exports/preview", json={"mobile_device": phone["device_id"]}
    ).json()
    assert preview["android"] == "cached_snapshot"
    manifest = json.loads(preview["files"]["manifest.json"])
    assert manifest["android_captured_at"]
    assert "android/app-diagnostics.json" in preview["files"]
    # A phone can also obtain desktop diagnostics using its explicit diagnostics permission.
    mobile_preview = backend.client.post(
        "/v1/diagnostics/exports/preview", headers=headers, json={}
    ).json()
    assert "desktop/system-info.json" in mobile_preview["files"]
    assert "android/app-diagnostics.json" in mobile_preview["files"]


@pytest.mark.parametrize(
    "updates",
    [
        {"raw_log": "password=secret"},
        {"app_version": "token_secret"},
        {"memory_bytes": "cookie-secret"},
        {"events": ["some private chat text"]},
        {"captured_at": "2026-10-18T03:00:00"},
        {"latency_ms": -1.0},
        {"consent": False},
        {"consent": "true"},
        {"android_api": "37"},
    ],
)
def test_raw_or_malformed_mobile_data_is_rejected(backend, updates):
    response = backend.client.post("/v1/diagnostics/mobile", json=snapshot(**updates))
    assert response.status_code == 422
    assert backend.store.all("SELECT * FROM snapshots") == []


def test_exports_cannot_be_read_by_another_device(backend):
    phone, _ = pair(backend)
    other, _ = pair(backend)
    headers = {"Authorization": "Bearer " + phone["token"]}
    assert (
        backend.client.post(
            "/v1/diagnostics/exports/preview",
            headers=headers,
            json={"mobile_device": other["device_id"]},
        ).status_code
        == 403
    )
    preview = backend.client.post("/v1/diagnostics/exports/preview", json={}).json()
    assert (
        backend.client.get(
            f"/v1/diagnostics/exports/{preview['id']}",
            headers=headers,
            params={"sha256": preview["sha256"]},
        ).status_code
        == 404
    )


def test_diagnostic_history_retention_and_missing_device(backend):
    backend.settings.diagnostic_retention = 2
    for _ in range(3):
        assert backend.client.post("/v1/diagnostics/mobile", json=snapshot()).status_code == 201
    assert len(backend.store.all("SELECT * FROM snapshots")) == 2
    with pytest.raises(ValueError):
        backend.store.log("password=arbitrary-secret")
    for _ in range(5):
        backend.store.log("backend_started", retention=2)
    assert len(backend.store.all("SELECT * FROM diagnostic_events")) == 2


def test_unavailable_platform_metrics_do_not_break_diagnostic_export(backend, monkeypatch):
    import psutil

    def unavailable(*args, **kwargs):
        raise psutil.NoSuchProcess(123456)

    monkeypatch.setattr(psutil, "Process", unavailable)
    monkeypatch.setattr(psutil, "virtual_memory", unavailable)
    response = backend.client.post("/v1/diagnostics/exports/preview", json={})
    assert response.status_code == 200
    system = json.loads(response.json()["files"]["desktop/system-info.json"])
    assert system["process_rss_bytes"] is None
    assert system["ram_total_bytes"] is None
    assert "ram" in system["unavailable_measurements"]


def test_diagnostic_disk_probe_passes_windows_compatible_string(backend, monkeypatch):
    import psutil

    original = psutil.disk_usage
    observed = []

    def windows_contract(path):
        if not isinstance(path, str):
            raise TypeError("Windows disk probe requires a string")
        observed.append(path)
        return original(path)

    monkeypatch.setattr(psutil, "disk_usage", windows_contract)
    snapshot = backend.client.post("/v1/diagnostics/snapshots")
    assert snapshot.status_code == 201
    preview = backend.client.post("/v1/diagnostics/exports/preview", json={})
    assert preview.status_code == 200 and len(observed) >= 2


def test_native_clients_receive_mobile_diagnostics_contract(backend):
    schema = backend.client.get("/v1/schema").json()
    request = schema["paths"]["/v1/diagnostics/mobile"]["post"]["requestBody"]
    assert request["content"]["application/json"]["schema"]["$ref"].endswith("/MobileSnapshot")
    assert "consent" in schema["components"]["schemas"]["MobileSnapshot"]["required"]
    assert schema["components"]["schemas"]["MobileSnapshot"]["additionalProperties"] is False


def test_work_tasks_report_blocker_and_persist_transitions(backend):
    row = backend.client.post(
        "/v1/work/tasks", json={"title": "Build app", "requirements": "Make an actual APK"}
    ).json()
    task_id = row["id"]
    assert row["execution_available"] is False
    for action, expected in [
        ("start", "blocked"),
        ("pause", "paused"),
        ("resume", "blocked"),
        ("stop", "stopped"),
    ]:
        response = backend.client.post(
            f"/v1/work/tasks/{task_id}/actions",
            json={"action": action, "revision": row["revision"]},
        )
        assert response.status_code == 200
        row = response.json()
        assert row["status"] == expected
    assert (
        backend.client.post(
            f"/v1/work/tasks/{task_id}/actions", json={"action": "resume", "revision": 1}
        ).status_code
        == 409
    )
    checkpoints = backend.client.get(f"/v1/work/tasks/{task_id}/checkpoints").json()
    assert len(checkpoints) == 4
    assert checkpoints[-1]["state"]["status"] == "stopped"


def test_diagnostics_reports_current_runner_readiness_without_private_configuration(backend):
    builds = backend.app.state.builds
    assert (
        backend.client.get("/v1/diagnostics/overview").json()["code_execution_available"] is False
    )
    builds.ready = True
    snapshot = backend.client.get("/v1/diagnostics/overview").json()
    assert snapshot["work_capability"] == "isolated_build"
    assert snapshot["code_execution_available"] is True
    builds.ready = False
    assert (
        backend.client.get("/v1/diagnostics/overview").json()["code_execution_available"] is False
    )
