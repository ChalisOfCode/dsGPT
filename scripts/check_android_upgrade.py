"""Exact production APK update on a disposable, rooted API-28 emulator.

Root is used only for fixture trust/hostname setup and read-only observation.
The unchanged applications pair over real TLS, create/use AndroidKeyStore keys,
and update with adb install -r. No app data, keys or preferences are injected.
The fixture CA is not a real Tailscale certificate; physical routing is untested.
"""

import argparse
import contextlib
import hashlib
import json
import os
import re
import subprocess
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from pathlib import Path

PACKAGE = "com.dsgpt.mobile"
HOST = "dsgpt-upgrade-fixture.ts.net"
PORT = 18443
ORIGIN = f"https://{HOST}:{PORT}"
CHAT_TITLE = "Upgrade retained chat"


def require_runner(private):
    if (os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("GITHUB_REPOSITORY") != "ChalisOfCode/dsGPT"
            or os.name != "posix"):
        raise RuntimeError("Requires disposable public Linux runner")
    root = Path(os.environ["RUNNER_TEMP"]).resolve()
    if private.resolve() == root or not private.resolve().is_relative_to(root):
        raise ValueError("Private fixture must remain in runner temporary storage")


def command(args, timeout=30):
    result = subprocess.run(args, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError("Bounded fixture command failed")
    return result.stdout


def adb(*args, timeout=30):
    return command(["adb", "-s", "emulator-5554", *args], timeout)


def wait(check, seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(0.5)
    raise RuntimeError("Bounded fixture observation expired")


def certificate(private):
    import ipaddress

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    now = datetime.now(UTC)
    authority = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Disposable upgrade fixture")])
    ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
          .public_key(authority.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(hours=1))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .add_extension(x509.KeyUsage(True, False, False, False, False, True, True, None, None),
                         critical=True).sign(authority, hashes.SHA256()))
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, HOST)]))
            .issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(hours=1))
            .add_extension(x509.SubjectAlternativeName([
                x509.DNSName(HOST), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), True)
            .sign(authority, hashes.SHA256()))
    (private / "ca.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    (private / "tls.pem").write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    (private / "tls-key.pem").write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()))
    os.chmod(private / "tls-key.pem", 0o600)


def fixture_trust(private):
    # API 28 keeps its system trust store in /system, before Conscrypt APEX.
    if adb("shell", "getprop", "ro.build.version.sdk").strip() != b"28":
        raise RuntimeError("Unexpected emulator API")
    adb("root")
    adb("wait-for-device")
    if adb("shell", "id", "-u").strip() != b"0":
        raise RuntimeError("Disposable emulator root unavailable")
    adb("remount")
    digest = command(["openssl", "x509", "-in", str(private / "ca.pem"),
                      "-subject_hash_old", "-noout"]).decode().strip()
    if not re.fullmatch(r"[a-f0-9]{8}", digest):
        raise RuntimeError("Unexpected fixture certificate hash")
    target = f"/system/etc/security/cacerts/{digest}.0"
    adb("push", str(private / "ca.pem"), target)
    adb("shell", "chmod", "644", target)
    # Only the disposable image is modified, before either app is installed.
    hosts = private / "hosts"
    hosts.write_text("127.0.0.1 localhost\n::1 localhost\n10.0.2.2 " + HOST + "\n")
    adb("push", str(hosts), "/system/etc/hosts")
    adb("shell", "chmod", "644", "/system/etc/hosts")


class Backend:
    def __init__(self, private, token=None):
        from fastapi.testclient import TestClient

        from dsgpt.api import create_app
        from dsgpt.config import Settings

        self.private = private
        self.app = create_app(Settings(private / "backend", {}, allowed_hosts=(HOST, "testserver")))
        self.token = token or self.app.state.auth.initialize_owner()["token"]
        self.client = TestClient(self.app, headers={"Authorization": "Bearer " + self.token})
        self.observed_tokens = set()

        @self.app.middleware("http")
        async def observe(request, call_next):
            response = await call_next(request)
            if request.url.path == "/v1/device" and response.status_code == 200:
                self.observed_tokens.add(hashlib.sha256(
                    request.headers.get("authorization", "").encode()).hexdigest())
            return response

    def __enter__(self):
        import uvicorn

        self.client.__enter__()
        self.server = uvicorn.Server(uvicorn.Config(
            self.app, host="127.0.0.1", port=PORT, lifespan="off", access_log=False,
            log_level="critical", ssl_keyfile=str(self.private / "tls-key.pem"),
            ssl_certfile=str(self.private / "tls.pem")))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        wait(lambda: self.server.started, 10)
        return self

    def __exit__(self, *args):
        self.server.should_exit = True
        self.thread.join(10)
        self.client.__exit__(*args)
        if self.thread.is_alive():
            raise RuntimeError("Fixture backend did not stop")

    def request(self, path, data=None):
        response = (self.client.get(path) if data is None else self.client.post(path, json=data))
        if response.status_code not in {200, 201}:
            raise RuntimeError("Fixture backend request failed")
        return response.json()

    def pairing(self):
        return self.request("/v1/pairings", {"scopes": ["chat", "work", "diagnostics"]})["code"]

    def devices(self):
        return [{k: r[k] for k in ("id", "role", "scopes", "revoked")}
                for r in self.request("/v1/devices") if r["role"] != "owner"]


def app_file(relative):
    # Read-only emulator observation. Never change app files or export keystore keys.
    return adb("shell", "cat", f"/data/user/0/{PACKAGE}/{relative}")


def vault_digest():
    root = ET.fromstring(app_file("shared_prefs/connection.xml"))
    values = {node.attrib.get("name"): node.text for node in root}
    if not values.get("data") or not values.get("iv"):
        raise RuntimeError("Application did not save encrypted credential")
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def package_identity(version):
    output = adb("shell", "dumpsys", "package", PACKAGE).decode()
    uid = re.search(r"\buserId=(\d+)", output)
    code = re.search(r"\bversionCode=(\d+)\b", output)
    if not uid or not code or int(code[1]) != version:
        raise RuntimeError("Installed production identity/version differs")
    return uid[1]


def connect(code, expected):
    request = uuid.uuid4().hex
    adb("shell", "am", "force-stop", PACKAGE)
    adb("shell", "am", "start", "-W", "-n", PACKAGE + "/.AutomaticPairingActivity",
        "--es", "dsgpt_origin", ORIGIN, "--es", "dsgpt_pairing", code,
        "--es", "dsgpt_request", request)

    def result():
        try:
            raw = app_file("files/phone-connection-result.json")
            if len(raw) > 4096:
                raise RuntimeError("Oversized application bridge result")
            value = json.loads(raw)
            return value if value.get("request") == request else None
        except (RuntimeError, ValueError):
            return None

    reply = wait(result, 100)
    if reply.get("status") != expected:
        raise RuntimeError("Application reconnect result differs")
    return reply.get("device_id")


def visible_chat():
    def ready():
        try:
            adb("shell", "uiautomator", "dump", "/data/local/tmp/upgrade-ui.xml")
            value = adb("shell", "cat", "/data/local/tmp/upgrade-ui.xml")
            nodes = list(ET.fromstring(value).iter("node"))
            if any(CHAT_TITLE in node.attrib.get("text", "") for node in nodes):
                return True
            sidebar = next((node for node in nodes
                            if node.attrib.get("content-desc") == "Open sidebar"), None)
            if sidebar is not None:
                bounds = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]",
                                      sidebar.attrib.get("bounds", ""))
                if bounds:
                    x1, y1, x2, y2 = map(int, bounds.groups())
                    adb("shell", "input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2))
            return False
        except (RuntimeError, ET.ParseError):
            return False
    wait(ready, 25)


def check_preserved(before, after):
    if before != after:
        raise AssertionError("Original data or paired authority changed")


def run(private, report):
    from upgrade_binary_transfer import FILES, check_files

    require_runner(private)
    check_files({name: (private / name).read_bytes() for name in FILES})
    stage = "fixture_trust"
    try:
        certificate(private)
        fixture_trust(private)
        # Fail closed on an already installed production package; never uninstall it.
        if b"package:" + PACKAGE.encode() in adb("shell", "pm", "list", "packages", PACKAGE):
            raise RuntimeError("Emulator is not a clean installation target")
        stage = "baseline_install"
        if b"Success" not in adb("install", str(private / "baseline.apk"), timeout=90):
            raise RuntimeError("Baseline installation failed")
        before_uid = package_identity(23)
        with Backend(private) as backend:
            token = backend.token
            chat = backend.request("/v1/conversations", {"title": CHAT_TITLE})
            task = backend.request("/v1/work/tasks", {
                "title": "Upgrade retained Work", "requirements": "Preserve café 原文",
                "source_files": [{"name": "original.txt", "text": "Original café 原文\n"}]})
            before_chat = backend.request("/v1/conversations")
            before_task = backend.request("/v1/work/tasks/" + task["id"])
            stage = "baseline_pairing"
            identity = connect(backend.pairing(), "paired")
            before_vault = vault_digest()
            before_devices = backend.devices()
            assert len(before_devices) == 1 and before_devices[0]["id"] == identity
            before_auth = set(backend.observed_tokens)
            assert len(before_auth) == 1
            visible_chat()
            stage = "in_place_install"
            adb("shell", "am", "force-stop", PACKAGE)
            if b"Success" not in adb("install", "-r", str(private / "candidate.apk"), timeout=90):
                raise RuntimeError("Candidate in-place installation failed")
            check_preserved(before_uid, package_identity(24))
            check_preserved(before_vault, vault_digest())
            stage = "candidate_reconnect"
            backend.observed_tokens.clear()
            check_preserved(identity, connect(backend.pairing(), "reused"))
            check_preserved(before_auth, backend.observed_tokens)
            check_preserved(before_devices, backend.devices())
            check_preserved(before_vault, vault_digest())
            visible_chat()
            check_preserved(before_chat, backend.request("/v1/conversations"))
            check_preserved(before_task, backend.request("/v1/work/tasks/" + task["id"]))
            # Keep a syntactically valid unredeemed code for the offline attempt.
            pending_code = backend.pairing()
        stage = "offline_preservation"
        connect(pending_code, "connection_failed")
        check_preserved(before_vault, vault_digest())
        stage = "backend_restart_start"
        with Backend(private, token) as backend:
            stage = "backend_restart_identity"
            check_preserved(identity, connect(backend.pairing(), "reused"))
            stage = "backend_restart_token"
            check_preserved(before_auth, backend.observed_tokens)
            stage = "backend_restart_device_scopes"
            check_preserved(before_devices, backend.devices())
            stage = "backend_restart_vault"
            check_preserved(before_vault, vault_digest())
            stage = "backend_restart_chat_data"
            check_preserved(before_chat, backend.request("/v1/conversations"))
            stage = "backend_restart_work_data"
            check_preserved(before_task, backend.request("/v1/work/tasks/" + task["id"]))
            stage = "backend_restart_messages"
            assert backend.request("/v1/conversations/" + chat["id"] + "/messages") == []
            stage = "backend_restart_native_history"
            visible_chat()
            stage = "backend_restart_shutdown"
        report.write_text(json.dumps({
            "passed": True, "baseline_sha256": FILES["baseline.apk"][1],
            "candidate_sha256": FILES["candidate.apk"][1], "api_level": 28,
            "in_place_update_23_to_24": True, "uid_preserved": True,
            "encrypted_preferences_unchanged": True, "keystore_decryption_authenticated": True,
            "paired_identity_scopes_and_token_preserved": True,
            "prior_chat_visible_in_both_apps": True, "original_backend_data_preserved": True,
            "offline_failure_preserved_credential": True, "fresh_backend_reconnect": True,
            "controlled_system_ca_and_hostname": True, "physical_tailscale_verified": False,
        }, indent=2) + "\n")
        print("Exact production APK in-place update and reconnect checks passed.")
    except Exception as exc:
        # Never publish request/credential, subprocess output, private path or traceback.
        kind = type(exc).__name__
        safe_types = {"AssertionError", "RuntimeError", "TimeoutExpired", "ValueError", "OSError"}
        if kind not in safe_types:
            kind = "Other"
        report.write_text(json.dumps({"passed": False, "failed_stage": stage,
                                      "failure_type": kind}) + "\n")
        raise RuntimeError("Android upgrade acceptance failed at " + stage) from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    try:
        run(args.private, args.report)
    except Exception:
        print("Android upgrade acceptance failed; see the bounded stage receipt.")
        raise SystemExit(1) from None
    finally:
        with contextlib.suppress(Exception):
            adb("shell", "rm", "-f", "/data/local/tmp/upgrade-ui.xml")


if __name__ == "__main__":
    main()
