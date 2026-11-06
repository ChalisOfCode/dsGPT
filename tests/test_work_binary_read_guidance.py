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


def test_noop_edit_returns_source_without_counting_as_implementation(tmp_path):
    from dsgpt.project_tools import ProjectAction
    from dsgpt.work import visible_source_read

    store, work, tid, _ = setup(tmp_path)
    with store.transaction() as db:
        work.specs.initialize(db, tid, "Implement a referenced module")
        db.execute("UPDATE work_spec_sections SET notes='Reviewed' WHERE task_id=?", (tid,))
    body = "from module import main\nmain()\n"
    digest = hashlib.sha256(body.encode()).hexdigest()
    for a in [
        ProjectAction(tool="write_file", path="caller.py", content=body, summary="Create caller"),
        ProjectAction(
            tool="edit_file",
            path="caller.py",
            old_text="main()",
            new_text="main()",
            expected_sha256=digest,
            summary="No change",
        ),
    ]:
        commit(work, tid, a)
    messages = prompt(store, work, tid)
    result = json.loads(messages[-1]["content"].removeprefix("Recorded tool result: "))
    assert result["error"] == "edit_has_no_change" and result["content"] == body
    assert result["sha256"] == digest and result["has_more"] is False
    assert visible_source_read(messages, {"caller.py": digest}) == "caller.py"
    assert visible_source_read(messages, {"caller.py": "changed"}) is None
    context = json.loads(messages[1]["content"])
    assert "No bytes changed" in context["next_step"]
    assert not context["build_state"]["completion_ready"]


def test_consecutive_source_pages_remain_visible_without_stale_or_gapped_suppression(tmp_path):
    from dsgpt.project_tools import ProjectAction
    from dsgpt.work import visible_source_read

    store, work, tid, _ = setup(tmp_path)
    with store.transaction() as db:
        work.specs.initialize(db, tid, "Implement the requested behavior")
        db.execute("UPDATE work_spec_sections SET notes='Reviewed' WHERE task_id=?", (tid,))
    body = "# π source\n" + "value = 1\n" * 300 + "# end\n"
    digest = hashlib.sha256(body.encode()).hexdigest()
    commit(
        work, tid, ProjectAction(tool="write_file", path="large.py", content=body, summary="Source")
    )
    commit(work, tid, ProjectAction(tool="read_file", path="large.py", summary="Read start"))
    model = replace(work.models["local"], context=16384, output_tokens=4096)
    first = prompt(store, work, tid, model)
    page = json.loads(first[-1]["content"].removeprefix("Recorded tool result: "))
    assert len(page["content"].encode()) == 3000
    assert visible_source_read(first, {"large.py": digest}) is None
    commit(
        work,
        tid,
        ProjectAction(tool="read_file", path="large.py", offset=1800, summary="Read rest"),
    )
    messages = prompt(store, work, tid, model)
    assert visible_source_read(messages, {"large.py": digest}) == "large.py"
    assert visible_source_read(messages, {"large.py": "stale"}) is None
    # Without the previous page, a suffix is not complete-file evidence.
    assert visible_source_read(messages[-2:], {"large.py": digest}) is None
    # A gap or corrupt overlap must not suppress a useful reread.
    import copy

    for change in ("gap", "overlap"):
        damaged = copy.deepcopy(messages)
        last = json.loads(damaged[-1]["content"].removeprefix("Recorded tool result: "))
        if change == "gap":
            last["offset"] = 3001
        else:
            last["content"] = "X" + last["content"][1:]
        damaged[-1]["content"] = "Recorded tool result: " + json.dumps(last)
        assert visible_source_read(damaged, {"large.py": digest}) is None


def test_source_pair_has_priority_over_requirement_preview_and_inventory(tmp_path):
    """Large inventory must not evict the first page and induce alternating reads."""
    from dsgpt.project_tools import ProjectAction
    from dsgpt.work import visible_source_read

    store, work, tid, _ = setup(tmp_path, target="apps")
    request = "Implement the saved requirements. " * 160
    with store.transaction() as db:
        work.specs.initialize(db, tid, request)
        db.execute("UPDATE work_spec_sections SET notes=? WHERE task_id=?", ("Review " * 80, tid))
    for index in range(8):
        commit(work, tid, ProjectAction(
            tool="write_file", path=f"module_{index}.py", content="value = 1\n", summary="Fixture",
        ))
    body = "# source π\n" + "value = 1\n" * 460
    digest = hashlib.sha256(body.encode()).hexdigest()
    commit(work, tid, ProjectAction(
        tool="write_file", path="large.py", content=body, summary="Fixture source",
    ))
    for offset in (0, 2999):
        commit(work, tid, ProjectAction(
            tool="read_file", path="large.py", offset=offset, summary="Inspect source page",
        ))
    model = replace(work.models["local"], context=16384, output_tokens=4096)
    messages = prompt(store, work, tid, model)
    assert visible_source_read(messages, {"large.py": digest}) == "large.py"
    assert ollama_input_estimate(messages) + model.output_tokens <= model.context
    context = json.loads(messages[1]["content"])
    assert context["project_files"]["next_offset"] == 1
    section = context["requirements"]["current_section"]
    assert section["read"]["tool"] == "read_requirements"
    assert "Preview deferred" in section["note"]
    saved = store.one("SELECT requirements_sha256 FROM work_specs WHERE task_id=?", (tid,))
    assert saved["requirements_sha256"] == hashlib.sha256(request.encode()).hexdigest()


