"""Loopback-only HTTPS site for account acceptance; never used by production code.

Independent effect counts deliberately do not deduplicate writes. A driver that
retries after a lost response must fail acceptance, not be rescued by this site.
"""

import contextlib
import secrets
import socket
import ssl
import subprocess
import tempfile
import threading
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs


class Site(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), Handler)
        self.password = secrets.token_hex(16)
        self.mfa = secrets.token_hex(8)
        self.csrf = secrets.token_hex(16)
        self.challenge = secrets.token_hex(16)
        self.session = secrets.token_hex(16)
        self.authenticated = False
        self.effects = 0
        self.storage_ready = self.storage_restored = 0
        self.lock = threading.Lock()
        self.origin = f"https://localhost:{self.server_port}"

    def handle_error(self, request, client_address):
        # Traffic, credentials and addresses never become diagnostics.
        pass

    def expire(self):
        with self.lock:
            self.authenticated = False


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(3)

    def cookie(self, name):
        value = SimpleCookie()
        value.load(self.headers.get("Cookie", ""))
        return value[name].value if name in value else ""

    def signed_in(self):
        return self.server.authenticated and self.cookie("session") == self.server.session

    def reply(self, status, body="", *, html=False, cookie=None, location=None):
        data = body.encode()
        self.send_response(status)
        self.send_header(
            "Content-Type", "text/html; charset=utf-8" if html else "text/plain; charset=utf-8"
        )
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'unsafe-inline'; "
            "form-action 'self'; frame-ancestors 'none'",
        )
        if cookie:
            self.send_header(
                "Set-Cookie", cookie + "; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=3600"
            )
        if location:
            self.send_header("Location", location)
        self.end_headers()
        self.wfile.write(data)

    def form(self, path, field):
        return (
            f'<form method="post" action="{path}"><input type="hidden" name="csrf" '
            f'value="{self.server.csrf}"><label>{field}<input name="{field}" '
            f'type="password" autocomplete="off" '
            f'style="position:absolute;left:20px;top:20px;width:300px;height:40px">'
            f'</label><button style="position:absolute;left:20px;top:80px;'
            f'width:100px;height:40px">Submit</button></form>'
        )

    def do_GET(self):
        with self.server.lock:
            if self.path == "/login":
                return self.reply(200, self.form("/login", "password"), html=True)
            if self.path == "/mfa" and self.cookie("challenge") == self.server.challenge:
                return self.reply(200, self.form("/mfa", "code"), html=True)
            if self.path == "/entry":
                # One configured page supports owner sign-in and later task reads.
                if not self.signed_in():
                    return self.reply(200, self.form("/login", "password"), html=True)
                return self.reply(200, f"Controlled account. Updates: {self.server.effects}")
            if not self.signed_in():
                return self.reply(401, "Sign in required")
            if self.path == "/private.txt":
                return self.reply(200, f"Controlled account. Updates: {self.server.effects}")
            if self.path == "/redirect":
                return self.reply(302, location="https://example.invalid/private")
            if self.path == "/interrupt-form":
                return self.reply(200, self.form("/interrupt", "value"), html=True)
            if self.path in {"/storage-ready", "/storage-restored"}:
                if self.path == "/storage-ready":
                    self.server.storage_ready += 1
                else:
                    self.server.storage_restored += 1
                return self.reply(200, "Observed")
            if self.path == "/restore":
                # This page must never recreate markers: otherwise a missing
                # profile would masquerade as successful restoration.
                script = """<title>Profile missing</title><script>
const r = indexedDB.open('account-fixture', 1);
r.onsuccess = () => {
 const db = r.result;
 if (!db.objectStoreNames.contains('markers')) { db.close(); return; }
 const tx = db.transaction('markers', 'readonly');
 const read = tx.objectStore('markers').get('marker');
 read.onsuccess = () => {
  if (read.result === 'persisted' && localStorage.getItem('account-fixture') === 'persisted'
      && !document.cookie.includes('session=')) {
   document.title = 'Profile restored';
   fetch('/storage-restored');
  }
 };
 tx.oncomplete = () => db.close();
};
</script>"""
                return self.reply(200, script, html=True)
            if self.path == "/app":
                # Independent storage markers contain no credentials. The later
                # browser driver must observe these after reopening the profile.
                script = """<script>
localStorage.setItem('account-fixture', 'persisted');
const r = indexedDB.open('account-fixture', 1);
r.onupgradeneeded = () => r.result.createObjectStore('markers');
r.onsuccess = () => {
 const tx = r.result.transaction('markers', 'readwrite');
 tx.objectStore('markers').put('persisted', 'marker');
 tx.oncomplete = () => {
  r.result.close(); document.title = 'Storage ready'; fetch('/storage-ready');
 };
};
</script>"""
                return self.reply(200, self.form("/update", "value") + script, html=True)
            return self.reply(404)

    def do_POST(self):
        if (
            self.headers.get("Origin") != self.server.origin
            or self.headers.get("Content-Type") != "application/x-www-form-urlencoded"
            or self.headers.get("Transfer-Encoding")
        ):
            return self.reply(403)
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 4096:
                return self.reply(413)
            data = parse_qs(self.rfile.read(size).decode(), strict_parsing=True, max_num_fields=4)
        except (ValueError, UnicodeError):
            return self.reply(400)
        with self.server.lock:
            if data.get("csrf") != [self.server.csrf]:
                return self.reply(403)
            if self.path == "/login" and data.get("password") == [self.server.password]:
                return self.reply(303, cookie="challenge=" + self.server.challenge, location="/mfa")
            if (
                self.path == "/mfa"
                and self.cookie("challenge") == self.server.challenge
                and data.get("code") == [self.server.mfa]
            ):
                self.server.authenticated = True
                return self.reply(303, cookie="session=" + self.server.session, location="/app")
            if (
                self.path in {"/update", "/interrupt"}
                and self.signed_in()
                and data.get("value") == ["change"]
            ):
                self.server.effects += 1
                if self.path == "/interrupt":
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.close_connection = True
                    return
                return self.reply(200, "Applied")
            return self.reply(403)


@contextlib.contextmanager
def https_site():
    """Create ephemeral test TLS material, delete it even after failed assertions."""
    with tempfile.TemporaryDirectory(prefix="dsgpt-https-fixture-") as directory:
        root = Path(directory)
        cert, key = root / "cert.pem", root / "key.pem"
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "1",
                "-keyout",
                str(key),
                "-out",
                str(cert),
                "-subj",
                "/CN=localhost",
                "-addext",
                "subjectAltName=DNS:localhost,IP:127.0.0.1",
            ],
            check=True,
            timeout=10,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        key.chmod(0o600)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        server = Site()
        server.socket = context.wrap_socket(server.socket, server_side=True)
        worker = threading.Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        )
        worker.start()
        try:
            yield server, ssl.create_default_context(cafile=str(cert))
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=3)
