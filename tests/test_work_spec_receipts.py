"""Completion must attest to the exact outputs that were reviewed, including media."""

import hashlib
import json

import pytest

from dsgpt.builds import WorkBuilds, snapshot_hash
from dsgpt.config import Model
from dsgpt.project_tools import ProjectAction, ProjectTools
from dsgpt.storage import Store, canonical, uid, utcnow
from dsgpt.work import WorkRegistry
from dsgpt.work_specs import WorkSpecs


@pytest.fixture
def project(tmp_path):
    store = Store(tmp_path)
    model = Model("local", "Local", "ollama", "http://127.0.0.1:11434", "local")
    work = WorkRegistry(store, models={model.id: model})
    task = work.create(
        "Transcribe",
        "Deliver the recording as transcript JSON and SRT subtitles.",
        model.id,
        build_target="files",
    )
    other = work.create("Separate task", "Unrelated work")
    with store.transaction() as db:
        WorkSpecs.initialize(db, task["id"], task["requirements"])
        db.execute(
            "UPDATE work_spec_sections SET notes='Both transcript formats are required' "
            "WHERE task_id=?",
            (task["id"],),
        )
    return store, work, task, other


def source_snapshot(db, task_id):
    return snapshot_hash(
        [
            dict(row)
            for row in db.execute("SELECT path,sha256 FROM work_files WHERE task_id=?", (task_id,))
        ]
    )


def receipt(
    db,
    task_id,
    *,
    step=1,
    path="media/transcript.json",
    body=b'{"text":"Hello"}',
    execution_id=None,
):
    artifact_id = uid()
    metadata = {
        "id": artifact_id,
        "path": path,
        "sha256": hashlib.sha256(body).hexdigest(),
        "bytes": len(body),
        "kind": "file",
    }
    if execution_id is None:
        execution_id = uid()
        db.execute(
            "INSERT INTO work_executions(id,task_id,step,action,snapshot_sha256,status,result,"
            "cleanup_pending,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                execution_id,
                task_id,
                step,
                "{}",
                source_snapshot(db, task_id),
                "completed",
                canonical({"exit_code": 0, "artifacts": [metadata]}),
                0,
                utcnow(),
                utcnow(),
            ),
        )
    else:
        result = json.loads(
            db.execute("SELECT result FROM work_executions WHERE id=?", (execution_id,)).fetchone()[
                0
            ]
        )
        result["artifacts"].append(metadata)
        db.execute(
            "UPDATE work_executions SET result=? WHERE id=?", (canonical(result), execution_id)
        )
    db.execute(
        "INSERT INTO work_artifacts VALUES(?,?,?,?,?,?,?)",
        (artifact_id, execution_id, task_id, path, metadata["sha256"], len(body), body),
    )
    return metadata, execution_id


def mark(*paths):
    return ProjectAction(
        tool="mark_requirement",
        summary="Review completed transcript files",
        requirement_id=1,
        content="Reviewed the saved transcript outputs for the requested recording.",
        evidence_paths=list(paths),
    )


def commit(work, task_id, action):
    with work.store.transaction() as db:
        db.execute("UPDATE work_tasks SET status='running' WHERE id=?", (task_id,))
    work._commit(task_id, work.get(task_id)["session"], action)


def test_media_task_finishes_with_json_and_subtitle_receipts_without_source_files(project):
    store, work, task, _ = project
    task_id = task["id"]
    with store.transaction() as db:
        transcript, execution_id = receipt(db, task_id)
        subtitle, _ = receipt(
            db,
            task_id,
            execution_id=execution_id,
            path="media/transcript.srt",
            body=b"1\n00:00:00,000 --> 00:00:01,000\nHello\n",
        )
    commit(work, task_id, mark("receipts/" + transcript["path"], "receipts/" + subtitle["path"]))
    commit(work, task_id, ProjectAction(tool="finish", summary="Transcript and subtitles ready"))
    assert work.get(task_id)["status"] == "completed"
    assert store.all("SELECT * FROM work_files WHERE task_id=?", (task_id,)) == []
    result = json.loads(
        store.one(
            "SELECT result FROM work_steps WHERE task_id=? ORDER BY step DESC LIMIT 1", (task_id,)
        )["result"]
    )
    assert result["build_command_succeeded"] is True
    assert result["native_runtime_verified"] is False
    assert {item["id"] for item in result["artifacts"]} == {transcript["id"], subtitle["id"]}
    assert len(store.all("SELECT * FROM work_artifacts WHERE task_id=?", (task_id,))) == 2


