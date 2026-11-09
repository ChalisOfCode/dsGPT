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


def test_source_comparison_is_not_evicted_for_an_older_requirement(tmp_path):
    from dsgpt.work import visible_source_reads

    store, work, tid, _ = setup(tmp_path, target="apps")
    original = "Implement the requested behavior and test it. " * 30
    with store.transaction() as db:
        db.execute("DELETE FROM work_inputs WHERE task_id=?", (tid,))
        db.execute("UPDATE work_tasks SET requirements=? WHERE id=?", (original, tid))
        work.specs.initialize(db, tid, original)
        db.execute("UPDATE work_spec_sections SET notes='Reviewed' WHERE task_id=?", (tid,))
    body = "value = 0\n" * 240
    commit(work, tid, action(tool="write_file", path="model.py", content=body))
    commit(work, tid, action(tool="write_file", path="view.py", content="# display\n" * 100))
    with store.transaction() as db:
        db.execute(
            "INSERT INTO work_executions(id,task_id,step,action,snapshot_sha256,status,"
            "result,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            ("failed-build", tid, 0, '{}', "old", "failed",
             canonical({"error": "command_failed", "stderr": "Compiler diagnostic. " * 100,
                        "stdout": "Build progress. " * 100}), utcnow(), utcnow()),
        )
    commit(work, tid, action(tool="read_requirements", requirement_id=1))
    commit(work, tid, action(tool="read_file", path="model.py"))
    commit(work, tid, action(tool="read_file", path="view.py"))
    hashes = {f['path']: f['sha256'] for f in store.all(
        'SELECT path,sha256 FROM work_files WHERE task_id=?', (tid,))}
    model = replace(work.models['local'], context=16384, output_tokens=4096)
    messages = prompt(store, work, tid, model)
    assert 'model.py' in visible_source_reads(messages, hashes)
    assert 'view.py' in visible_source_reads(messages, hashes)
    assert ollama_input_estimate(messages) + model.output_tokens <= model.context
    assert json.loads(messages[1]['content'])['build_state']['latest']['status'] == 'failed'


def test_failed_build_keeps_observed_error_page_ahead_of_recent_suffixes(tmp_path):
    store, work, tid, _ = setup(tmp_path, target="apps")
    original = "Implement and test the complete application. " * 40
    body = "// source line with Unicode αβ\n" * 260
    with store.transaction() as db:
        db.execute("DELETE FROM work_inputs WHERE task_id=?", (tid,))
        db.execute("UPDATE work_tasks SET requirements=? WHERE id=?", (original, tid))
        work.specs.initialize(db, tid, original)
        db.execute("UPDATE work_spec_sections SET notes='Reviewed' WHERE task_id=?", (tid,))
    commit(work, tid, action(tool="write_file", path="src/model.kt", content=body))
    files = store.all("SELECT path,sha256 FROM work_files WHERE task_id=?", (tid,))
    result = {"error": "command_failed", "stderr":
              "e: file:///work/src/model.kt:31:20 Invalid receiver\n" + "details\n" * 200}
    with store.transaction() as db:
        db.execute(
            "INSERT INTO work_executions(id,task_id,step,action,snapshot_sha256,status,"
            "result,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
            ("failure", tid, 2, '{"tool":"build_project"}', snapshot_hash(files), "failed",
             canonical(result), utcnow(), utcnow()),
        )
    for offset in (0, 1800, 3600, 5400, 7200, 7200):
        commit(work, tid, action(tool="read_file", path="src/model.kt", offset=offset))
    found = False
    for size in range(10000, 16385, 256):
        model = replace(work.models['local'], context=size, output_tokens=4096)
        messages = prompt(store, work, tid, model)
        previous = [json.loads(m['content'][m['content'].index('{'):]) for m in messages
                    if m['content'].startswith('Previous source page')]
        if not previous:
            continue
        assert previous[0]['offset'] == 0
        assert previous[0]['content'] == body.encode()[:3000].decode('utf-8', errors='ignore')
        assert ollama_input_estimate(messages) + model.output_tokens <= model.context
        found = True
    assert found
    # An old snapshot or a successful execution must not prioritize this error.
    for status, digest in [('failed', 'older'), ('completed', snapshot_hash(files))]:
        with store.transaction() as db:
            db.execute('UPDATE work_executions SET status=?,snapshot_sha256=? WHERE id=?',
                       (status, digest, 'failure'))
        messages = prompt(store, work, tid, replace(model, context=16384))
        previous = [json.loads(m['content'][m['content'].index('{'):]) for m in messages
                    if m['content'].startswith('Previous source page')]
        assert previous and previous[0]['offset'] == 5400


@pytest.mark.parametrize('damage', [None, 'hash', 'content', 'action', 'path', 'unseen'])
def test_diagnostic_page_priority_requires_exact_observed_source(damage):
    import hashlib

    from dsgpt.work import diagnostic_source_pages

    body = 'αβ\nsecond line\n'
    source = {'content': body, 'sha256': hashlib.sha256(body.encode()).hexdigest()}
    page = {'path': 'src/a.kt', 'offset': 3, 'content': 'second line\n',
            'sha256': source['sha256']}
    chosen = {'tool': 'read_file', 'path': 'src/a.kt'}
    if damage == 'hash':
        page['sha256'] = 'old'
    elif damage == 'content':
        page['content'] = 'fabricated'
    elif damage == 'action':
        chosen['tool'] = 'write_file'
    elif damage == 'path':
        chosen['path'] = 'other.kt'
    history = [{'action': canonical(chosen), 'result': canonical(page)}]
    if damage == 'unseen':
        history = []
    assert diagnostic_source_pages(history, {'src/a.kt': source},
                                   'e: file:///work/src/a.kt:2:1 error') == (
        {('src/a.kt', 3)} if damage is None else set())
    for diagnostic in ['other/src/a.kt:2:1 error', 'src/a.kt:0:1 error',
                       'src/a.kt:999:1 error', 'src/a.kt:2 without column']:
        assert not diagnostic_source_pages(history, {'src/a.kt': source}, diagnostic)
