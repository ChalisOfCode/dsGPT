"""Observed binary-read failures guide a real next choice, without choosing user intent."""

import hashlib
import json
from dataclasses import replace

import pytest
from test_work_asset_tools import action, setup
from test_work_completion_phase import commit, reviewed

from dsgpt.inference import ollama_input_estimate


def prompt(store, work, tid, model=None):
    return work._guided_prompt(
        store.one("SELECT * FROM work_tasks WHERE id=?", (tid,)),
        store.one("SELECT * FROM work_sessions WHERE task_id=?", (tid,)),
        model or work.models["local"],
        [],
    )


@pytest.mark.parametrize("name", ["speech.wav", "archive.zip", "document.txt"])
def test_binary_read_recovery_uses_observed_error_not_filename_or_intent(tmp_path, name):
    store, work, tid, _ = setup(tmp_path)
    original = "Inspect this file as requested; do not assume I want transcription."
    body = b"\xff\xfe\x00\x81"
    with store.transaction() as db:
        db.execute("UPDATE work_tasks SET requirements=? WHERE id=?", (original, tid))
        work.specs.initialize(db, tid, original)
        db.execute("UPDATE work_spec_sections SET notes='Reviewed' WHERE task_id=?", (tid,))
        db.execute("DELETE FROM work_inputs WHERE task_id=?", (tid,))
        db.execute(
            "INSERT INTO work_inputs VALUES(?,?,?,?,?)",
            (tid, name, body, hashlib.sha256(body).hexdigest(), "{}"),
        )
    commit(work, tid, action(tool="read_asset", path="inputs/" + name))
    messages = prompt(store, work, tid)
    context = json.loads(messages[1]["content"])
    hint = context["next_step"]
    assert "The last read_asset failed" in hint
    assert "Do not repeat the same path and offset unchanged" in hint
    assert "For audio/video transcription" in hint and "For other binary work" in hint
    assert "For UTF-8 text" in hint and "next_offset (or 0)" in hint
    assert "matches the user's requirement" in hint
    assert "mark_requirement" not in hint
    assert "Review the current requirement against CURRENT saved files" not in hint
    assert not context["requirements"]["coverage"]["ready"]
    assert not context["build_state"]["completion_ready"]
    assert "transcribe_media" in messages[0]["content"]  # Existing instructions were present.
    assert (
        ollama_input_estimate(messages) + work.models["local"].output_tokens
        <= work.models["local"].context
    )
    steps = store.all("SELECT action,result FROM work_steps WHERE task_id=?", (tid,))
    assert len(steps) == 1 and json.loads(steps[0]["action"])["tool"] == "read_asset"
    assert json.loads(steps[0]["result"])["error"] == (
        "asset_is_not_utf8_text_or_offset_splits_character"
    )
    assert store.all("SELECT * FROM work_executions WHERE task_id=?", (tid,)) == []

    # A page too large for its reserved prompt is omitted with no stale recovery hint.
    tight = replace(work.models["local"], context=512, output_tokens=128)
    omitted = prompt(store, work, tid, tight)
    assert not any(m["content"].startswith("Recorded tool result: ") for m in omitted)
    fallback = json.loads(omitted[1]["content"])
    assert fallback["previous_result"]["error"] == (
        "asset_is_not_utf8_text_or_offset_splits_character"
    )
    assert "The last read_asset failed" not in fallback["next_step"]


def test_unrelated_read_error_keeps_existing_guidance(tmp_path):
    store, work, tid, _ = setup(tmp_path)
    with store.transaction() as db:
        work.specs.initialize(db, tid, "Review the requested file")
        db.execute("UPDATE work_spec_sections SET notes='Reviewed' WHERE task_id=?", (tid,))
    commit(work, tid, action(tool="read_asset", path="inputs/missing.wav"))
    context = json.loads(prompt(store, work, tid)[1]["content"])
    assert "The last read_asset failed" not in context["next_step"]
    assert "Review the current requirement" in context["next_step"]


async def test_binary_read_error_does_not_override_verified_completion(tmp_path):
    store, work, tid, _ = await reviewed(tmp_path)
    # A failed, unnecessary binary read does not invalidate already-current output checks.
    commit(
        work,
        tid,
        action(tool="read_asset", path="inputs/speech.wav"),
        {"error": "asset_is_not_utf8_text_or_offset_splits_character"},
    )
    context = json.loads(prompt(store, work, tid)[1]["content"])
    assert context["build_state"]["completion_ready"]
    assert "Call finish now" in context["next_step"]
    assert "The last read_asset failed" not in context["next_step"]