@pytest.mark.parametrize(
    "change",
    [
        "removed",
        "replaced",
        "hash_changed",
        "failed",
        "cleanup_pending",
        "foreign_execution",
        "foreign_artifact",
        "source_changed",
        "stale_execution",
        "failed_replacement",
    ],
)
def test_coverage_cannot_survive_changed_or_unusable_receipt(project, change):
    store, _, task, other = project
    task_id = task["id"]
    with store.transaction() as db:
        artifact, execution_id = receipt(db, task_id)
        action = mark("receipts/" + artifact["path"])
        result = WorkSpecs.coverage(db, task_id, action)
        original_source = source_snapshot(db, task_id)
        assert result["source_snapshot_sha256"] == original_source
        assert result["snapshot_sha256"] != original_source
        assert WorkSpecs.finish_state(db, task_id, original_source)["ready"]
        if change == "removed":
            db.execute("DELETE FROM work_artifacts WHERE id=?", (artifact["id"],))
        elif change in {"replaced", "failed_replacement"}:
            # Even a new receipt with identical bytes requires reviewing that new receipt.
            _, replacement = receipt(db, task_id, step=2)
            if change == "failed_replacement":
                db.execute("UPDATE work_executions SET status='failed' WHERE id=?", (replacement,))
        elif change == "hash_changed":
            body = b'{"text":"Changed"}'
            db.execute(
                "UPDATE work_artifacts SET content=?,sha256=?,bytes=? WHERE id=?",
                (body, hashlib.sha256(body).hexdigest(), len(body), artifact["id"]),
            )
        elif change == "failed":
            db.execute("UPDATE work_executions SET status='failed' WHERE id=?", (execution_id,))
        elif change == "cleanup_pending":
            db.execute("UPDATE work_executions SET cleanup_pending=1 WHERE id=?", (execution_id,))
        elif change == "foreign_execution":
            db.execute(
                "UPDATE work_executions SET task_id=? WHERE id=?", (other["id"], execution_id)
            )
        elif change == "foreign_artifact":
            db.execute(
                "UPDATE work_artifacts SET task_id=? WHERE id=?", (other["id"], artifact["id"])
            )
        elif change == "source_changed":
            ProjectTools.apply(
                db,
                task_id,
                ProjectAction(
                    tool="write_file",
                    path="script.py",
                    content="print('new source')",
                    summary="Edit",
                ),
            )
        elif change == "stale_execution":
            db.execute(
                "UPDATE work_executions SET snapshot_sha256=? WHERE id=?", ("0" * 64, execution_id)
            )
        current_source = source_snapshot(db, task_id)
        state = WorkSpecs.finish_state(db, task_id, current_source)
        assert not state["ready"] and state["next_sections"] == [1]
        reviewed = WorkSpecs.coverage(db, task_id, action)
        if change == "replaced":
            assert "error" not in reviewed
            assert WorkSpecs.finish_state(db, task_id, current_source)["ready"]
        else:
            assert reviewed["error"] == "coverage_requires_current_project_files_or_receipts"


def test_unrelated_receipt_does_not_invalidate_reviewed_outputs(project):
    store, _, task, _ = project
    with store.transaction() as db:
        receipt(db, task["id"])
        WorkSpecs.coverage(db, task["id"], mark("receipts/media/transcript.json"))
        receipt(db, task["id"], step=2, path="media/other.json")
        assert WorkSpecs.finish_state(db, task["id"], source_snapshot(db, task["id"]))["ready"]


def test_receipt_namespace_cannot_be_forged_with_source_file(project):
    store, _, task, _ = project
    with store.transaction() as db:
        ProjectTools.apply(
            db,
            task["id"],
            ProjectAction(
                tool="write_file",
                path="receipts/media/transcript.json",
                content="Invented receipt",
                summary="Fixture",
            ),
        )
        result = WorkSpecs.coverage(db, task["id"], mark("receipts/media/transcript.json"))
        assert result["error"] == "coverage_requires_current_project_files_or_receipts"


