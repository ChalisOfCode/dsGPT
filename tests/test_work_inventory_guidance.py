import json

import pytest

from dsgpt.config import Model
from dsgpt.project_tools import ProjectAction, ProjectTools
from dsgpt.storage import Store
from dsgpt.work import WorkRegistry


@pytest.mark.parametrize("count,offset,expected_next", [(3, 0, None), (7, 0, 4), (7, 4, None)])
def test_inventory_guidance_exposes_real_continuation_and_source_next_step(
    tmp_path, count, offset, expected_next
):
    store = Store(tmp_path)
    model = Model("local", "Local", "ollama", "http://127.0.0.1:11434", "local")
    work = WorkRegistry(store, models={model.id: model})
    task = work.create("Build", "Implement a native application and test it.", model.id)
    tid = task["id"]
    with store.transaction() as db:
        work.specs.initialize(db, tid, task["requirements"])
        db.execute("UPDATE work_spec_sections SET notes='Reviewed' WHERE task_id=?", (tid,))
        db.execute("UPDATE work_tasks SET status='running' WHERE id=?", (tid,))
        for index in range(count):
            ProjectTools.apply(
                db,
                tid,
                ProjectAction(
                    tool="write_file", path=f"module{index}.py", content="pass\n", summary="Fixture"
                ),
            )
    session = store.one("SELECT * FROM work_sessions WHERE task_id=?", (tid,))
    work._commit(tid, session, ProjectAction(tool="list_files", offset=offset, summary="Inspect"))
    row = store.one("SELECT * FROM work_tasks WHERE id=?", (tid,))
    session = store.one("SELECT * FROM work_sessions WHERE task_id=?", (tid,))
    messages = work._guided_prompt(row, session, model, [])
    context = json.loads(messages[1]["content"])
    assert "not empty" in context["next_step"]
    assert "call read_file" in context["next_step"]
    recorded = next(
        json.loads(m["content"].removeprefix("Recorded tool result: "))
        for m in messages
        if m["content"].startswith("Recorded tool result: ")
    )
    assert recorded["next_offset"] == expected_next
    assert len(recorded["files"]) == min(4, count - offset)
    assert ("read_more" in recorded) == (expected_next is not None)
    assert store.one("SELECT count(*) AS n FROM work_files WHERE task_id=?", (tid,))["n"] == count
    assert context["build_state"]["coverage_ready"] is False
