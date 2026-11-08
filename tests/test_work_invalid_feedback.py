"""Rejected actions are evidence for the next model choice, never executable code."""

import json
from dataclasses import replace

import pytest
from pydantic import ValidationError
from test_work_asset_tools import action, setup
from test_work_binary_read_guidance import prompt
from test_work_completion_phase import commit

from dsgpt.inference import ollama_input_estimate
from dsgpt.work import parse_model_action


@pytest.mark.parametrize(
    "raw", ['{"tool":"edit_file","new_text":"unfinished', '{"tool":"unknown","summary":"invalid"}']
)
def test_invalid_feedback_survives_history_selection_without_replaying_bad_output(tmp_path, raw):
    store, work, tid, _ = setup(tmp_path, target="source")
    with store.transaction() as db:
        work.specs.initialize(db, tid, "Create a small source file")
        db.execute("UPDATE work_spec_sections SET notes='Reviewed' WHERE task_id=?", (tid,))
    commit(work, tid, action(tool="write_file", path="a.py", content="value = 0\n"))
    commit(work, tid, action(tool="read_file", path="a.py"))
    for attempt in range(1, 4):
        with store.transaction() as db:
            db.execute("UPDATE work_tasks SET status='running' WHERE id=?", (tid,))
        session = store.one("SELECT * FROM work_sessions WHERE task_id=?", (tid,))
        with pytest.raises(ValidationError) as caught:
            parse_model_action(raw)
        work._invalid_action(tid, session, raw, caught.value)
        messages = prompt(store, work, tid)
        context = json.loads(messages[1]["content"])
        result = json.loads(messages[-1]["content"].removeprefix("Recorded tool result: "))
        assert result["error"] == "invalid_action" and result["fields"]
        assert "NO action was executed" in context["next_step"]
        assert "one small edit" in context["next_step"]
        assert raw not in "\n".join(m["content"] for m in messages)
        assert store.one("SELECT content FROM work_files WHERE task_id=?", (tid,))["content"] == (
            "value = 0\n"
        )
        assert store.one("SELECT status FROM work_tasks WHERE id=?", (tid,))["status"] == (
            "blocked" if attempt == 3 else "queued"
        )
    saved = store.one("SELECT action FROM work_steps WHERE task_id=? ORDER BY step DESC", (tid,))
    assert json.loads(saved["action"])["invalid_output"] == raw


@pytest.mark.parametrize("recover", [True, False])
@pytest.mark.parametrize("context_size", [8192, 16384])
async def test_streamed_rejection_reaches_next_call_and_only_valid_edit_can_change_file(
    tmp_path, recover, context_size
):
    """Controller integration fixture; not evidence that a real model recovers."""
    store, work, tid, _ = setup(tmp_path, target="source")
    with store.transaction() as db:
        original_request = "Change the saved value from zero to one"
        db.execute("UPDATE work_tasks SET requirements=? WHERE id=?", (original_request, tid))
        work.specs.initialize(db, tid, original_request)
        db.execute("UPDATE work_spec_sections SET notes='Reviewed' WHERE task_id=?", (tid,))
    commit(work, tid, action(tool="write_file", path="a.py", content="value = 0\n"))
    commit(work, tid, action(tool="read_file", path="a.py"))
    work.models["local"] = replace(work.models["local"], context=context_size)
    original = store.one("SELECT sha256 FROM work_files WHERE task_id=?", (tid,))["sha256"]
    invalid = '{"tool":"edit_file","path":"a.py","new_text":"unfinished'

    class StreamedChoices:
        calls = 0

        async def stream(self, model, messages, response_schema=None):
            assert ollama_input_estimate(messages) + model.output_tokens <= model.context
            self.calls += 1
            if self.calls > 1:
                context = json.loads(messages[1]["content"])
                recorded = (
                    json.loads(messages[-1]["content"].removeprefix("Recorded tool result: "))
                    if messages[-1]["content"].startswith("Recorded tool result: ")
                    else context["previous_result"]
                )
                assert recorded["error"] == "invalid_action"
                assert "NO action was executed" in context["next_step"]
                assert recorded["fields"][0]["type"] == "json_invalid"
                assert invalid not in "\n".join(m["content"] for m in messages)
            chosen = (
                json.dumps({
                    "tool": "edit_file", "path": "a.py", "expected_sha256": original,
                    "old_text": "value = 0", "new_text": "value = 1",
                    "summary": "Fixture corrected edit",
                })
                if recover and self.calls == 2 else invalid
            )
            for start in range(0, len(chosen), 9):
                yield {"kind": "delta", "data": {"text": chosen[start:start + 9]}}

    inference = work.inference = StreamedChoices()
    for attempt in range(1, 3 if recover else 4):
        await work._step(store.one("SELECT * FROM work_tasks WHERE id=?", (tid,)))
        expected = "value = 1\n" if recover and attempt == 2 else "value = 0\n"
        assert store.one("SELECT content FROM work_files WHERE task_id=?", (tid,))["content"] == (
            expected
        )
    session = store.one("SELECT * FROM work_sessions WHERE task_id=?", (tid,))
    assert inference.calls == (2 if recover else 3)
    assert session["repeated_actions"] == (0 if recover else 3)
    assert work.get(tid)["status"] == ("queued" if recover else "blocked")


