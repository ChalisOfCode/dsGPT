"""Regression cases from the physical Windows/Pixel report, including missing prerequisites."""

import importlib
import json
import os
import subprocess
from unittest.mock import Mock

import httpx
import pytest
from test_acceptance_harness import main, make_runner

setup = importlib.import_module("dsgpt_acceptance_test.setup")


def response(argv, out=b"", code=0):
    return subprocess.CompletedProcess(argv, code, out, b"")


def test_wait_keeps_detecting_after_old_deadline_and_advances_without_enter(monkeypatch):
    monkeypatch.setattr(setup, "interactive", lambda ci: True)
    monkeypatch.setattr(setup, "skip_pressed", lambda: False)
    monkeypatch.setattr(setup.time, "sleep", lambda _: None)
    states = iter([(None, "unauthorized"), (None, "offline"), ("ready", "authorized")])
    assert setup.wait_ready(lambda: next(states), "Pixel", timeout=0) == "ready"


def test_skip_is_a_blocker_and_unattended_wait_is_bounded(monkeypatch):
    monkeypatch.setattr(setup, "interactive", lambda ci: True)
    monkeypatch.setattr(setup, "skip_pressed", lambda: True)
    with pytest.raises(main.Blocked, match="Skipped by user"):
        setup.wait_ready(lambda: (None, "pending"), "Pixel")
    monkeypatch.setattr(setup, "interactive", lambda ci: False)
    with pytest.raises(main.Blocked, match="Unattended wait expired"):
        setup.wait_ready(lambda: (None, "pending"), "Pixel", timeout=0)


def test_missing_ollama_installs_starts_downloads_and_verifies_model(tmp_path, monkeypatch):
    runner = make_runner(tmp_path)
    runner.args.ci = False
    installed, spawned, requests = [], [], []
    monkeypatch.setattr(main, "executable", lambda *args: None)
    monkeypatch.setattr(runner, "vendor_install", lambda *a: pytest.fail("No desktop installer"))

    def install():
        installed.append("standalone_cli")
        return "installed-ollama.exe"

    monkeypatch.setattr(runner, "install_ollama_runtime", install)
    monkeypatch.setattr(runner, "spawn", lambda argv, env: spawned.append((argv, env)))
    tags, pulled = 0, False

    def handler(request):
        nonlocal tags, pulled
        requests.append((request.url.host, request.url.path))
        assert request.url.host == "127.0.0.1"
        if request.url.path == "/api/tags":
            tags += 1
            if tags == 1:
                raise httpx.ConnectError("not installed", request=request)
            models = (
                [{"name": "qwen3:1.7b", "size": 1400000000, "digest": "a" * 64}] if pulled else []
            )
            return httpx.Response(200, json={"models": models})
        if request.url.path == "/api/pull":
            assert json.loads(request.content) == {"model": "qwen3:1.7b", "stream": True}
            pulled = True
            return httpx.Response(200, content=b'{"status":"success"}\n')
        if request.url.path == "/api/show":
            return httpx.Response(
                200, json={"model_info": {"architecture": "qwen3"}, "capabilities": ["completion"]}
            )
        raise AssertionError(str(request.url))

    runner.http.close()
    runner.http = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        result = runner.discover_models()
        assert installed == ["standalone_cli"]
        assert spawned[0][0] == ["installed-ollama.exe", "serve"]
        assert spawned[0][1]["OLLAMA_HOST"] == "127.0.0.1:11434"
        assert spawned[0][1]["OLLAMA_NO_CLOUD"] == "1"
        assert result["downloaded_acceptance_model"] and not result["hosted_inference"]
        assert runner.models[0]["expected_digest"] == "a" * 64
    finally:
        runner.http.close()


