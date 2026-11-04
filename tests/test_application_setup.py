"""Persistent setup must preserve user state and avoid claiming fixture acceptance."""

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from test_acceptance_harness import main as acceptance

from dsgpt import installation
from dsgpt.config import Settings

# Load the packaged entrypoint under its installed import names.
root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "dsgpt_acceptance", root / "scripts/acceptance/__init__.py"
)
package = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = package
spec.loader.exec_module(package)
sys.modules["dsgpt_acceptance.__main__"] = acceptance
spec = importlib.util.spec_from_file_location(
    "dsgpt_application_test", root / "scripts/application/__main__.py"
)
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


@pytest.mark.parametrize("ready,runtime_available", [(True, True), (True, False), (False, True)])
def test_update_launch_reuses_completed_setup_and_preserves_saved_state(
    tmp_path, monkeypatch, ready, runtime_available
):
    state = {
        "ready": ready,
        "phone_installed": True,
        "route": {"host": "pc.tail.ts.net", "port": 8443},
    }
    installation.save(tmp_path, state)
    before = (tmp_path / installation.STATE_FILE).read_bytes()
    monkeypatch.setattr(app.managed, "managed_directory", lambda: tmp_path)
    runtime = Mock(return_value=runtime_available)
    monkeypatch.setattr(app.installation, "start_saved_runtime", runtime)
    launch = Mock(return_value=0)
    monkeypatch.setattr(app.managed, "main", launch)
    process = Mock()
    monkeypatch.setattr(app.subprocess, "Popen", process)
    experience = Mock()
    monkeypatch.setattr(app, "start_experience", experience)
    assert app._main(["launch"]) == 0
    assert (tmp_path / installation.STATE_FILE).read_bytes() == before
    if ready and runtime_available:
        launch.assert_called_once_with(["launch"])
        experience.assert_called_once()
        process.assert_not_called()
    else:
        launch.assert_not_called()
        assert process.call_args.args[0][-2:] == ["dsgpt_application", "setup"]


def test_installed_host_is_exact_and_manual_configuration_is_preserved(tmp_path):
    settings = Settings(tmp_path, allowed_hosts=("localhost", "other.tail.ts.net"))
    installation.save(tmp_path, {"tailnet_host": "PC.tail.ts.net"})
    updated = installation.settings_for_installation(settings)
    assert updated.allowed_hosts == ("localhost", "other.tail.ts.net", "pc.tail.ts.net")
    assert settings.allowed_hosts == ("localhost", "other.tail.ts.net")
    for value in ("*", "https://pc.tail.ts.net", "pc.ts.net.evil.com", "..ts.net", "example.com"):
        installation.save(tmp_path, {"tailnet_host": value})
        with pytest.raises(ValueError):
            installation.settings_for_installation(settings)


def test_saved_runtime_reuses_existing_server_and_rejects_modified_executable(tmp_path):
    executable = tmp_path / "ollama.exe"
    executable.write_bytes(b"verified-cli")
    installation.remember_runtime(tmp_path, executable)
    launch = Mock()
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"models": []}))
    ) as client:
        assert installation.start_saved_runtime(tmp_path, client=client, launch=launch)
    launch.assert_not_called()
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503))) as client:
        assert installation.start_saved_runtime(tmp_path, client=client, launch=launch)
        assert launch.call_args.args[0] == [str(executable), "serve"]
        assert launch.call_args.kwargs["env"]["OLLAMA_HOST"] == "127.0.0.1:11434"
        assert launch.call_args.kwargs["env"]["OLLAMA_NO_CLOUD"] == "1"
        launch.reset_mock()
        executable.write_bytes(b"modified-cli")
        assert not installation.start_saved_runtime(tmp_path, client=client, launch=launch)
        launch.assert_not_called()


def route(port=8443, proxy="http://127.0.0.1:18765"):
    return {
        "TCP": {str(port): {"HTTPS": True}},
        "Web": {f"pc.tail.ts.net:{port}": {"Handlers": {"/": {"Proxy": proxy}}}},
    }