def test_source_read_preserves_targeted_edit_guidance_after_rejected_overwrite(tmp_path):
    from dsgpt.project_tools import ProjectAction

    store, work, tid, _ = setup(tmp_path)
    with store.transaction() as db:
        work.specs.initialize(
            db, tid, "Implement the requested behavior without losing existing code"
        )
        db.execute("UPDATE work_spec_sections SET notes='Reviewed' WHERE task_id=?", (tid,))
    commit(
        work,
        tid,
        ProjectAction(
            tool="write_file", path="main.py", content="keep = 1\nchange = 0\n", summary="Initial"
        ),
    )
    commit(
        work,
        tid,
        ProjectAction(
            tool="write_file", path="main.py", content="change = 1\n", summary="Incorrect overwrite"
        ),
    )
    commit(work, tid, ProjectAction(tool="read_file", path="main.py", summary="Read for repair"))
    messages = prompt(store, work, tid)
    hint = json.loads(messages[1]["content"])["next_step"]
    assert "Do not call write_file on this path" in hint
    assert "expected_sha256" in hint and "old_text" in hint and "new_text" in hint
    observed = next(
        json.loads(m["content"].removeprefix("Recorded tool result: "))
        for m in messages
        if m["content"].startswith("Recorded tool result: ")
    )
    assert observed["content"] == "keep = 1\nchange = 0\n"
    commit(
        work,
        tid,
        ProjectAction(
            tool="edit_file",
            path="main.py",
            old_text="change = 0",
            new_text="change = 1",
            expected_sha256=observed["sha256"],
            summary="Targeted repair",
        ),
    )
    assert (
        store.one("SELECT content FROM work_files WHERE task_id=? AND path=?", (tid, "main.py"))[
            "content"
        ]
        == "keep = 1\nchange = 1\n"
    )


def test_consecutive_source_reads_keep_current_companion_not_stale_bytes(tmp_path):
    from dsgpt.project_tools import ProjectAction

    store, work, tid, _ = setup(tmp_path)
    with store.transaction() as db:
        work.specs.initialize(db, tid, "Wire the caller to the new module")
        db.execute("UPDATE work_spec_sections SET notes='Reviewed' WHERE task_id=?", (tid,))
    for name in ("module.py", "caller.py"):
        commit(
            work, tid, ProjectAction(tool="write_file", path=name, content=name, summary="Create")
        )
    for name in ("caller.py", "module.py"):
        commit(work, tid, ProjectAction(tool="read_file", path=name, summary="Inspect"))

    def companions():
        return [
            m["content"]
            for m in prompt(store, work, tid)
            if m["content"].startswith("Previous source page")
        ]

    assert len(companions()) == 1 and "caller.py" in companions()[0]
    with store.transaction() as db:
        db.execute(
            "UPDATE work_files SET content=?,sha256=? WHERE task_id=? AND path=?",
            ("changed", hashlib.sha256(b"changed").hexdigest(), tid, "caller.py"),
        )
    assert not companions()


def test_source_read_grammar_retains_edits_and_partial_or_changed_rereads():
    from dsgpt.project_tools import action_schema
    from dsgpt.work import visible_source_read

    body = "π = 3\n"
    digest = hashlib.sha256(body.encode()).hexdigest()
    page = dict(path="a.py", sha256=digest, offset=0, content=body, has_more=False)

    def grammar(result, revisions):
        msgs = [
            {"role": "assistant", "content": json.dumps(dict(tool="read_file", path="a.py"))},
            {"role": "user", "content": "Recorded tool result: " + json.dumps(result)},
        ]
        schema = action_schema(
            file_paths=list(revisions), already_visible_read=visible_source_read(msgs, revisions)
        )
        return {v["properties"]["tool"]["const"]: v["properties"] for v in schema["oneOf"]}

    revisions = {"a.py": digest, "b.py": digest}
    live = grammar(page, revisions)
    assert live["read_file"]["path"]["enum"] == ["b.py"]
    assert live["edit_file"]["path"]["enum"] == ["a.py", "b.py"]
    assert "read_file" not in grammar(page, {"a.py": digest})
    for modified, rev in [
        ({**page, "content": body[:1]}, revisions),
        ({**page, "has_more": True}, revisions),
        (page, {"a.py": "changed"}),
    ]:
        assert "a.py" in grammar(modified, rev)["read_file"]["path"]["enum"]
