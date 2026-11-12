"""Harness negative controls; not emulator or real-upgrade acceptance."""
import importlib.util
import json
import ssl
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "android_upgrade", Path(__file__).resolve().parents[1] / "scripts/check_android_upgrade.py")
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


def test_harness_refuses_owner_device_and_missing_runner():
    with pytest.raises(ValueError, match="disposable emulator"):
        driver.Android("owner-device")
    with pytest.raises(RuntimeError, match="disposable public"):
        driver.require_runner({})
    with pytest.raises(RuntimeError, match="disposable public"):
        driver.require_runner({"GITHUB_ACTIONS": "true", "RUNNER_TEMP": "/tmp",
                               "GITHUB_REPOSITORY": "ChalisOfCode/dsGPT-development"})


def test_missing_or_changed_reconnect_identity_cannot_pass():
    driver.check_connection({"status": "reused", "device_id": driver.DEVICE}, "reused")
    for receipt in ({"status": "paired", "device_id": driver.DEVICE},
                    {"status": "reused"}, {"status": "reused", "device_id": "another"}):
        with pytest.raises(AssertionError):
            driver.check_connection(receipt, "reused")


def test_https_fixture_rejects_repair_and_changed_token_and_survives_outage(tmp_path):
    key, cert, _ = driver.certificate(tmp_path)
    fixture = driver.Fixture()
    server = driver.ThreadingHTTPServer(("127.0.0.1", 0), driver.handler(fixture))
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(cert, key)
    server.socket = tls.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    context = ssl.create_default_context(cafile=str(cert))
    # The local test connects by IP; the emulator uses the certificate hostname.
    context.check_hostname = False
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                        urllib.request.HTTPSHandler(context=context))

    def call(path, token=None, body=None):
        request = urllib.request.Request(f"https://127.0.0.1:{server.server_port}" + path,
                  data=None if body is None else json.dumps(body).encode(),
                  headers={} if token is None else {"Authorization": "Bearer " + token})
        with opener.open(request, timeout=5) as response:
            return json.load(response)

    try:
        with pytest.raises(urllib.error.HTTPError) as failure:
            call("/v1/device", "wrong")
        assert failure.value.code == 401
        token = call("/v1/pairings/redeem", body={"code": fixture.code})["token"]
        assert call("/v1/device", token)["id"] == driver.DEVICE
        with pytest.raises(urllib.error.HTTPError) as failure:
            call("/v1/pairings/redeem", body={"code": fixture.code})
        assert failure.value.code == 401
        fixture.available = False
        with pytest.raises(urllib.error.HTTPError) as failure:
            call("/v1/device", token)
        assert failure.value.code == 503
        fixture.available = True
        assert call("/v1/device", token)["id"] == driver.DEVICE
        assert fixture.pairings == 1
    finally:
        server.shutdown()
        server.server_close()
