"""Driver guards and actual TLS/API fixture, not installed Android acceptance."""
import importlib.util
import ssl
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