def test_tailscale_reuse_requires_owned_exact_private_route_and_preserves_foreign_routes():
    config = route()
    previous = {"host": "pc.tail.ts.net", "port": 8443}
    assert app.choose_route(config, previous["host"], previous) == (8443, True)
    assert app.choose_route(route(proxy="http://127.0.0.1:9000"), previous["host"], previous) == (
        18446,
        False,
    )
    config["AllowFunnel"] = {"pc.tail.ts.net:8443": True}
    assert not app.route_matches(config, previous["host"], 8443)
    assert app.choose_route(config, previous["host"], previous) == (18446, False)
    before = json.dumps(config)
    app.choose_route(config, previous["host"], previous)
    assert json.dumps(config) == before


def test_model_registration_is_durable_idempotent_and_does_not_overwrite_user_models():
    models = [
        {"id": "acceptance-local-0", "runtime_model": "local:9b", "expected_digest": "a" * 64}
    ]
    existing = [{"id": "user-custom"}]
    writes = []

    def request(method, path, body=None):
        if method == "GET":
            return existing
        writes.append(body)
        existing.append({"id": body["id"]})

    first = app.register_models(models, request)
    assert app.register_models(models, request) == first
    assert len(writes) == 1 and writes[0]["expected_digest"] == "a" * 64
    assert writes[0]["id"].startswith("local-")
    assert existing[0] == {"id": "user-custom"}


def test_setup_runs_real_persistent_path_and_never_acceptance_or_cleanup(tmp_path, monkeypatch):
    monkeypatch.setattr(app.managed, "managed_directory", lambda: tmp_path)
    setup = app.Setup(tmp_path, ci=True, launch=False)
    calls = []

    def done(name):
        return lambda: calls.append(name) or {"ok": True}

    for name in (
        "integrity",
        "desktop_dependencies",
        "local_setup",
        "private_connection",
        "prepare_backend",
        "tools",
        "search",
        "https",
        "install_phone",
    ):
        monkeypatch.setattr(setup, name, done(name))
    monkeypatch.setattr(setup, "resume_setup", lambda enable: calls.append(("resume", enable)))
    monkeypatch.setattr(app, "startup", lambda *a, **k: {"enabled": True})
    monkeypatch.setattr(setup, "finish", lambda: pytest.fail("Must not remove real app/backend"))
    monkeypatch.setattr(
        setup, "start_backend", lambda: pytest.fail("Must not create synthetic database")
    )
    try:
        assert setup.run_setup()
        assert installation.load(tmp_path)["ready"]
        assert calls.index("prepare_backend") < calls.index("tools")
        assert "install_phone" in calls and ("resume", False) in calls
        assert setup.report["scope"].startswith("Application installation")
        assert not (tmp_path / "backend").exists()
    finally:
        setup.http.close()


def test_failed_optional_tool_setup_keeps_core_and_records_repair_needed(tmp_path, monkeypatch):
    monkeypatch.setattr(app.managed, "managed_directory", lambda: tmp_path)
    setup = app.Setup(tmp_path, ci=True, launch=False)
    for name in (
        "integrity",
        "desktop_dependencies",
        "local_setup",
        "private_connection",
        "prepare_backend",
        "https",
        "install_phone",
    ):
        monkeypatch.setattr(setup, name, lambda: {})
    monkeypatch.setattr(app, "startup", lambda *a, **k: {})
    monkeypatch.setattr(setup, "resume_setup", lambda _: None)
    monkeypatch.setattr(setup, "tools", lambda: (_ for _ in ()).throw(RuntimeError("tool failure")))
    monkeypatch.setattr(setup, "search", lambda: pytest.fail("Docker unavailable"))
    try:
        assert not setup.run_setup()
        assert installation.load(tmp_path)["ready"] is False
        assert any(
            c["name"] == "Prepare document and build tools" and c["status"] == "FAIL"
            for c in setup.report["checks"]
        )
    finally:
        setup.http.close()


def phone_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(app.managed, "managed_directory", lambda: tmp_path / "data")
    setup = app.Setup(tmp_path, ci=True, launch=False)
    setup.state["phone_origin"] = "https://pc.tail.ts.net:8443"
    (tmp_path / "android").mkdir(exist_ok=True)
    (tmp_path / "android/dsGPT-Mobile.apk").write_bytes(b"reviewed APK fixture")
    setup.find_phone = Mock(return_value=("wifi-device", "hardware-hash"))
    return setup