def test_mixed_source_and_receipt_evidence_checks_every_path(project):
    store, _, task, _ = project
    with store.transaction() as db:
        ProjectTools.apply(
            db,
            task["id"],
            ProjectAction(
                tool="write_file",
                path="summary.txt",
                content="Summary of the recording",
                summary="Write",
            ),
        )
        receipt(db, task["id"])
        result = WorkSpecs.coverage(
            db, task["id"], mark("summary.txt", "receipts/media/transcript.json")
        )
        assert "error" not in result
        assert WorkSpecs.finish_state(db, task["id"], source_snapshot(db, task["id"]))["ready"]
        assert "error" in WorkSpecs.coverage(
            db, task["id"], mark("missing.txt", "receipts/media/transcript.json")
        )


def test_requirement_read_pages_unicode_losslessly_and_signals_end(project):
    store, _, task, _ = project
    task_id, text = task["id"], "Keep 🏁 and العربية and 日本語 intact."
    with store.transaction() as db:
        db.execute("UPDATE work_tasks SET requirements=? WHERE id=?", (text, task_id))
        WorkSpecs.initialize(db, task_id, text)
        offset, parts = 0, []
        while True:
            page = WorkSpecs.read(db, task_id, offset=offset, limit=9)
            parts.append(page["content"])
            if page["next_offset"] is None:
                assert page["has_more"] is False
                break
            assert page["has_more"] is True and page["next_offset"] > offset
            offset = page["next_offset"]
        assert "".join(parts) == text
        for offset in (len(text), len(text) + 20):
            page = WorkSpecs.read(db, task_id, offset=offset)
            assert page["content"] == "" and page["next_offset"] is None
            assert page["has_more"] is False


def test_requirement_listing_has_explicit_end_for_partial_and_empty_pages(project):
    store, _, task, _ = project
    task_id, text = task["id"], "x" * (1600 * 9)
    with store.transaction() as db:
        db.execute("UPDATE work_tasks SET requirements=? WHERE id=?", (text, task_id))
        WorkSpecs.initialize(db, task_id, text)
        first = WorkSpecs.listing(db, task_id)
        assert len(first["sections"]) == 8 and first["total"] == 9
        assert first["next_offset"] == 8 and first["has_more"] is True
        last = WorkSpecs.listing(db, task_id, offset=8)
        assert len(last["sections"]) == 1 and last["next_offset"] is None
        assert last["has_more"] is False
        for offset in (9, 100):
            empty = WorkSpecs.listing(db, task_id, offset=offset)
            assert empty["sections"] == [] and empty["next_offset"] is None
            assert empty["has_more"] is False


def no_output_execution(db, task_id, step, status="completed"):
    identifier = uid()
    db.execute(
        "INSERT INTO work_executions(id,task_id,step,action,snapshot_sha256,status,result,"
        "cleanup_pending,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            identifier,
            task_id,
            step,
            '{"tool":"run"}',
            source_snapshot(db, task_id),
            status,
            canonical({"exit_code": 0 if status == "completed" else 1, "artifacts": []}),
            0,
            utcnow(),
            utcnow(),
        ),
    )
    return identifier


def test_file_finish_collects_every_transcription_window_after_output_free_read(project):
    store, work, task, _ = project
    task_id = task["id"]
    outputs, executions = [], []
    with store.transaction() as db:
        for window in (1, 2):
            transcript, execution = receipt(
                db, task_id, step=window, path=f"media/window-{window}.json"
            )
            subtitle, _ = receipt(
                db,
                task_id,
                execution_id=execution,
                path=f"media/window-{window}.srt",
                body=b"1\n00:00:00,000 --> 00:00:01,000\nHello\n",
            )
            outputs.extend((transcript, subtitle))
            executions.append(execution)
        inspection = no_output_execution(db, task_id, 3)
        evidence = WorkBuilds.finish_evidence(db, task_id, "files")
        assert {item["id"] for item in evidence["artifacts"]} == {item["id"] for item in outputs}
        assert evidence["execution_ids"] == list(reversed(executions))
        assert inspection not in evidence["execution_ids"]
    commit(work, task_id, mark(*("receipts/" + item["path"] for item in outputs)))
    commit(work, task_id, ProjectAction(tool="finish", summary="Both windows and formats ready"))
    assert work.get(task_id)["status"] == "completed"
    result = json.loads(
        store.one(
            "SELECT result FROM work_steps WHERE task_id=? ORDER BY step DESC LIMIT 1", (task_id,)
        )["result"]
    )
    assert {item["id"] for item in result["artifacts"]} == {item["id"] for item in outputs}


