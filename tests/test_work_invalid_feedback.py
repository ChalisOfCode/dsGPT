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


@pytest.mark.parametrize("case", ["current", "two_rejections", "stale", "partial", "intervening"])
def test_rejected_response_retains_only_current_observed_source(tmp_path, case):
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
    if case == "stale":
        with store.transaction() as db:
            db.execute(
                "UPDATE work_files SET content=?,sha256=? WHERE task_id=? AND path='a.py'",
                ("changed", hashlib.sha256(b"changed").hexdigest(), tid),
            )
    raw = '{"tool":"write_file","path":"a.py","content":"unfinished'
    for _ in range(2 if case == "two_rejections" else 1):
        with store.transaction() as db:
            db.execute("UPDATE work_tasks SET status='running' WHERE id=?", (tid,))
        with pytest.raises(ValidationError) as caught:
            parse_model_action(raw)
        work._invalid_action(
            tid, store.one("SELECT * FROM work_sessions WHERE task_id=?", (tid,)), raw, caught.value
        )
    model = replace(work.models["local"], context=16384, output_tokens=4096)
    messages = prompt(store, work, tid, model)
    assert ollama_input_estimate(messages) + model.output_tokens <= model.context
    result = json.loads(messages[-1]["content"].removeprefix("Recorded tool result: "))
    assert result["error"] == "invalid_action"
    assert raw not in "\n".join(m["content"] for m in messages)
    retained = [m for m in messages if m["content"].startswith(RETAINED_SOURCE_PREFIX)]
    revisions = {
        row["path"]: row["sha256"] for row in store.all(
            "SELECT path,sha256 FROM work_files WHERE task_id=?", (tid,)
        )
    }
    visible = visible_source_read(messages, revisions)
    if case in {"current", "two_rejections"}:
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
    assert ("read_file" not in choices) == (case in {"current", "two_rejections"})
    assert "edit_file" in choices and "write_file" in choices