@pytest.mark.parametrize("status", ["paired", "reused"])
def test_automatic_pairing_requires_phone_and_desktop_verification(tmp_path, monkeypatch, status):
    import subprocess

    setup = phone_setup(tmp_path, monkeypatch)
    identifier = "11111111-1111-4111-8111-111111111111"
    commands = []

    def command(argv, timeout=60):
        commands.append([str(v) for v in argv])
        output = b"Success" if "install" in argv else b""
        if "run-as" in argv:
            output = json.dumps(
                {"request": setup.phone_job, "status": status, "device_id": identifier}
            ).encode()
        return subprocess.CompletedProcess(argv, 0, output, b"")

    monkeypatch.setattr(app, "command", command)
    setup.request = Mock(
        side_effect=[
            {"code": "secret-one-use-code"},
            [{"id": identifier, "role": "client", "revoked": 0}],
        ]
    )
    try:
        result = setup.install_phone()
        assert result["phone_authenticated"] and not result["requires_phone_confirmation"]
        assert result["connection_reused"] == (status == "reused")
        assert any("install" in c and "-r" in c for c in commands)
        assert not any("uninstall" in c or "clear" in c for c in commands)
        assert any("com.dsgpt.mobile/.AutomaticPairingActivity" in c for c in commands)
        progress = (setup.directory / "phone-setup.json").read_text()
        assert json.loads(progress)["status"] == "succeeded"
        assert setup.report["phone_connection"]["status"] == "succeeded"
        assert "secret-one-use-code" not in progress
        assert installation.load(setup.directory)["phone_hardware"] == "hardware-hash"
    finally:
        setup.http.close()


@pytest.mark.parametrize("reply", ["different_desktop", "connection_failed", "paired_revoked"])
def test_pairing_failure_never_reports_success_or_wipes_previous_state(
    tmp_path, monkeypatch, reply
):
    import subprocess

    setup = phone_setup(tmp_path, monkeypatch)
    setup.state["phone_installed"] = True
    setup.directory.mkdir(parents=True)
    setup.persist()
    before = (setup.directory / installation.STATE_FILE).read_bytes()

    def command(argv, timeout=60):
        status = "paired" if reply == "paired_revoked" else reply
        output = (
            json.dumps(
                {
                    "request": setup.phone_job,
                    "status": status,
                    "device_id": "11111111-1111-4111-8111-111111111111",
                }
            ).encode()
            if "run-as" in argv
            else b"Success"
        )
        return subprocess.CompletedProcess(argv, 0, output, b"")

    monkeypatch.setattr(app, "command", command)
    setup.request = Mock(
        side_effect=[
            {"code": "secret-code"},
            [{"id": "11111111-1111-4111-8111-111111111111", "role": "client", "revoked": 1}],
        ]
    )
    try:
        with pytest.raises((app.Blocked, AssertionError)):
            setup.install_phone()
        assert (setup.directory / installation.STATE_FILE).read_bytes() == before
        assert (
            json.loads((setup.directory / "phone-setup.json").read_text())["status"] != "succeeded"
        )
    finally:
        setup.http.close()


def test_wireless_discovery_reuses_authorization_and_deduplicates_usb_alias(tmp_path, monkeypatch):
    import subprocess

    monkeypatch.setattr(app.managed, "managed_directory", lambda: tmp_path / "data")
    setup = app.Setup(tmp_path, ci=True, launch=False)
    commands = []

    def command(argv, timeout=60):
        commands.append([str(v) for v in argv])
        if "services" in argv:
            output = (
                b"pixel _adb-tls-connect._tcp. 192.168.1.2:40123\n"
                b"evil _adb-tls-connect._tcp. 8.8.8.8:5555\n"
                b"pair _adb-tls-pairing._tcp. 192.168.1.2:44111"
            )
        elif "devices" in argv:
            output = b"List of devices attached\nUSB1\tdevice\n192.168.1.2:40123\tdevice\n"
        elif "getprop" in argv:
            output = {
                "ro.product.model": b"Pixel 11 Pro",
                "ro.product.manufacturer": b"Google",
                "ro.serialno": b"same-phone",
            }[argv[-1]]
        else:
            output = b""
        return subprocess.CompletedProcess(argv, 0, output, b"")

    monkeypatch.setattr(app, "command", command)
    try:
        serial, identity = setup.find_phone(tmp_path / "adb.exe")
        assert serial == "192.168.1.2:40123" and len(identity) == 64
        assert [c[-1] for c in commands if "connect" in c] == ["192.168.1.2:40123"]
        assert not any("pair" in c or "tcpip" in c for c in commands)
    finally:
        setup.http.close()


