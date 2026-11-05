"""Rejected actions are evidence for the next model choice, never executable code."""

import json

import pytest
from pydantic import ValidationError
from test_work_asset_tools import action, setup
from test_work_binary_read_guidance import prompt
from test_work_completion_phase import commit

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
