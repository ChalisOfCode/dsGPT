"""Ready tasks still require an explicit model finish or blocker decision."""

import json

import pytest
from test_work_asset_tools import action, setup

from dsgpt.project_tools import ProjectAction, ProjectTools, action_schema
from dsgpt.storage import uid, utcnow


def commit(work, tid, chosen, result=None):
    with work.store.transaction() as db:
        db.execute("UPDATE work_tasks SET status='running' WHERE id=?", (tid,))
    session = work.store.one("SELECT * FROM work_sessions WHERE task_id=?", (tid,))
    work._commit(tid, session, chosen, result)


async def reviewed(tmp_path):
    store, work, tid, sandbox = setup(tmp_path)
    row = store.one("SELECT * FROM work_tasks WHERE id=?", (tid,))
    with store.transaction() as db:
        work.specs.initialize(db, tid, row["requirements"])
        db.execute("UPDATE work_spec_sections SET notes='Reviewed' WHERE task_id=?", (tid,))
    result = await work.builds.execute(tid, 1, action())
    commit(work, tid, action(), result)
    speech = result["transcription"]
    commit(
        work,
        tid,
        ProjectAction(
            tool="mark_requirement",
            requirement_id=1,
            evidence_paths=[speech["transcript_path"], speech["subtitles_path"]],
            content="Fixture review of collected transcript and subtitles.",
            summary="Review fixture",
        ),
    )
    assert work._completion_ready(tid)
    return store, work, tid, result


def choices(schema):
    return {item["properties"]["tool"]["const"] for item in schema["oneOf"]}


@pytest.mark.parametrize("final_tool", ["finish", "blocked"])
async def test_ready_read_last_keeps_finish_priority_and_model_final_choice(tmp_path, final_tool):
    store, work, tid, result = await reviewed(tmp_path)
    for path in (
        result["transcription"]["subtitles_path"],
        result["transcription"]["transcript_path"],
    ):
        commit(work, tid, action(tool="read_asset", path=path))
    row = store.one("SELECT * FROM work_tasks WHERE id=?", (tid,))
    session = store.one("SELECT * FROM work_sessions WHERE task_id=?", (tid,))
    messages = work._guided_prompt(row, session, work.models["local"], [])
    context = json.loads(messages[1]["content"])
    assert context["build_state"]["completion_ready"]
    assert "Call finish now" in context["next_step"]
    assert "Compare their text" not in context["next_step"]
    assert choices(
        action_schema(isolated_execution=True, specification=True, completion_only=True)
    ) == {"finish", "blocked"}
    assert store.one("SELECT status FROM work_tasks WHERE id=?", (tid,))["status"] == "queued"

    class FinalChoice:
        async def stream(self, model, messages, response_schema=None):
            assert choices(response_schema) == {"finish", "blocked"}
            yield {
                "kind": "delta",
                "data": {
                    "text": json.dumps({"tool": final_tool, "summary": "Fixture final decision"})
                },
            }

    work.inference = FinalChoice()
    await work._step(row)
    expected = "completed" if final_tool == "finish" else "blocked"
    assert store.one("SELECT status FROM work_tasks WHERE id=?", (tid,))["status"] == expected
    assert (
        json.loads(
            store.one(
                "SELECT action FROM work_steps WHERE task_id=? ORDER BY step DESC LIMIT 1", (tid,)
            )["action"]
        )["tool"]
        == final_tool
    )


