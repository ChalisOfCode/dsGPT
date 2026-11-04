import hashlib
import os
import sqlite3
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from dsgpt.migrations import VERSION_2
from dsgpt.storage import APPLICATION_ID, SCHEMA, SCHEMA_VERSION, Store


def test_actual_http_transfer_resumes_after_worker_process_is_killed(tmp_path):
    data = b"GGUF" + bytes(range(256)) * 8192
    gate, ranges = threading.Event(), []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            header = self.headers.get("Range")
            ranges.append(header)
            start = int(header[6:-1]) if header else 0
            self.send_response(206 if header else 200)
            self.send_header("Content-Length", str(len(data) - start))
            if header:
                self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
            self.end_headers()
            try:
                self.wfile.write(data[start : start + 262144])
                self.wfile.flush()
                if len(ranges) == 1:
                    gate.wait(15)
                self.wfile.write(data[start + 262144 :])
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    root = Path(__file__).resolve().parents[1]
    directory = tmp_path / "data"
    env = {**os.environ, "PYTHONPATH": str(root / "src")}
    command = [
        sys.executable,
        str(root / "scripts/download_recovery_fixture.py"),
        "--data",
        str(directory),
        "--origin",
        f"http://127.0.0.1:{server.server_port}",
    ]
    child = None
    try:
        with (tmp_path / "worker.log").open("w") as log:
            child = subprocess.Popen(command, env=env, stdout=log, stderr=log)
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                partial = list((directory / "managed-models").glob("*.part"))
                if partial and partial[0].stat().st_size >= 262144:
                    break
                assert child.poll() is None, (tmp_path / "worker.log").read_text()
                time.sleep(0.02)
            else:
                raise AssertionError("No partial transfer observed")
            child.kill()
            child.wait(timeout=5)
            observed_size = partial[0].stat().st_size
            gate.set()
            second = subprocess.run(command, env=env, stdout=log, stderr=log, timeout=20)
            assert second.returncode == 0, (tmp_path / "worker.log").read_text()
        store = Store(directory)
        row = store.one("SELECT * FROM downloads")
        assert row["status"] == "downloaded" and row["downloaded"] == len(data)
        assert ranges == [None, f"bytes={observed_size}-"]
        final = next((directory / "managed-models").glob("*.gguf"))
        assert hashlib.sha256(final.read_bytes()).digest() == hashlib.sha256(data).digest()
        assert len(store.all("SELECT id FROM downloads")) == 1
    finally:
        gate.set()
        if child and child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_schema_v2_upgrade_preserves_memory_and_has_restorable_backup(tmp_path):
    with sqlite3.connect(tmp_path / "dsgpt.db") as db:
        db.executescript(SCHEMA + VERSION_2)
        db.execute(f"PRAGMA application_id={APPLICATION_ID}")
        db.execute("PRAGMA user_version=2")
        db.execute(
            "INSERT INTO memories VALUES('keep',NULL,'Memory','Important','user',1,'now','now')"
        )
    store = Store(tmp_path)
    assert store.one("SELECT content FROM memories")["content"] == "Important"
    assert store.one("PRAGMA user_version")["user_version"] == SCHEMA_VERSION
    assert store.all("SELECT * FROM downloads") == []
    backups = list(tmp_path.glob(f"before-v2-to-v{SCHEMA_VERSION}-*.db"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
        assert db.execute("SELECT content FROM memories").fetchone()[0] == "Important"
