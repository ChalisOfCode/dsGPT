import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .migrations import MIGRATIONS, REQUIRED_TABLES

APPLICATION_ID = 0x44534750
SCHEMA_VERSION = 30


def utcnow():
    return datetime.now(UTC).isoformat()


def uid():
    return str(uuid4())


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


SCHEMA = """
CREATE TABLE devices (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL,
 token_hash TEXT UNIQUE NOT NULL, scopes TEXT NOT NULL,
 created_at TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE pairings (
 code_hash TEXT PRIMARY KEY, expires REAL NOT NULL, scopes TEXT NOT NULL
);
CREATE TABLE conversations (
 id TEXT PRIMARY KEY, title TEXT NOT NULL, model_id TEXT,
 hidden INTEGER NOT NULL DEFAULT 0, pinned INTEGER NOT NULL DEFAULT 0,
 pin_order REAL NOT NULL DEFAULT 0, revision INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE messages (
 id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id),
 role TEXT NOT NULL, content TEXT NOT NULL, status TEXT NOT NULL,
 ordinal INTEGER NOT NULL, created_at TEXT NOT NULL,
 UNIQUE(conversation_id, ordinal)
);
CREATE TABLE runs (
 id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id),
 model_id TEXT NOT NULL, request_hash TEXT NOT NULL, message_id TEXT NOT NULL,
 status TEXT NOT NULL, error_code TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX one_active_run ON runs(conversation_id)
 WHERE status IN ('queued','running');
CREATE TABLE events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES runs(id),
 kind TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX events_run_id ON events(run_id,id);
CREATE TABLE work_tasks (
 id TEXT PRIMARY KEY, title TEXT NOT NULL, requirements TEXT NOT NULL,
 status TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE checkpoints (
 id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES work_tasks(id),
 state TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE diagnostic_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL,
 correlation_id TEXT, created_at TEXT NOT NULL
);
CREATE TABLE snapshots (
 id TEXT PRIMARY KEY, device_id TEXT NOT NULL, captured_at TEXT NOT NULL,
 received_at TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE TABLE collections (
 id TEXT PRIMARY KEY, device_id TEXT NOT NULL REFERENCES devices(id),
 status TEXT NOT NULL, created_at TEXT NOT NULL, snapshot_id TEXT
);
CREATE TABLE exports (
 id TEXT PRIMARY KEY, device_id TEXT NOT NULL, expires REAL NOT NULL,
 manifest_hash TEXT NOT NULL, files TEXT NOT NULL
);
"""


