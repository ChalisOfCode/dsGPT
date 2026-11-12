"""Driver guards and actual TLS/API fixture, not installed Android acceptance."""
import asyncio
import importlib.util
import ssl
import threading
import time
from pathlib import Path

import httpx
import pytest

spec = importlib.util.spec_from_file_location(
    "android_upgrade_driver", Path(__file__).parents[1] / "scripts/check_android_upgrade.py")
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


def test_driver_rejects_nonrunner_or_unowned_directory(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    with pytest.raises(RuntimeError):
        driver.require_runner(tmp_path)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REPOSITORY", "ChalisOfCode/dsGPT")
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    with pytest.raises(ValueError):
        driver.require_runner(tmp_path)
    with pytest.raises(ValueError):
        driver.require_runner(tmp_path.parent / "other")


def test_controlled_tls_backend_retains_actual_paired_authority_after_restart(tmp_path):
    driver.certificate(tmp_path)
    context = ssl.create_default_context(cafile=str(tmp_path / "ca.pem"))
    with driver.Backend(tmp_path) as backend:
        owner = backend.token
        code = backend.pairing()
        with httpx.Client(verify=context, trust_env=False, timeout=5,
                          headers={"Host": driver.HOST}) as client:
            url = f"https://127.0.0.1:{driver.PORT}"
            reply = client.post(url + "/v1/pairings/redeem", json={
                "code": code, "name": "Synthetic upgrade test"})
            assert reply.status_code == 200
            headers = {"Authorization": "Bearer " + reply.json()["token"]}
            identity = client.get(url + "/v1/device", headers=headers)
            assert identity.status_code == 200
            expected = identity.json()
            assert expected["role"] == "client"
            assert set(expected["scopes"]) == {"chat", "work", "diagnostics"}
            observed = set(backend.observed_tokens)
            assert len(observed) == 1
    with driver.Backend(tmp_path, owner) as backend:
        with httpx.Client(verify=context, trust_env=False, timeout=5,
                          headers={"Host": driver.HOST}) as client:
            identity = client.get(url + "/v1/device", headers=headers)
            assert identity.status_code == 200
            assert identity.json() == expected
            assert backend.observed_tokens == observed
            assert len(backend.devices()) == 1


def test_fixture_shutdown_cancels_inflight_request_and_releases_listener(tmp_path):
    """A connected client must not keep the disposable backend alive forever."""
    driver.certificate(tmp_path)
    context = ssl.create_default_context(cafile=str(tmp_path / "ca.pem"))
    entered, cancelled = threading.Event(), threading.Event()
    backend = driver.Backend(tmp_path)

    @backend.app.get("/fixture-held-request")
    async def held_request():
        entered.set()
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.set()

    outcomes = []

    def request():
        try:
            with httpx.Client(verify=context, trust_env=False, timeout=15,
                              headers={"Host": driver.HOST}) as client:
                response = client.get(f"https://127.0.0.1:{driver.PORT}/fixture-held-request")
                outcomes.append(response.status_code)
        except httpx.HTTPError:
            outcomes.append("disconnected")

    with backend:
        reader = threading.Thread(target=request, daemon=True)
        reader.start()
        assert entered.wait(5)
        started = time.monotonic()
    assert time.monotonic() - started < 8
    reader.join(3)
    assert cancelled.is_set()
    assert not reader.is_alive()
    assert not backend.thread.is_alive()
    assert outcomes == [500] or outcomes == ["disconnected"]
    # A fresh actual backend must bind the same TLS listener and retained store.
    with driver.Backend(tmp_path, backend.token) as restarted:
        assert restarted.request("/v1/device")["role"] == "owner"