def test_running_ollama_needs_no_cli_install_and_remote_models_are_rejected(tmp_path, monkeypatch):
    runner = make_runner(tmp_path)
    monkeypatch.setattr(main, "executable", lambda *a: pytest.fail("Running server needs no CLI"))
    monkeypatch.setattr(runner, "vendor_install", lambda *a: pytest.fail("Must reuse server"))
    entries = [
        {"name": "other-remote:9b", "size": 10, "digest": "b" * 64},
        {"name": "local:8b", "size": 100, "digest": "c" * 64},
    ]

    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": entries})
        assert request.url.path == "/api/show"
        remote = json.loads(request.content)["model"] == "other-remote:9b"
        return httpx.Response(
            200,
            json={
                "model_info": {"arch": "test"},
                **({"remote_host": "cloud.example"} if remote else {}),
            },
        )

    runner.http.close()
    runner.http = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        assert runner.discover_models()["models"] == ["local:8b"]
    finally:
        runner.http.close()


def test_phone_late_authorization_retries_and_report_excludes_serial(tmp_path, monkeypatch):
    runner = make_runner(tmp_path)
    states = iter(
        [
            b"PRIVATE_SERIAL unauthorized",
            b"PRIVATE_SERIAL offline",
            b"PRIVATE_SERIAL device product:pixel",
        ]
    )
    calls = []
    monkeypatch.setattr(main, "executable", lambda *a: "adb")
    monkeypatch.setattr(setup.time, "sleep", lambda _: None)

    def command(argv, *args, **kwargs):
        calls.append(argv)
        if "devices" in argv:
            return response(argv, b"List of devices attached\n" + next(states) + b"\n")
        return response(argv, b"DSGPT_READY\n" if "shell" in argv else b"")

    monkeypatch.setattr(main, "command", command)
    try:
        assert runner.phone_detect()["authorized_shell_verified"]
        assert runner.phone == "PRIVATE_SERIAL"
        evidence = (runner.share / "phone-connection.json").read_text()
        assert "PRIVATE_SERIAL" not in evidence
        assert "unauthorized" in evidence and "offline" in evidence and "device" in evidence
        assert ["adb", "reconnect", "offline"] in calls
    finally:
        runner.http.close()


def test_ambiguous_devices_are_not_silently_selected():
    devices = setup.adb_devices(b"List of devices attached\na device\nb unauthorized\n")
    assert len(devices) == 2 and "Several" in setup.adb_guidance(devices)
    assert "RSA" in setup.adb_guidance([("a", "unauthorized")])
    assert "data-capable" in setup.adb_guidance([])


def test_installer_reboot_is_checkpointed_and_stops_dependent_checks(tmp_path, monkeypatch):
    runner = make_runner(tmp_path)
    runner.args.ci = False
    proxy = Mock(wraps=os)
    proxy.name = "nt"
    monkeypatch.setattr(main, "os", proxy)
    monkeypatch.setattr(main, "executable", lambda *a: "winget.exe")
    registered, calls = [], []
    monkeypatch.setattr(
        main, "resume_after_reboot", lambda kit, enable, **kw: registered.append(enable)
    )

    def launch(argv):
        calls.append(argv)
        return Mock(poll=lambda: 3010, returncode=3010)

    monkeypatch.setattr(main.subprocess, "Popen", launch)
    try:
        with pytest.raises(main.RestartRequired):
            runner.check("Install", lambda: runner.vendor_install("Docker.DockerDesktop"))
        assert registered == [True] and runner.needs_restart
        assert "--silent" in calls[0] and "--no-upgrade" in calls[0]
        assert calls[0][calls[0].index("--override") + 1] == (
            "install --user --quiet --accept-license --backend=wsl-2"
        )
        saved = json.loads((runner.share / "report.json").read_text())
        assert saved["checks"][0]["status"] == "BLOCKED"
        assert "restart" in saved["checks"][0]["detail"].lower()
    finally:
        runner.http.close()