class Store:
    def __init__(self, directory: Path):
        self.diagnostic_event_retention = 2000
        self.diagnostic_snapshot_retention = 50
        self.diagnostic_snapshot_bytes = 131072
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.directory / "dsgpt.db"
        if self.path.is_symlink():
            raise ValueError("Refusing a symlink database")
        migration_lock = InstanceLock(self.directory, "migration.lock")
        migration_lock.acquire()
        try:
            self._initialize()
        finally:
            migration_lock.release()
        if os.name != "nt":
            os.chmod(self.path, 0o600)

    def _initialize(self):
        with self.connect() as db:
            app_id = db.execute("PRAGMA application_id").fetchone()[0]
            version = db.execute("PRAGMA user_version").fetchone()[0]
            tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if app_id not in (0, APPLICATION_ID) or (app_id == 0 and tables):
                raise ValueError("Not a dsGPT database; refusing to modify existing data")
            if version > SCHEMA_VERSION:
                raise ValueError("Database is newer than this backend; downgrade refused")
            names = {row[0] for row in tables}
            required = set().union(*(REQUIRED_TABLES[v] for v in range(1, version + 1)))
            if not required <= names:
                raise ValueError("Incomplete database schema requires manual recovery")
            if version == SCHEMA_VERSION:
                return
            # Never upgrade a database owned by a running older backend.
            backend_lock = InstanceLock(self.directory)
            backend_lock.acquire()
            try:
                self._upgrade(db, version, tables)
                db.execute("PRAGMA journal_mode=WAL")
            finally:
                backend_lock.release()

    def _upgrade(self, db, version, tables):
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("Database integrity check failed; restore a verified backup")
        if db.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("Database foreign keys are invalid; refusing migration")
        if version == 0:
            if tables:
                raise ValueError("Incomplete database initialization requires manual recovery")
        else:
            target = self.directory / f"before-v{version}-to-v{SCHEMA_VERSION}-{uid()}.db"
            self.backup(target)
        script = SCHEMA if version == 0 else ""
        script += "\n".join(MIGRATIONS[v] for v in range(max(2, version + 1), SCHEMA_VERSION + 1))
        try:
            db.executescript(
                "BEGIN IMMEDIATE;\n"
                + script
                + f"PRAGMA application_id={APPLICATION_ID};"
                + f"PRAGMA user_version={SCHEMA_VERSION};"
            )
            if db.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("Migration violated database constraints")
            db.commit()
        except BaseException:
            db.rollback()
            raise

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def all(self, query, args=()):
        with self.connect() as db:
            return [dict(row) for row in db.execute(query, args)]

    def one(self, query, args=()):
        rows = self.all(query, args)
        return rows[0] if rows else None

    def backup(self, target: Path):
        # SQLite backup API includes committed WAL pages; copying the .db alone does not.
        # Exclusive creation also refuses symlinks and races; snapshots contain private data.
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        with self.connect() as db, sqlite3.connect(target) as out:
            db.backup(out)
            if out.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("Backup validation failed")

    def log(self, code, correlation_id=None, retention=None):
        from .diagnostic_details import ERROR_HELP
        from .diagnostic_journal import capture

        retention = self.diagnostic_event_retention if retention is None else retention
        if not 1 <= retention <= 10000:
            raise ValueError("Diagnostic event retention must be between 1 and 10000")
        allowed = {
            "backend_started",
            "model_loading",
            "model_loaded",
            "model_unloaded",
            "backend_stopped",
            "inference_failed",
            "run_interrupted",
            "run_completed",
            "device_paired",
            "device_revoked",
            "snapshot_received",
            "context_exceeded",
            "runtime_unavailable",
            "local_model_required",
            "local_vision_model_required",
            "runtime_protocol_error",
            "runtime_context_mismatch",
            "output_limit",
            "model_digest_changed",
            "managed_runtime_integrity_failed",
            "managed_runtime_unavailable",
            "managed_runtime_start_failed",
            "managed_runtime_start_timeout",
            "managed_runtime_port_in_use",
            "managed_runtime_stop_failed",
            "managed_runtime_socket_path_too_long",
            "research_failed",
        }
        if code not in allowed | ERROR_HELP.keys():
            raise ValueError("Diagnostic events accept registered codes only")
        # Never accept free-form messages, exception strings, prompts, or headers.
        if correlation_id is not None:
            from uuid import UUID

            correlation_id = str(UUID(correlation_id))
        with self.transaction() as db:
            db.execute(
                "INSERT INTO diagnostic_events(code,correlation_id,created_at) VALUES(?,?,?)",
                (code, correlation_id, utcnow()),
            )
            db.execute(
                "DELETE FROM diagnostic_events WHERE id NOT IN "
                "(SELECT id FROM diagnostic_events ORDER BY id DESC LIMIT ?)",
                (retention,),
            )
            if code in ERROR_HELP:
                capture(self, db, code, correlation_id)


class InstanceLock:
    """One backend process per database; prevents duplicate inference after a second launch."""

    def __init__(self, directory, filename="backend.lock"):
        self.path = Path(directory) / filename
        self.file = None

    def acquire(self):
        if self.path.is_symlink():
            raise ValueError("Refusing a symlink lock file")
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        self.file = os.fdopen(fd, "r+b")
        if os.fstat(fd).st_size == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            self.file = None
            raise RuntimeError("Another dsGPT backend owns this data directory") from exc

    def release(self):
        if self.file:
            self.file.close()
            self.file = None
