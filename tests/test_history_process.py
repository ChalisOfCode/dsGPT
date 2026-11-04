import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from test_history import archive, exported

from dsgpt.history import History
from dsgpt.history_archive import read_archive
from dsgpt.history_import import main
from dsgpt.migrations import MIGRATIONS
from dsgpt.security import Auth
from dsgpt.storage import APPLICATION_ID, SCHEMA, SCHEMA_VERSION, InstanceLock, Store, uid


def test_v9_backup_preserves_attachments_and_indexes_existing_messages(tmp_path):
    with sqlite3.connect(tmp_path / "dsgpt.db") as db:
        db.executescript(SCHEMA + "".join(MIGRATIONS[v] for v in range(2, 10)))
        db.execute(f"PRAGMA application_id={APPLICATION_ID}")
        db.execute("PRAGMA user_version=9")
        db.execute(
            "INSERT INTO conversations VALUES('chat','Old chat',NULL,0,1,2,3,'then','later')"
        )
        db.execute(
            "INSERT INTO messages VALUES('msg','chat','user','CITRINE before import',"
            "'completed',1,'then')"
        )
        db.execute(
            "INSERT INTO message_attachments VALUES('file','msg','note.txt','Keep body',"
            "9,'hash','then',0)"
        )
        db.execute("UPDATE search_settings SET origin='http://127.0.0.1:8080',revision=4")
    store = Store(tmp_path)
    assert store.one("PRAGMA user_version")["user_version"] == SCHEMA_VERSION
    assert store.one("SELECT * FROM message_attachments")["text"] == "Keep body"
    assert store.one("SELECT * FROM search_settings")["revision"] == 4
    assert History(store).search("CITRINE")[0]["message_id"] == "msg"
    assert store.all("PRAGMA foreign_key_check") == []
    backup = next(tmp_path.glob(f"before-v9-to-v{SCHEMA_VERSION}-*.db"))
    with sqlite3.connect(backup) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 9
        assert db.execute("SELECT content FROM messages").fetchone()[0] == "CITRINE before import"
        assert not db.execute(
            "SELECT name FROM sqlite_master WHERE name='history_sources'"
        ).fetchone()


def test_cli_preview_apply_busy_remove_and_retry(tmp_path, capsys):
    path, value = archive(tmp_path)
    directory = tmp_path / "data"
    assert main(["preview", "--file", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["selected_messages"] == 2
    assert not directory.exists()
    store = Store(directory)
    Auth(store).initialize_owner()
    arguments = [
        "apply",
        "--file",
        str(path),
        "--sha256",
        value["archive_sha256"],
        "--request-id",
        uid(),
        "--data-dir",
        str(directory),
    ]
    lock = InstanceLock(directory)
    lock.acquire()
    try:
        assert main(arguments) == 1
        assert "Another dsGPT backend" in capsys.readouterr().err
        assert store.all("SELECT * FROM history_batches") == []
    finally:
        lock.release()
    assert main(arguments) == 0
    first = json.loads(capsys.readouterr().out)
    chat = first["items"][0]["conversation_id"]
    message_id = store.one("SELECT id FROM messages WHERE role='user'")["id"]
    remember = [
        "remember",
        "--data-dir",
        str(directory),
        "--id",
        message_id,
        "--request-id",
        uid(),
        "--title",
        "Explicit orchard memory",
    ]
    assert main(remember) == 0
    assert "SAPPHIRE" not in capsys.readouterr().out
    assert main(["remove", "--data-dir", str(directory), "--id", chat, "--confirm-remove"]) == 0
    capsys.readouterr()
    assert main(arguments) == 0
    assert json.loads(capsys.readouterr().out)["items"][0]["removed"] is True
    assert store.one("SELECT content FROM memories")["content"].endswith("SAPPHIRE.")
    assert main(["list", "--data-dir", str(directory)]) == 0
    assert json.loads(capsys.readouterr().out)[0]["removed"] == 1


def test_real_process_kill_rolls_back_then_retry_commits_once(tmp_path):
    path, value = archive(tmp_path, [exported("one"), exported("two")])
    directory = tmp_path / "data"
    Store(directory)
    marker = tmp_path / "transaction-open"
    request_id = uid()
    # Instrument SQLite's trace callback in this trusted test child only. Stop immediately
    # before the final receipt statement, after messages/FTS are written but not committed.
    code = r"""
import sys,time
from contextlib import contextmanager
from pathlib import Path
from dsgpt.storage import Store
from dsgpt.history_import import main
original=Store.transaction
@contextmanager
def paused(self):
    with original(self) as db:
        def trace(sql):
            if sql.startswith('UPDATE history_batches SET result='):
                Path(sys.argv[1]).write_text('ready')
                time.sleep(45)
        db.set_trace_callback(trace)
        yield db
Store.transaction=paused
raise SystemExit(main(sys.argv[2:]))
"""
    args = [
        "apply",
        "--file",
        str(path),
        "--data-dir",
        str(directory),
        "--sha256",
        value["archive_sha256"],
        "--request-id",
        request_id,
    ]
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    process = subprocess.Popen(
        [sys.executable, "-c", code, str(marker), *args],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 10
        while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert marker.exists(), process.communicate(timeout=1)
        # Readers see only the old state until COMMIT.
        with sqlite3.connect(directory / "dsgpt.db") as db:
            assert db.execute("SELECT count(*) FROM messages").fetchone()[0] == 0
        process.kill()
        process.communicate(timeout=10)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10)
    store = Store(directory)
    assert store.one("SELECT count(*) AS n FROM history_batches")["n"] == 0
    assert History(store).search("SAPPHIRE") == []
    run = subprocess.run(
        [sys.executable, "-m", "dsgpt.history_import", *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert run.returncode == 0, run.stderr
    first = json.loads(run.stdout)
    h = History(Store(directory))
    assert first == h.apply(read_archive(path), request_id, value["archive_sha256"])
    assert store.one("SELECT count(*) AS n FROM messages")["n"] == 4
    h.remove(first["items"][0]["conversation_id"])
    after = subprocess.run(
        [sys.executable, "-m", "dsgpt.history_import", *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert after.returncode == 0, after.stderr
    assert json.loads(after.stdout)["items"][0]["removed"] is True
    assert len(h.search("SAPPHIRE")) == 1  # The separate source ID 'two' remains.