def test_tailscale_rechecks_late_connection_without_exposing_account(tmp_path, monkeypatch):
    runner = make_runner(tmp_path)
    monkeypatch.setattr(main, "executable", lambda *a: "tailscale")
    states = iter(
        [
            {"BackendState": "Stopped"},
            {"BackendState": "Running", "Self": {"DNSName": "private-account.example.ts.net."}},
        ]
    )
    monkeypatch.setattr(main, "command", lambda *a: response(a, json.dumps(next(states)).encode()))
    calls = []
    monkeypatch.setattr(runner, "spawn", lambda argv: calls.append(argv))
    monkeypatch.setattr(setup.time, "sleep", lambda _: None)
    try:
        assert runner.tailscale_setup()["pc_connected"]
        assert calls == [["tailscale", "up", "--timeout=30s"]]
        assert runner.tailnet == "private-account.example.ts.net"
        assert "private-account" not in json.dumps(runner.clean(runner.tailnet))
    finally:
        runner.http.close()


@pytest.mark.parametrize(
    "address",
    [
        "8.8.8.8:443",
        "localhost:5555",
        "127.0.0.1:5037",
        "192.168.1.2:0",
        "192.168.1.2:70000",
        "--help",
    ],
)
def test_wireless_endpoint_rejects_public_localhost_and_invalid_ports(address):
    with pytest.raises(ValueError):
        setup.wireless_endpoint(address)


def test_wireless_pairing_discovery_only_accepts_private_tls_pairing_services():
    output = (
        b"List of discovered mdns services\n"
        b"phone _adb-tls-pairing._tcp. 192.168.1.4:37855\n"
        b"phone _adb-tls-connect._tcp. 192.168.1.4:39999\n"
        b"other _adb-tls-pairing._tcp. 8.8.8.8:443\n"
    )
    assert setup.pairing_endpoints(output) == ["192.168.1.4:37855"]
    assert setup.wireless_serial("adb-private._adb-tls-connect._tcp.")
    assert not setup.wireless_serial("USB_PRIVATE_SERIAL")


def test_first_wireless_pairing_discovers_address_and_keeps_code_out_of_argv(tmp_path, monkeypatch):
    import getpass

    runner = make_runner(tmp_path)
    runner.args.ci = False
    runner.adb_bin = "adb"
    paired, calls = False, []
    monkeypatch.setattr(main.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "")
    monkeypatch.setattr(getpass, "getpass", lambda prompt: "123456")

    def command(argv, *a, **kw):
        if "devices" in argv:
            return response(argv, b"192.168.1.4:39999 device" if paired else b"")
        assert argv == ["adb", "mdns", "services"]
        return response(argv, b"phone _adb-tls-pairing._tcp. 192.168.1.4:37855\n")

    def pair(argv, **kw):
        nonlocal paired
        calls.append((argv, kw))
        paired = True
        return response(argv, b"Successfully paired to 192.168.1.4:37855")

    monkeypatch.setattr(main, "command", command)
    monkeypatch.setattr(main.subprocess, "run", pair)
    try:
        runner.wireless_pairing()
        assert calls[0][0] == ["adb", "pair", "192.168.1.4:37855"]
        assert calls[0][1]["input"] == b"123456\n"
        assert "123456" not in str(calls[0][0])
        assert runner.clean("123456") == "[redacted]"
        assert "tcpip" not in str(calls)
    finally:
        runner.http.close()


def test_wireless_mode_reuses_pairing_selects_network_transport_and_skips_usb_driver(
    tmp_path, monkeypatch
):
    runner = make_runner(tmp_path)
    runner.args.wireless = True
    monkeypatch.setattr(main, "executable", lambda *a: "adb")
    monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("Pairing must be reused"))
    monkeypatch.setattr(
        main, "google_usb_inventory", lambda *a: pytest.fail("No USB driver needed")
    )

    def command(argv, *a, **kw):
        if "devices" in argv:
            return response(argv, b"USB_SERIAL device\n192.168.1.4:39999 device\n")
        return response(argv, b"DSGPT_READY\n" if "shell" in argv else b"")

    monkeypatch.setattr(main, "command", command)
    try:
        result = runner.phone_detect()
        assert result["debug_transport"] == "wireless debugging"
        assert runner.phone == "192.168.1.4:39999"
        assert "192.168.1.4" not in (runner.share / "phone-connection.json").read_text()
    finally:
        runner.http.close()