@pytest.mark.parametrize("rejection", ["invalid_action", "existing_file_requires_targeted_edit"])
@pytest.mark.parametrize("case", [
    "current", "two_rejections", "stale", "partial", "intervening",
    "comparison", "noop_comparison", "stale_comparison",
])
def test_rejected_response_retains_only_current_observed_source(tmp_path, case, rejection):
    import hashlib

    from dsgpt.project_tools import action_schema
    from dsgpt.work import RETAINED_SOURCE_PREFIX, visible_source_read

    store, work, tid, _ = setup(tmp_path, target="source")
    with store.transaction() as db:
        work.specs.initialize(db, tid, "Implement the requested change")
        db.execute("UPDATE work_spec_sections SET notes='Reviewed' WHERE task_id=?", (tid,))
    body = "# Unicode π\nvalue = 0\n" if case != "partial" else "value = 0\n" * 500
    commit(work, tid, action(tool="write_file", path="a.py", content=body))
    commit(work, tid, action(tool="read_file", path="a.py"))
    if case == "intervening":
        commit(work, tid, action(tool="list_files"))
    if case == "noop_comparison":
        digest = hashlib.sha256(body.encode()).hexdigest()
        commit(work, tid, action(tool="edit_file", path="a.py", expected_sha256=digest,
                                old_text="value = 0", new_text="value = 0"))
    if case in {"comparison", "noop_comparison", "stale_comparison"}:
        commit(work, tid, action(tool="read_requirements", requirement_id=1, offset=0))
    if case in {"stale", "stale_comparison"}:
        with store.transaction() as db:
            db.execute(
                "UPDATE work_files SET content=?,sha256=? WHERE task_id=? AND path='a.py'",
                ("changed", hashlib.sha256(b"changed").hexdigest(), tid),
            )
    raw = '{"tool":"write_file","path":"a.py","content":"unfinished'
    for _ in range(2 if case == "two_rejections" else 1):
        with store.transaction() as db:
            db.execute("UPDATE work_tasks SET status='running' WHERE id=?", (tid,))
        if rejection == "invalid_action":
            with pytest.raises(ValidationError) as caught:
                parse_model_action(raw)
            work._invalid_action(
                tid, store.one("SELECT * FROM work_sessions WHERE task_id=?", (tid,)),
                raw, caught.value
            )
        else:
            commit(work, tid, action(tool="write_file", path="a.py", content="WRONG replacement"))
    model = replace(work.models["local"], context=16384, output_tokens=4096)
    messages = prompt(store, work, tid, model)
    assert ollama_input_estimate(messages) + model.output_tokens <= model.context
    result = json.loads(messages[-1]["content"].removeprefix("Recorded tool result: "))
    assert result["error"] == rejection
    assert raw not in "\n".join(m["content"] for m in messages)
    retained = [m for m in messages if m["content"].startswith(RETAINED_SOURCE_PREFIX)]
    revisions = {
        row["path"]: row["sha256"] for row in store.all(
            "SELECT path,sha256 FROM work_files WHERE task_id=?", (tid,)
        )
    }
    visible = visible_source_read(messages, revisions)
    complete = case in {"current", "two_rejections", "intervening", "comparison", "noop_comparison"}
    if complete:
        assert len(retained) == 1
        assert json.loads(retained[0]["content"][len(RETAINED_SOURCE_PREFIX):])["content"] == body
        assert visible == "a.py"
        assert visible_source_read(messages, {"a.py": "changed"}) is None
    else:
        assert visible is None
        if case != "partial":
            assert not retained
    grammar = action_schema(file_paths=["a.py"], already_visible_read=visible)
    choices = {v["properties"]["tool"]["const"] for v in grammar["oneOf"]}
    assert ("read_file" not in choices) == complete
    assert "edit_file" in choices and "write_file" in choices