def test_noop_edit_retains_observed_companion_page_and_rejection(tmp_path):
    from dsgpt.project_tools import ProjectAction
    from dsgpt.work import visible_source_read

    store, work, tid, _ = setup(tmp_path)
    with store.transaction() as db:
        work.specs.initialize(db, tid, "Implement the requested behavior")
        db.execute("UPDATE work_spec_sections SET notes='Reviewed' WHERE task_id=?", (tid,))
    body = "# unique anchor\n" + "value = 1\n" * 500 + "# final page\n"
    digest = hashlib.sha256(body.encode()).hexdigest()
    for a in [
        ProjectAction(tool="write_file", path="large.py", content=body, summary="Create"),
        ProjectAction(tool="read_file", path="large.py", offset=0, summary="First page"),
        ProjectAction(tool="read_file", path="large.py", offset=3000, summary="Last page"),
        ProjectAction(tool="edit_file", path="large.py", old_text="# unique anchor",
                      new_text="# unique anchor", expected_sha256=digest, summary="Change"),
    ]:
        commit(work, tid, a)
    model = replace(work.models["local"], context=16384, output_tokens=4096)
    messages = prompt(store, work, tid, model)
    result = json.loads(messages[-1]["content"].removeprefix("Recorded tool result: "))
    assert result["error"] == "edit_has_no_change"
    assert visible_source_read(messages, {"large.py": digest}) == "large.py"
    assert visible_source_read(messages, {"large.py": "stale"}) is None
    assert "no source was saved" in messages[-2]["content"]
    assert "No bytes changed" in json.loads(messages[1]["content"])["next_step"]
    assert not json.loads(messages[1]["content"])["build_state"]["completion_ready"]
    assert ollama_input_estimate(messages) + model.output_tokens <= model.context


@pytest.mark.parametrize("companion", ["complete", "partial", "stale", "corrupt"])
def test_both_visible_files_exclude_only_redundant_reads(tmp_path, companion):
    from dsgpt.project_tools import ProjectAction, action_schema
    from dsgpt.work import visible_source_reads

    store, work, tid, _ = setup(tmp_path)
    with store.transaction() as db:
        work.specs.initialize(db, tid, "Implement both modules")
        db.execute("UPDATE work_spec_sections SET notes='Reviewed' WHERE task_id=?", (tid,))
    bodies = {"a.py": "# Unicode π\nvalue = 1\n", "b.py": "value = 2\n"}
    if companion == "partial":
        bodies["a.py"] *= 200
    for path, body in bodies.items():
        commit(
            work, tid, ProjectAction(tool="write_file", path=path, content=body, summary="Create")
        )
    for path in bodies:
        commit(work, tid, ProjectAction(tool="read_file", path=path, summary="Read"))
    messages = prompt(store, work, tid, replace(work.models["local"], context=16384))
    revisions = {p: hashlib.sha256(b.encode()).hexdigest() for p, b in bodies.items()}
    if companion == "stale":
        revisions["a.py"] = "changed"
    if companion == "corrupt":
        for m in messages:
            if m["content"].startswith("Previous source page"):
                m["content"] = m["content"].replace("value = 1", "value = 9")
    visible = visible_source_reads(messages, revisions)
    assert visible == ({"a.py", "b.py"} if companion == "complete" else {"b.py"})
    schema = action_schema(file_paths=list(bodies), already_visible_read=visible)
    choices = {x["properties"]["tool"]["const"]: x["properties"] for x in schema["oneOf"]}
    assert choices["edit_file"]["path"]["enum"] == list(bodies)
    if companion == "complete":
        assert "read_file" not in choices
    else:
        assert choices["read_file"]["path"]["enum"] == ["a.py"]
