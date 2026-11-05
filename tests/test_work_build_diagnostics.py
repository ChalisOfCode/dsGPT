"""Compiler failure evidence must survive subsequent source inspection."""

import json
from dataclasses import replace

import pytest
from test_work_asset_tools import action, setup
from test_work_binary_read_guidance import prompt
from test_work_completion_phase import commit, reviewed

from dsgpt.builds import snapshot_hash
from dsgpt.inference import ollama_input_estimate
from dsgpt.storage import canonical, uid, utcnow
from dsgpt.work import build_log_excerpt


@pytest.mark.parametrize("stream", ["stderr", "stdout"])
def test_compiler_diagnostic_remains_after_reads_and_is_marked_stale_after_edit(tmp_path, stream):
    store, work, tid, _ = setup(tmp_path, target="apps")
    with store.transaction() as db:
        work.specs.initialize(db, tid, "Implement a working calculator with behavior tests")
        db.execute("UPDATE work_spec_sections SET notes='Reviewed' WHERE task_id=?", (tid,))
    for path, body in [("main.kt", "// implement calculator\n"), ("test.kt", "Calculator()\n")]:
        commit(work, tid, action(tool="write_file", path=path, content=body))
    files = store.all("SELECT path,sha256 FROM work_files WHERE task_id=?", (tid,))
    diagnostic = "e: file:///work/test.kt:1:1 Unresolved reference 'Calculator'.\n"
    log = diagnostic + "\nMore compiler output\n" * 100 + "BUILD FAILED\n"
    result = {"error": "command_failed", stream: log, "exit_code": 1}
    execution_id = uid()
    with store.transaction() as db:
        db.execute(
            "INSERT INTO work_executions(id,task_id,step,action,snapshot_sha256,status,result,"
            "cleanup_pending,recorded,created_at,updated_at) "
            "VALUES(?,?,?,?,?,'failed',?,0,1,?,?)",
            (
                execution_id,
                tid,
                3,
                '{"tool":"build_project"}',
                snapshot_hash(files),
                canonical(result),
                utcnow(),
                utcnow(),
            ),
        )
    commit(work, tid, action(tool="build_project", target="apps"), result)
    model = replace(work.models["local"], context=16384, output_tokens=4096)
    # Once two source reads displace the action history, the build evidence must
    # still show the original error, rather than only the generic failure tail.
    for path in ("test.kt", "main.kt"):
        commit(work, tid, action(tool="read_file", path=path))
        messages = prompt(store, work, tid, model)
        state = json.loads(messages[1]["content"])["build_state"]
        latest = state["latest"]
        assert diagnostic.strip() in latest[stream]
        assert "BUILD FAILED" in latest[stream]
        assert "read_build_log" in latest[stream]
        assert latest["id"] == execution_id and latest["current_sources"]
        assert "CURRENT sources" in latest["recovery"]
        assert not state["completion_ready"]
        assert ollama_input_estimate(messages) + model.output_tokens <= model.context
    current = next(f for f in files if f["path"] == "main.kt")
    commit(
        work,
        tid,
        action(
            tool="edit_file",
            path="main.kt",
            old_text="// implement calculator",
            new_text="class Calculator",
            expected_sha256=current["sha256"],
        ),
    )
    commit(work, tid, action(tool="read_file", path="main.kt"))
    latest = json.loads(prompt(store, work, tid, model)[1]["content"])["build_state"]["latest"]
    assert not latest["current_sources"] and "OLDER source snapshot" in latest["recovery"]
    assert diagnostic.strip() in latest[stream]  # Retain history without calling it current.
    assert (
        json.loads(
            store.one("SELECT result FROM work_executions WHERE id=?", (execution_id,))["result"]
        )
        == result
    )  # Prompt budgeting must not destroy the full stored log.


@pytest.mark.parametrize("budget", [700, 1200])
def test_build_log_excerpt_preserves_short_output_and_bounds_utf8(budget):
    short = "error: αβγ\n"
    assert build_log_excerpt(short, budget) == short
    original = short + "中文🙂" * 1000 + "\nFAILED"
    excerpt = build_log_excerpt(original, budget)
    assert len(excerpt.encode()) <= budget
    assert excerpt.startswith(short) and excerpt.endswith("FAILED")
    assert "\ufffd" not in excerpt and "read_build_log" in excerpt


async def test_successful_current_execution_does_not_receive_failure_recovery(tmp_path):
    store, work, tid, _ = await reviewed(tmp_path)
    state = json.loads(prompt(store, work, tid)[1]["content"])["build_state"]
    assert state["completion_ready"]
    assert "recovery" not in state["latest"]
