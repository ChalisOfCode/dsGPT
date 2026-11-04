"""Long edits can legitimately reread unchanged interfaces after other files change."""

import pytest

from dsgpt.config import Model
from dsgpt.project_tools import ProjectAction, action_schema
from dsgpt.storage import Store
from dsgpt.work import WorkRegistry


def commit(work, task, tool, **arguments):
    with work.store.transaction() as db:
        db.execute("UPDATE work_tasks SET status='running' WHERE id=?", (task,))
    session = work.store.one("SELECT * FROM work_sessions WHERE task_id=?", (task,))
    work._commit(task, session, ProjectAction(tool=tool, summary="Fixture action", **arguments))
    return work.get(task)


def test_repeated_inventory_still_blocks_when_nothing_changed(tmp_path):
    work = WorkRegistry(
        Store(tmp_path),
        models={"local": Model("local", "Fixture", "ollama", "http://127.0.0.1:11434", "local")},
    )
    task = work.create("Greeting", "Create a greeting file", "local")["id"]
    assert commit(work, task, "list_files")["status"] == "queued"
    assert commit(work, task, "list_files")["status"] == "queued"
    assert commit(work, task, "list_files")["status"] == "blocked"
    assert work.get(task)["session"]["error_code"] == "no_progress"


def test_inventory_after_new_files_is_real_progress(tmp_path):
    work = WorkRegistry(
        Store(tmp_path),
        models={"local": Model("local", "Fixture", "ollama", "http://127.0.0.1:11434", "local")},
    )
    task = work.create("Greeting", "Create greeting and help files", "local")["id"]
    commit(work, task, "list_files")
    commit(work, task, "write_file", path="greeting.txt", content="Hello")
    commit(work, task, "list_files")
    commit(work, task, "write_file", path="help.txt", content="Open the greeting")
    assert commit(work, task, "list_files")["status"] == "queued"


def test_reread_interface_after_other_source_changes_is_not_a_loop(tmp_path):
    work = WorkRegistry(
        Store(tmp_path),
        models={"local": Model("local", "Fixture", "ollama", "http://127.0.0.1:11434", "local")},
    )
    task = work.create("Greeting", "Create a greeting program", "local")["id"]
    commit(work, task, "write_file", path="contract.txt", content="Output a greeting")
    commit(work, task, "read_file", path="contract.txt")
    commit(work, task, "write_file", path="greeting.txt", content="Hello")
    commit(work, task, "read_file", path="contract.txt")
    commit(work, task, "write_file", path="help.txt", content="Open the greeting")
    assert commit(work, task, "read_file", path="contract.txt")["status"] == "queued"
    assert (
        work.store.one(
            "SELECT content FROM work_files WHERE task_id=? AND path='contract.txt'", (task,)
        )["content"]
        == "Output a greeting"
    )


def test_paged_asset_grammar_does_not_restrict_paths_to_first_page():
    schema = action_schema(isolated_execution=True, asset_paths=None)
    variants = {v["properties"]["tool"]["const"]: v for v in schema["oneOf"]}
    assert "list_assets" in variants and "offset" in variants["list_assets"]["properties"]
    assert "query" in variants["list_assets"]["properties"]
    for tool in ("read_asset", "transcribe_media", "assemble_transcript"):
        assert "enum" not in variants[tool]["properties"]["path"]
    action = ProjectAction(
        tool="assemble_transcript", path="inputs/meeting.wav", summary="Combine complete audio"
    )
    assert action.path == "inputs/meeting.wav"


@pytest.mark.parametrize("changed,expected", [(True, "queued"), (False, "blocked")])
def test_assembly_observes_changed_window_receipts_without_changing_source(
    tmp_path, changed, expected
):
    work = WorkRegistry(
        Store(tmp_path),
        models={"local": Model("local", "Fixture", "ollama", "http://127.0.0.1:11434", "local")},
    )
    task = work.create(
        "Meeting", "Deliver transcript and subtitles", "local", build_target="files"
    )["id"]
    for index in range(3):
        with work.store.transaction() as db:
            db.execute("UPDATE work_tasks SET status='running' WHERE id=?", (task,))
        session = work.store.one("SELECT * FROM work_sessions WHERE task_id=?", (task,))
        work._commit(
            task,
            session,
            ProjectAction(
                tool="assemble_transcript",
                path="inputs/meeting.wav",
                summary="Assemble checked windows",
            ),
            {
                "snapshot_sha256": "a" * 64,
                "transcription_source_sha256": "b" * 64,
                "assets_sha256": str(index if changed else 0) * 64,
                "exit_code": 0,
                "artifacts": [],
            },
        )
    assert work.get(task)["status"] == expected