def test_automatic_bridge_is_permission_protected_and_has_no_public_link_filter():
    import xml.etree.ElementTree as ET

    manifest = ET.parse(root / "clients/android/app/src/main/AndroidManifest.xml")
    android = "{http://schemas.android.com/apk/res/android}"
    activity = next(
        a
        for a in manifest.findall("./application/activity")
        if a.get(android + "name") == ".AutomaticPairingActivity"
    )
    assert activity.get(android + "permission") == "android.permission.DUMP"
    assert activity.find("intent-filter") is None


def test_https_approval_handoff_is_limited_to_vendor_host():
    output = "Enable https://login.tailscale.com/f/serve?node=abc then continue"
    assert app.serve_approval_urls(output) == {"https://login.tailscale.com/f/serve?node=abc"}
    for value in (
        "http://login.tailscale.com/f/serve",
        "https://login.tailscale.com.evil.test/",
        "https://evil.test/f/serve",
        "https://login.tailscale.com@evil.test/f",
    ):
        assert not app.serve_approval_urls(value)


def test_unavailable_phone_does_not_force_desktop_setup_on_every_launch(tmp_path, monkeypatch):
    monkeypatch.setattr(app.managed, "managed_directory", lambda: tmp_path)
    setup = app.Setup(tmp_path, ci=True, launch=False)
    for name in (
        "integrity",
        "desktop_dependencies",
        "local_setup",
        "private_connection",
        "prepare_backend",
        "tools",
        "search",
        "https",
    ):
        monkeypatch.setattr(setup, name, lambda: {})
    monkeypatch.setattr(app, "startup", lambda *a, **k: {})
    monkeypatch.setattr(setup, "resume_setup", lambda _: None)
    monkeypatch.setattr(
        setup, "install_phone", lambda: (_ for _ in ()).throw(app.Blocked("Phone offline"))
    )
    try:
        assert setup.run_setup()
        assert installation.load(tmp_path)["ready"] is True
        assert (
            json.loads((tmp_path / "phone-setup.json").read_text())["status"] == "needs_attention"
        )
    finally:
        setup.http.close()


def test_private_https_opens_vendor_consent_and_uses_noninteractive_serve(tmp_path, monkeypatch):
    setup = phone_setup(tmp_path, monkeypatch)
    setup.tailscale = "tailscale.exe"
    called = []

    class Process:
        returncode = 0

        def __init__(self, argv, **kwargs):
            called.append(argv)
            kwargs["stdout"].write(b"Approve https://login.tailscale.com/f/serve?node=abc\n")
            kwargs["stdout"].flush()

        def poll(self):
            return 0

        def wait(self):
            return 0

    monkeypatch.setattr(app.subprocess, "Popen", Process)
    browser = Mock()
    monkeypatch.setattr(app.webbrowser, "open", browser)
    try:
        setup.enable_private_https(8443)
        assert called == [
            ["tailscale.exe", "serve", "--bg", "--yes", "--https=8443", app.managed.ORIGIN]
        ]
        browser.assert_called_once_with("https://login.tailscale.com/f/serve?node=abc")
        status = (setup.directory / "phone-setup.json").read_text()
        assert "approval" in status and "node=abc" not in status
    finally:
        setup.http.close()


def test_existing_route_recovered_after_state_loss():
    host = "pc.tail.ts.net"
    config = {
        "TCP": {"8443": {"HTTPS": True}},
        "Web": {host + ":8443": {"Handlers": {"/": {"Proxy": app.managed.ORIGIN}}}},
    }
    assert app.choose_route(config, host, None) == (8443, True)
    config["AllowFunnel"] = {host + ":8443": True}
    assert app.choose_route(config, host, None) != (8443, True)


def test_existing_phone_pairing_survives_unavailable_debugging(tmp_path, monkeypatch):
    setup = phone_setup(tmp_path, monkeypatch)
    setup.find_phone = Mock(side_effect=app.Blocked("ADB offline"))
    setup.request = Mock(return_value={"phones": [{"id": "saved-device", "online": False}]})
    try:
        result = setup.install_phone(reconnect=True)
        assert result["connection_preserved"] and result["update_deferred"]
        assert setup.report["phone_connection"]["status"] == "paired"
        assert setup.request.call_count == 1
    finally:
        setup.http.close()
