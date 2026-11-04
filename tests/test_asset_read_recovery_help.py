"""Binary read errors explain the actual typed media action without executing it."""

import importlib.util
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "src/dsgpt/work_asset_tools.py"
SPEC = importlib.util.spec_from_file_location("dsgpt.read_recovery_under_test", MODULE_PATH)
asset_tools = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(asset_tools)


@pytest.mark.parametrize("raw", [b"RIFF\x00\x00\x00\x00WAVE", b"\xffbinary", "🙂".encode()[1:]])
def test_binary_and_split_character_error_is_actionable_and_keeps_original(raw):
    with sqlite3.connect(":memory:") as db:
        db.executescript(
            "CREATE TABLE work_build_profiles(task_id);"
            "CREATE TABLE work_inputs(task_id,name,original);"
        )
        db.execute("INSERT INTO work_build_profiles VALUES('task')")
        db.execute("INSERT INTO work_inputs VALUES(?,?,?)", ("task", "source.dat", raw))
        item = {"name": "source.dat", "bytes": len(raw), "sha256": "a" * 64}
        with patch.object(asset_tools.work_assets, "lookup", return_value=item) as lookup:
            result = asset_tools.read_asset(db, "task", "inputs/source.dat")
        lookup.assert_called_once_with(db, "task", "inputs/source.dat")
        assert result["error"] == "asset_is_not_utf8_text_or_offset_splits_character"
        assert "transcribe_media with the same path" in result["help"]
        assert "transcript_path/subtitles_path" in result["help"]
        assert "next_offset" in result["help"]
        assert db.execute("SELECT original FROM work_inputs").fetchone()[0] == raw
        assert set(result) == {"error", "help"}