@pytest.mark.parametrize("context_size", [512, 8192, 16384])
def test_rejected_overwrite_guides_targeted_edit_and_never_mutates_source(tmp_path, context_size):
    from dsgpt.work import RETAINED_SOURCE_PREFIX

    store, work, tid, _ = setup(tmp_path, target="source")
    with store.transaction() as db:
        work.specs.initialize(db, tid, "Change the saved value")
        db.execute("UPDATE work_spec_sections SET notes='Reviewed' WHERE task_id=?", (tid,))
    commit(work, tid, action(tool="write_file", path="a.py", content="value = 0\n"))
    commit(work, tid, action(tool="read_file", path="a.py"))
    before = store.one("SELECT sha256,content FROM work_files WHERE task_id=?", (tid,))
    commit(work, tid, action(tool="write_file", path="a.py", content="REJECTED proposal"))
    model = replace(work.models["local"], context=context_size, output_tokens=128)
    messages = prompt(store, work, tid, model)
    context = json.loads(messages[1]["content"])
    assert "NO source changed" in context["next_step"]
    assert "read_file only" in context["next_step"]
    assert "Do not retry write_file" in context["next_step"]
    assert "REJECTED proposal" not in "\n".join(m["content"] for m in messages)
    after = store.one("SELECT sha256,content FROM work_files WHERE task_id=?", (tid,))
    assert dict(after) == dict(before)
    if context_size > 512:
        assert ollama_input_estimate(messages) + model.output_tokens <= model.context
        assert any(m["content"].startswith(RETAINED_SOURCE_PREFIX) for m in messages)
        commit(work, tid, action(
            tool="edit_file", path="a.py", expected_sha256=before["sha256"],
            old_text="value = 0", new_text="value = 1",
        ))
        saved = store.one("SELECT content FROM work_files WHERE task_id=?", (tid,))
        assert saved["content"] == "value = 1\n"
    else:
        assert context["previous_result"]["error"] == "existing_file_requires_targeted_edit"


