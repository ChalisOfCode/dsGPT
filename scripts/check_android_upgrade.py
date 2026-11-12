"""Exact production APK upgrade on a fresh, rooted disposable API-28 emulator.

Uses an isolated HTTPS API fixture and test-only emulator trust/DNS mapping.
Exercises unchanged production APKs and AndroidKeyStore, not real Tailscale,
backend migrations, model inference, or owner hardware. Never imports a signing key.
"""

import argparse
import hashlib
import json
import os
import re
import secrets
import ssl
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

PACKAGE = "com.dsgpt.mobile"
HOST = "upgrade-fixture.test.ts.net"
DEVICE = "11111111-2222-4333-8444-555555555555"
PINS = {
    "baseline": "d60013f75a657f022681b97ee6925719b80fc573ab4c30f5b2cc95aeb7bbcb41",
    "candidate": "d3ce920b2ee1e7d5110f959d9c663c3e284619a234e7f35f73975feef8c512db",
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require_runner(env):
    if (env.get("GITHUB_ACTIONS") != "true"
            or env.get("GITHUB_REPOSITORY") != "ChalisOfCode/dsGPT"
            or not env.get("RUNNER_TEMP")):
        raise RuntimeError("Requires an owned disposable public Actions runner")


class Fixture:
    def __init__(self):
        self.code = secrets.token_urlsafe(24)
        self.token = secrets.token_urlsafe(32)
        self.pairings = 0
        self.models = 0
        self.identities = 0
        self.rejected = 0
        self.available = True
        self.lock = threading.Lock()

    def request(self, method, path, authorization, body):
        with self.lock:
            if not self.available:
                return 503, {"detail": "Synthetic outage"}
            if path == "/v1/pairings/redeem" and method == "POST":
                if body.get("code") != self.code or self.pairings:
                    self.rejected += 1
                    return 401, {"detail": "No second pairing allowed"}
                self.pairings += 1
                return 200, {"token": self.token}
            if authorization != "Bearer " + self.token:
                self.rejected += 1
                return 401, {"detail": "Unauthorized"}
            if path == "/v1/device":
                self.identities += 1
                return 200, {"id": DEVICE, "role": "client", "scopes": ["chat"]}
            if path == "/v1/models":
                self.models += 1
                return 200, []
            if path == "/v1/conversations":
                return 200, []
            if path == "/v1/research/capabilities":
                return 200, {"search_configured": False, "public_page_reading": False}
            if path == "/v1/device/heartbeat" and method == "POST":
                return 200, {"ok": True}
            return 404, {"detail": "Unsupported fixture route"}


def handler(fixture):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Never log tokens, intent parameters, headers or bodies.

        def dispatch(self):
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= 16384:
                self.send_error(413)
                return
            try:
                body = json.loads(self.rfile.read(length)) if length else {}
                if not isinstance(body, dict):
                    raise ValueError("Object required")
            except (ValueError, UnicodeError):
                self.send_error(400)
                return
            code, result = fixture.request(
                self.command, urlsplit(self.path).path,
                self.headers.get("Authorization"), body)
            data = json.dumps(result).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = dispatch
        do_POST = dispatch

    return Handler


def wait_for(check, seconds=45):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(.5)
    raise TimeoutError("Bounded Android upgrade observation did not arrive")


class Android:
    def __init__(self, serial):
        if serial != "emulator-5554":
            raise ValueError("Only the fixed disposable emulator is allowed")
        self.prefix = ["adb", "-s", serial]

    def run(self, *args, timeout=45, check=True):
        proc = subprocess.run(self.prefix + list(args), capture_output=True, timeout=timeout)
        if check and proc.returncode:
            # Captured output may contain synthetic credential parameters. Do not echo it.
            raise RuntimeError("Android command failed")
        return proc.stdout

    def installed(self):
        text = self.run("shell", "dumpsys", "package", PACKAGE).decode()
        uid = re.search(r"\buserId=(\d+)", text)
        version = re.search(r"\bversionCode=(\d+)", text)
        if not uid or not version:
            raise AssertionError("Installed production identity missing")
        return int(uid[1]), int(version[1])

    def stop(self):
        self.run("shell", "am", "force-stop", PACKAGE)

    def prefs(self):
        data = self.run("shell", "cat", f"/data/user/0/{PACKAGE}/shared_prefs/connection.xml")
        if b'name="data"' not in data or b'name="iv"' not in data:
            raise AssertionError("Production encrypted connection was not saved")
        return sha(data)

    def connect(self, origin, code):
        request = secrets.token_hex(16)
        self.run("shell", "am", "start", "-W", "-n", PACKAGE + "/.AutomaticPairingActivity",
                 "--es", "dsgpt_origin", origin, "--es", "dsgpt_pairing", code,
                 "--es", "dsgpt_request", request)

        def receipt():
            raw = self.run(
                "shell", "cat", f"/data/user/0/{PACKAGE}/files/phone-connection-result.json",
                check=False)
            try:
                value = json.loads(raw)
            except (ValueError, UnicodeError):
                return None
            return value if value.get("request") == request else None

        return wait_for(receipt, seconds=100)

    def launch(self):
        self.run("shell", "am", "start", "-W", "-n", PACKAGE + "/.MainActivity")


def check_connection(receipt, status):
    if receipt.get("status") != status:
        raise AssertionError("Unexpected production connection outcome")
    if status == "reused" and receipt.get("device_id") != DEVICE:
        raise AssertionError("Restored paired identity changed")


def certificate(directory):
    # Fresh test-only certificate, never the application's signing material.
    key, cert = directory / "tls.key", directory / "tls.pem"
    subprocess.run([
        "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
        "-keyout", str(key), "-out", str(cert), "-subj", "/CN=" + HOST,
        "-addext", "subjectAltName=DNS:" + HOST,
        "-addext", "basicConstraints=critical,CA:TRUE",
    ], check=True, capture_output=True, timeout=30)
    key.chmod(0o600)
    name = subprocess.run(["openssl", "x509", "-in", str(cert), "-subject_hash_old", "-noout"],
                          check=True, capture_output=True, timeout=10).stdout.decode().strip()
    if not re.fullmatch(r"[a-f0-9]{8}", name):
        raise ValueError("Invalid test certificate filename")
    return key, cert, name + ".0"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    require_runner(os.environ)
    for name in PINS:
        if sha(getattr(args, name).read_bytes()) != PINS[name]:
            raise ValueError("Exact verified APK hash mismatch")
    android = Android("emulator-5554")
    if android.run("shell", "getprop", "ro.kernel.qemu").strip() != b"1":
        raise RuntimeError("Physical devices are forbidden")
    if android.run("shell", "getprop", "ro.build.version.sdk").strip() != b"28":
        raise RuntimeError("Controlled trust fixture requires API 28")
    if PACKAGE.encode() in android.run("shell", "pm", "list", "packages", PACKAGE):
        raise RuntimeError("Requires a fresh emulator; never uninstall existing data")
    android.run("root")
    android.run("wait-for-device")
    if android.run("shell", "id", "-u").strip() != b"0":
        raise RuntimeError("Disposable emulator must support root")
    android.run("remount")
    with tempfile.TemporaryDirectory(
            prefix="android-upgrade-", dir=os.environ["RUNNER_TEMP"]) as tmp:
        directory = Path(tmp)
        key, cert, name = certificate(directory)
        android.run("push", str(cert), "/system/etc/security/cacerts/" + name)
        android.run("shell", "chmod", "644", "/system/etc/security/cacerts/" + name)
        hosts = directory / "hosts"
        hosts.write_text("127.0.0.1 localhost " + HOST + "\n::1 localhost\n")
        android.run("push", str(hosts), "/system/etc/hosts")
        fixture = Fixture()
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler(fixture))
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(cert, key)
        server.socket = tls.wrap_socket(server.socket, server_side=True)
        port = server.server_port
        android.run("reverse", "tcp:8443", f"tcp:{port}")
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            android.run("install", str(args.baseline), timeout=90)
            uid, version = android.installed()
            if version != 23:
                raise AssertionError("Incorrect baseline version")
            origin = "https://" + HOST + ":8443"
            check_connection(android.connect(origin, fixture.code), "paired")
            wait_for(lambda: fixture.models > 0)
            android.stop()
            original_prefs = android.prefs()
            android.run("install", "-r", str(args.candidate), timeout=90)
            if android.installed() != (uid, 24) or android.prefs() != original_prefs:
                raise AssertionError("Installed upgrade changed UID or saved connection")
            # The replacement code is deliberately invalid: a fresh pairing cannot pass.
            check_connection(android.connect(origin, "invalid_after_upgrade"), "reused")
            for _ in range(2):
                android.stop()
                count = fixture.models
                android.launch()
                wait_for(lambda count=count: fixture.models > count)
                if android.prefs() != original_prefs:
                    raise AssertionError("Restart rewrote encrypted connection")
            android.stop()
            fixture.available = False
            check_connection(android.connect(origin, "invalid_during_outage"), "connection_failed")
            if android.prefs() != original_prefs:
                raise AssertionError("Network failure discarded saved connection")
            fixture.available = True
            android.stop()
            check_connection(android.connect(origin, "invalid_after_recovery"), "reused")
            if (fixture.pairings != 1 or fixture.rejected or fixture.identities < 2
                    or android.prefs() != original_prefs):
                raise AssertionError("Re-pairing, credential change or authentication failure")
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps({
                "schema": 1, "apk_sha256": PINS, "application_id": PACKAGE,
                "baseline_version_code": 23, "candidate_version_code": 24,
                "in_place_upgrade": True, "uid_preserved": True,
                "encrypted_connection_bytes_preserved": True,
                "android_keystore_decryption_and_authenticated_reuse": True,
                "cold_starts": 2, "outage_preservation_and_recovery": True,
                "pairings": fixture.pairings,
                "scope": ("Exact production APKs on API28 emulator with controlled HTTPS API, "
                          "trust and DNS fixtures; no real backend, Tailscale, inference "
                          "or physical-device claim."),
            }, indent=2) + "\n")
        finally:
            server.shutdown()
            server.server_close()
            android.stop()
            android.run("reverse", "--remove", "tcp:8443", check=False)


if __name__ == "__main__":
    main()
