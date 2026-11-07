"""Edits cannot select another file's revision; execution still checks races."""

import hashlib
import json

from test_work_inline_original import Inference, setup, step

from dsgpt.project_tools import ProjectAction, ProjectTools, action_schema


def edit_pairs(schema):
    return {
        (v["properties"]["path"]["const"], v["properties"]["expected_sha256"]["const"])
        for v in schema["oneOf"] if v["properties"]["tool"]["const"] == "edit_file"
    }


def test_path_and_revision_are_bound_including_shared_content_and_unicode():
    revisions = {"MainActivity.kt": "a" * 64, "gradle.properties": "b" * 64,
                 "雪/é.kt": "a" * 64}
    schema = action_schema(list(revisions.values()), specification=True,
                           file_paths=list(revisions), file_revisions=revisions)
    assert edit_pairs(schema) == set(revisions.items())
    assert ("MainActivity.kt", revisions["gradle.properties"]) not in edit_pairs(schema)
    for variant in schema["oneOf"]:
        if variant["properties"]["tool"]["const"] == "edit_file":
            assert {"old_text", "new_text", "expected_sha256"} <= set(variant["required"])


def test_revision_mapping_does_not_expand_selectable_paths():
    revisions = {"a.py": "a" * 64, "b.py": "b" * 64}
    assert edit_pairs(action_schema(file_paths=["a.py"], file_revisions=revisions)) == {
        ("a.py", revisions["a.py"])}
    assert edit_pairs(action_schema(file_paths=[], file_revisions=revisions)) == set()


async def test_controller_refreshes_pairs_and_runtime_rejects_stale_response(tmp_path):
    store, work, tid = setup(tmp_path)
    work.inference = Inference()
    await step(work, tid)
    row = store.one("SELECT * FROM work_files WHERE task_id=? AND path='notes.txt'", (tid,))
    old_hash, old_text = row["sha256"], row["content"]

    def concurrent_edit():
        with store.transaction() as db:
            result = ProjectTools.apply(db, tid, ProjectAction(
                tool="edit_file", path="notes.txt", old_text=old_text,
                new_text="Concurrent change", expected_sha256=old_hash, summary="Change"))
        assert "error" not in result

    work.inference = Inference({"tool": "edit_file", "path": "notes.txt",
                               "old_text": old_text, "new_text": "Stale proposal",
                               "expected_sha256": old_hash, "summary": "Edit"},
                              mutation=concurrent_edit)
    await step(work, tid)
    assert edit_pairs(work.inference.calls[0][1]) == {("notes.txt", old_hash)}
    result = json.loads(store.one(
        "SELECT result FROM work_steps WHERE task_id=? ORDER BY step DESC LIMIT 1", (tid,)
    )["result"])
    assert result["error"] == "file_changed_read_before_overwrite"
    assert store.one("SELECT content FROM work_files WHERE task_id=?", (tid,))["content"] == (
        "Concurrent change")
    work.inference = Inference({"tool": "read_file", "path": "notes.txt", "summary": "Inspect"})
    await step(work, tid)
    assert edit_pairs(work.inference.calls[0][1]) == {
        ("notes.txt", hashlib.sha256(b"Concurrent change").hexdigest())}