@pytest.mark.parametrize(
    "change", ["source_edit", "stale_receipt", "missing_receipt", "latest_failure", "uncovered"]
)
async def test_invalidated_completion_restores_normal_action_tools(tmp_path, change):
    store, work, tid, result = await reviewed(tmp_path)
    with store.transaction() as db:
        if change == "source_edit":
            ProjectTools.apply(
                db,
                tid,
                ProjectAction(
                    tool="write_file", path="new.txt", content="changed source", summary="Change"
                ),
            )
        elif change == "stale_receipt":
            db.execute(
                "UPDATE work_artifacts SET sha256=? WHERE id=?",
                ("f" * 64, result["artifacts"][0]["id"]),
            )
        elif change == "missing_receipt":
            db.execute("DELETE FROM work_artifacts WHERE id=?", (result["artifacts"][0]["id"],))
        elif change == "uncovered":
            db.execute("UPDATE work_spec_sections SET status='pending' WHERE task_id=?", (tid,))
        else:
            db.execute(
                "INSERT INTO work_executions(id,task_id,step,action,snapshot_sha256,status,result,"
                "cleanup_pending,recorded,created_at,updated_at) "
                "VALUES(?,?,?,?,?,'failed',?,0,1,?,?)",
                (
                    uid(),
                    tid,
                    99,
                    "{}",
                    result["snapshot_sha256"],
                    '{"error":"fixture_failure"}',
                    utcnow(),
                    utcnow(),
                ),
            )
    assert not work._completion_ready(tid)
    schema = action_schema(
        isolated_execution=True, specification=True, completion_only=work._completion_ready(tid)
    )
    assert {
        "read_asset",
        "transcribe_media",
        "mark_requirement",
        "run",
        "finish",
        "blocked",
    } <= choices(schema)

    class RepairChoice:
        async def stream(self, model, messages, response_schema=None):
            assert "run" in choices(response_schema) and "read_asset" in choices(response_schema)
            assert "Call finish now" not in json.loads(messages[1]["content"])["next_step"]
            yield {
                "kind": "delta",
                "data": {
                    "text": json.dumps(
                        {"tool": "blocked", "summary": "Investigate fixture invalidation"}
                    )
                },
            }

    work.inference = RepairChoice()
    await work._step(store.one("SELECT * FROM work_tasks WHERE id=?", (tid,)))
    assert store.one("SELECT status FROM work_tasks WHERE id=?", (tid,))["status"] == "blocked"


def test_source_only_completion_needs_enabled_current_coverage_and_actual_files(tmp_path):
    store, work, tid, _ = setup(tmp_path, target="source")
    assert not work._completion_ready(tid)
    with store.transaction() as db:
        requirements = db.execute(
            "SELECT requirements FROM work_tasks WHERE id=?", (tid,)
        ).fetchone()[0]
        work.specs.initialize(db, tid, requirements)
        db.execute("UPDATE work_spec_sections SET notes='Reviewed' WHERE task_id=?", (tid,))
        ProjectTools.apply(
            db,
            tid,
            ProjectAction(tool="write_file", path="main.txt", content="source", summary="Draft"),
        )
        ProjectTools.apply(
            db,
            tid,
            ProjectAction(
                tool="mark_requirement",
                evidence_paths=["main.txt"],
                content="Reviewed saved source",
                summary="Review",
            ),
        )
    assert work._completion_ready(tid)
    with store.transaction() as db:
        db.execute("DELETE FROM work_files WHERE task_id=?", (tid,))
    assert not work._completion_ready(tid)


@pytest.mark.parametrize(
    "target,platform", [("apk", "android"), ("exe", "windows"), ("apps", "android")]
)
def test_empty_app_project_guides_scaffolding_without_claiming_features(tmp_path, target, platform):
    store, work, _, _ = setup(tmp_path)
    task = work.create(
        "Requested app", "Build an app with editable tasks.", "local", build_target=target
    )
    tid = task["id"]
    with store.transaction() as db:
        work.specs.initialize(db, tid, task["requirements"])
        db.execute("UPDATE work_spec_sections SET notes='Reviewed' WHERE task_id=?", (tid,))
    for tool in ("list_files", "read_requirements"):
        commit(work, tid, ProjectAction(tool=tool, requirement_id=1, summary="Inspect"))
        row = store.one("SELECT * FROM work_tasks WHERE id=?", (tid,))
        session = store.one("SELECT * FROM work_sessions WHERE task_id=?", (tid,))
        context = json.loads(
            work._guided_prompt(row, session, work.models["local"], [])[1]["content"]
        )
        assert "ZERO source files" in context["next_step"]
        assert "scaffold_app with platform=" + platform in context["next_step"]
        assert "not finished" in context["next_step"]
        assert not context["build_state"]["completion_ready"]
    commit(
        work,
        tid,
        ProjectAction(
            tool="scaffold_app", platform=platform, title="Requested app", summary="Create starter"
        ),
    )
    row = store.one("SELECT * FROM work_tasks WHERE id=?", (tid,))
    session = store.one("SELECT * FROM work_sessions WHERE task_id=?", (tid,))
    context = json.loads(work._guided_prompt(row, session, work.models["local"], [])[1]["content"])
    assert "ZERO source files" not in context["next_step"]
    assert not context["build_state"]["completion_ready"]
