"""Driver integrity guards only; these are not installer upgrade acceptance."""

import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "application_upgrade",
    Path(__file__).resolve().parents[1] / "scripts/check_application_upgrade.py",
)
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


def test_original_rows_exactly_preserved_while_new_columns_are_allowed(tmp_path):
    database = tmp_path / "old.db"
    with sqlite3.connect(database) as db:
        for table in ("conversations", "messages", "work_tasks", "devices"):
            db.execute(f"CREATE TABLE {table}(id TEXT PRIMARY KEY,content TEXT)")
            db.execute(f"INSERT INTO {table} VALUES('one','Original café 原文')")
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE work_files(task_id TEXT,path TEXT,content TEXT,sha256 TEXT)")
        db.execute("INSERT INTO work_files VALUES(?,?,?,?)",
                   ("one", "original.txt", "café 原文", "retained-hash"))
    original = json.loads(json.dumps(driver.snapshot(database)))
    with sqlite3.connect(database) as db:
        db.execute("ALTER TABLE work_tasks ADD COLUMN new_metadata TEXT")
    driver.check_snapshot(database, original)
    for invalid in ("2invalid", "content) FROM work_files;--", "content,name"):
        malformed = {"work_files": {"columns": [invalid], "rows": []}}
        with pytest.raises(ValueError, match="snapshot column"):
            driver.check_snapshot(database, malformed)
    with sqlite3.connect(database) as db:
        db.execute("UPDATE messages SET content='silently changed'")
    with pytest.raises(AssertionError, match="records changed"):
        driver.check_snapshot(database, original)


def test_installed_provenance_and_bytes_must_match(tmp_path):
    payload = tmp_path / "backend.py"
    payload.write_bytes(b"original")
    receipt = {"source_commit": "a" * 40, "files": {"backend.py": {
        "bytes": 8, "sha256": hashlib.sha256(b"original").hexdigest()}}}
    (tmp_path / "application-manifest.json").write_text(json.dumps(receipt))
    assert driver.manifest(tmp_path, "a" * 40) == "a" * 40
    with pytest.raises(ValueError, match="source differs"):
        driver.manifest(tmp_path, "b" * 40)
    payload.write_bytes(b"modified")
    with pytest.raises(ValueError, match="integrity failed"):
        driver.manifest(tmp_path, "a" * 40)


def test_upgrade_driver_refuses_non_actions_environment(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    with pytest.raises(RuntimeError, match="disposable Windows"):
        driver.require_runner()


def test_reconnect_must_preserve_scopes_and_role():
    original = {"id": "synthetic-device", "role": "client", "scopes": ["chat", "work"]}
    driver.check_identity({**original, "scopes": ["work", "chat"]}, original)
    for change in ({"id": "another"}, {"role": "owner"},
                   {"scopes": ["chat", "work", "admin"]}, {"scopes": ["chat"]}):
        with pytest.raises(AssertionError, match="authority changed"):
            driver.check_identity({**original, **change}, original)


def test_existing_model_directory_bytes_cannot_be_replaced_or_silently_reseeded(tmp_path):
    receipt = driver.preserved_model_file(tmp_path)
    driver.preserved_model_file(tmp_path, receipt)
    with pytest.raises(FileExistsError):
        driver.preserved_model_file(tmp_path)
    path = tmp_path / "managed-models/upgrade-preservation-fixture.bin"
    original = path.read_bytes()
    path.write_bytes(b"X" + original[1:])
    with pytest.raises(AssertionError, match="fixture bytes changed"):
        driver.preserved_model_file(tmp_path, receipt)


def test_failure_location_excludes_private_values_and_external_paths():
    secret = "synthetic-private-exception-value"
    try:
        driver.check_identity({"id": secret}, {"id": "original"})
    except AssertionError as error:
        record = driver.failure_record("baseline", error)
    assert record == {"passed": False, "phase": "baseline", "error_type": "AssertionError",
                      "driver_function": "check_identity", "driver_line":
                      driver.check_identity.__code__.co_firstlineno + 5}
    assert secret not in json.dumps(record)
    assert str(Path(__file__).parent) not in json.dumps(record)