def test_file_finish_uses_latest_path_and_does_not_resurrect_deleted_replacement(project):
    store, _, task, _ = project
    task_id = task["id"]
    with store.transaction() as db:
        old, _ = receipt(db, task_id)
        replacement, _ = receipt(db, task_id, step=2, body=b'{"text":"Corrected"}')
        other, _ = receipt(db, task_id, step=3, path="media/other.json")
        action = mark("receipts/" + replacement["path"])
        assert "error" not in WorkSpecs.coverage(db, task_id, action)
        evidence = WorkBuilds.finish_evidence(db, task_id, "files")
        assert {item["id"] for item in evidence["artifacts"]} == {replacement["id"], other["id"]}
        db.execute("DELETE FROM work_artifacts WHERE id=?", (replacement["id"],))
        evidence = WorkBuilds.finish_evidence(db, task_id, "files")
        assert [item["id"] for item in evidence["artifacts"]] == [other["id"]]
        assert old["id"] not in canonical(evidence)
        assert not WorkSpecs.finish_state(db, task_id, source_snapshot(db, task_id))["ready"]
        assert "error" in WorkSpecs.coverage(db, task_id, action)


@pytest.mark.parametrize(
    "change",
    [
        "failed",
        "cleanup_pending",
        "foreign_artifact",
        "foreign_execution",
        "hash_mismatch",
        "size_mismatch",
        "truncated_content",
        "missing_metadata",
        "malformed_result",
        "error_result",
    ],
)
def test_file_finish_excludes_invalid_stored_deliverable(project, change):
    store, _, task, other = project
    task_id = task["id"]
    with store.transaction() as db:
        artifact, execution = receipt(db, task_id)
        kept, _ = receipt(db, task_id, step=2, path="media/retained.json")
        if change == "failed":
            db.execute("UPDATE work_executions SET status='failed' WHERE id=?", (execution,))
        elif change == "cleanup_pending":
            db.execute("UPDATE work_executions SET cleanup_pending=1 WHERE id=?", (execution,))
        elif change == "foreign_artifact":
            db.execute(
                "UPDATE work_artifacts SET task_id=? WHERE id=?", (other["id"], artifact["id"])
            )
        elif change == "foreign_execution":
            db.execute("UPDATE work_executions SET task_id=? WHERE id=?", (other["id"], execution))
        elif change == "hash_mismatch":
            db.execute("UPDATE work_artifacts SET sha256=? WHERE id=?", ("f" * 64, artifact["id"]))
        elif change == "size_mismatch":
            db.execute("UPDATE work_artifacts SET bytes=bytes+1 WHERE id=?", (artifact["id"],))
        elif change == "truncated_content":
            db.execute("UPDATE work_artifacts SET content=? WHERE id=?", (b"", artifact["id"]))
        elif change == "missing_metadata":
            db.execute("UPDATE work_executions SET result='{}' WHERE id=?", (execution,))
        elif change == "malformed_result":
            db.execute("UPDATE work_executions SET result='invalid' WHERE id=?", (execution,))
        elif change == "error_result":
            db.execute(
                "UPDATE work_executions SET result=? WHERE id=?",
                (canonical({"error": "failed", "artifacts": [artifact]}), execution),
            )
        evidence = WorkBuilds.finish_evidence(db, task_id, "files")
        assert [item["id"] for item in evidence["artifacts"]] == [kept["id"]]


def test_file_finish_requires_current_sources_and_latest_success(project):
    store, _, task, _ = project
    task_id = task["id"]
    with store.transaction() as db:
        receipt(db, task_id)
        failure = no_output_execution(db, task_id, 2, "failed")
        assert WorkBuilds.finish_evidence(db, task_id, "files") is None
        db.execute(
            "UPDATE work_executions SET status='completed',result='{}' WHERE id=?", (failure,)
        )
        assert WorkBuilds.finish_evidence(db, task_id, "files") is not None
        ProjectTools.apply(
            db,
            task_id,
            ProjectAction(
                tool="write_file", path="script.py", content="print('new source')", summary="Edit"
            ),
        )
        no_output_execution(db, task_id, 3)
        assert WorkBuilds.finish_evidence(db, task_id, "files") is None