@pytest.mark.parametrize("case", ["current", "stale", "partial"])
@pytest.mark.parametrize("rejection", ["overwrite", "wrong_hash"])
def test_rejected_overwrite_retains_target_not_newer_unrelated_read(tmp_path, case, rejection):
    import hashlib

    from dsgpt.work import RETAINED_SOURCE_PREFIX, visible_source_reads

    store, work, tid, _ = setup(tmp_path, target="source")
    with store.transaction() as db:
        work.specs.initialize(db, tid, "Implement the requested change")
        db.execute("UPDATE work_spec_sections SET notes='Reviewed' WHERE task_id=?", (tid,))
    body = "value = 0\n" * (500 if case == "partial" else 1)
    commit(work, tid, action(tool="write_file", path="a.py", content=body))
    commit(work, tid, action(tool="write_file", path="build.txt", content="configuration\n"))
    commit(work, tid, action(tool="read_file", path="a.py"))
    commit(work, tid, action(tool="read_file", path="build.txt"))
    if case == "stale":
        with store.transaction() as db:
            db.execute("UPDATE work_files SET content=?,sha256=? WHERE task_id=? AND path='a.py'",
                       ("changed", hashlib.sha256(b"changed").hexdigest(), tid))
    if rejection == "overwrite":
        commit(work, tid, action(tool="write_file", path="a.py", content="Rejected proposal"))
    else:
        commit(work, tid, action(tool="edit_file", path="a.py", expected_sha256="0" * 64,
                                old_text="value = 0", new_text="value = 1"))
    model = replace(work.models["local"], context=16384, output_tokens=4096)
    messages = prompt(store, work, tid, model)
    revisions = {r["path"]: r["sha256"] for r in store.all(
        "SELECT path,sha256 FROM work_files WHERE task_id=?", (tid,))}
    retained = [json.loads(m["content"][len(RETAINED_SOURCE_PREFIX):]) for m in messages
                if m["content"].startswith(RETAINED_SOURCE_PREFIX)]
    assert all(p["path"] == "a.py" for p in retained)
    assert visible_source_reads(messages, revisions) == ({"a.py"} if case == "current" else set())
    assert ollama_input_estimate(messages) + model.output_tokens <= model.context
    assert ("existing_file_requires_targeted_edit" if rejection == "overwrite" else
            "file_changed_read_before_overwrite") in messages[-1]["content"]
    assert store.one("SELECT content FROM work_files WHERE task_id=? AND path='a.py'", (tid,))[
        "content"] == ("changed" if case == "stale" else body)


@pytest.mark.parametrize('stale', [False, True])
def test_rejected_edit_retains_source_under_context_pressure(tmp_path, stale):
    import hashlib

    from dsgpt.storage import canonical, utcnow
    from dsgpt.work import RETAINED_SOURCE_PREFIX, visible_source_read

    store, work, tid, _ = setup(tmp_path, target='source')
    with store.transaction() as db:
        work.specs.initialize(db, tid, 'Implement the module and verify its behavior. ' * 45)
        db.execute("UPDATE work_spec_sections SET notes='Reviewed' WHERE task_id=?", (tid,))
        db.execute('UPDATE work_specs SET brief=? WHERE task_id=?',
                   ('Overview details. ' * 150, tid))
    body = '# Unicode π\n' + 'value = 0\n' * 210
    digest = hashlib.sha256(body.encode()).hexdigest()
    commit(work, tid, action(tool='write_file', path='a.py', content=body))
    commit(work, tid, action(tool='read_file', path='a.py'))
    commit(work, tid, action(tool='edit_file', path='a.py', old_text='absent',
                            new_text='replacement', expected_sha256=digest))
    with store.transaction() as db:
        db.execute('UPDATE work_sessions SET summary=? WHERE task_id=?',
                   ('Inspect errors. ' * 25, tid))
        db.execute('INSERT INTO work_executions(id,task_id,step,action,snapshot_sha256,'
                   'status,result,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
                   ('build', tid, 0, '{}', 'old-snapshot', 'failed',
                    canonical({'error': 'command_failed', 'stderr': 'Compiler error. ' * 150,
                               'stdout': 'Build output. ' * 80}), utcnow(), utcnow()))
        if stale:
            db.execute("UPDATE work_files SET content='changed',sha256='changed' WHERE task_id=?",
                       (tid,))
    model = replace(work.models['local'], context=16384, output_tokens=4096)
    messages = prompt(store, work, tid, model)
    assert ollama_input_estimate(messages) + model.output_tokens <= model.context
    result = json.loads(messages[-1]['content'].removeprefix('Recorded tool result: '))
    assert result['error'] == 'edit_match_not_unique' and result['matches'] == 0
    retained = [m for m in messages if m['content'].startswith(RETAINED_SOURCE_PREFIX)]
    assert bool(retained) is not stale
    assert visible_source_read(messages, {'a.py': digest}) == (None if stale else 'a.py')
    if not stale:
        page = json.loads(retained[0]['content'][len(RETAINED_SOURCE_PREFIX):])
        assert page['content'] == body and page['sha256'] == digest
