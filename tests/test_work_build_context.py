import json

from dsgpt.builds import snapshot_hash
from dsgpt.config import Model
from dsgpt.project_tools import ProjectAction, ProjectTools
from dsgpt.storage import Store, canonical, utcnow
from dsgpt.work import WorkRegistry


def test_build_context_keeps_failure_and_complete_current_sources_after_history_rolls(tmp_path):
    store = Store(tmp_path)
    model = Model("local", "Local", "ollama", "http://127.0.0.1:11434", "local")
    work = WorkRegistry(store, models={model.id: model})
    task = work.create("Repair", "Build existing source", model.id, build_target="exe")
    other = work.create("Private", "Other task")
    with store.transaction() as db:
        for task_id, path, body in [
            (task["id"], "main.c", "#include <stdio.h>\nint main() { return 0; }\n"),
            (task["id"], "large.c", "LARGE_BODY" * 1000),
            (other["id"], "private.c", "FOREIGN_SECRET"),
        ]:
            ProjectTools.apply(
                db,
                task_id,
                ProjectAction(tool="write_file", path=path, content=body, summary="Fixture"),
            )
        files = [
            dict(r)
            for r in db.execute(
                "SELECT path,sha256 FROM work_files WHERE task_id=? ORDER BY path", (task["id"],)
            )
        ]
        db.execute(
            "INSERT INTO work_executions(id,task_id,step,action,snapshot_sha256,status,result,"
            "cleanup_pending,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                "execution",
                task["id"],
                1,
                "{}",
                snapshot_hash(files),
                "failed",
                canonical({"stderr": "compiler failure", "exit_code": 1}),
                0,
                utcnow(),
                utcnow(),
            ),
        )
        for step in [2, 3]:
            db.execute(
                "INSERT INTO work_steps VALUES(?,?,?,?,?)",
                (task["id"], step, '{"tool":"list_files"}', "{}", utcnow()),
            )

    def state():
        messages = work._prompt(task, task["session"], model, memories=[])
        serialized = canonical(messages)
        assert "FOREIGN_SECRET" not in serialized and "LARGE_BODY" not in serialized
        return json.loads(messages[-1]["content"].split(": ", 1)[1].split("\nChoose")[0])

    current = state()
    assert current["finish_ready"] is False
    assert current["sources_changed_since_execution"] is False
    assert current["latest_execution"]["applies_to_current_sources"] is True
    assert current["latest_execution"]["result"]["stderr"] == "compiler failure"
    bodies = current["complete_current_files"]
    assert len(bodies) == 1 and bodies[0]["content"].startswith("#include")
    assert bodies[0]["content"].endswith("return 0; }\n")
    with store.transaction() as db:
        db.execute(
            "UPDATE work_executions SET status=?,result=? WHERE id=?",
            (
                "completed",
                canonical({"artifacts": [{"kind": "exe", "id": "artifact"}]}),
                "execution",
            ),
        )
    assert state()["finish_ready"] is True
    with store.transaction() as db:
        ProjectTools.apply(
            db,
            task["id"],
            ProjectAction(
                tool="write_file",
                path="main.c",
                content="int main() { return 1; }",
                expected_sha256=bodies[0]["sha256"],
                summary="Changed sources",
            ),
        )
    assert state()["finish_ready"] is False
    assert state()["sources_changed_since_execution"] is True
    assert state()["latest_execution"]["applies_to_current_sources"] is False
    messages = work._prompt(task, task["session"], model, memories=[])
    assert "Do not repeat an already completed write" in messages[-1]["content"]


def test_compiler_repair_removes_duplicate_log_before_context_guard(tmp_path):
    from dsgpt.inference import ollama_input_estimate

    store = Store(tmp_path)
    model = Model("local", "Local", "ollama", "http://127.0.0.1:11434", "local")
    work = WorkRegistry(store, models={model.id: model})
    requirements = (
        "Repair and compile existing hello.c, first compiling unchanged to observe its error. "
        'Every compile must use ["sh","-c","sleep 45; '
        'x86_64-w64-mingw32-gcc hello.c -o hello.exe"] '
        'and artifacts ["hello.exe"]. Correct the missing semicolon using the current hash. '
        "Preserve DSGPT_ACCEPTANCE_BUILD. Finish after collecting the EXE."
    )
    task = work.create("Repair", requirements, model.id, build_target="exe")
    source = '#include <stdio.h>\nint main(void){puts("DSGPT_ACCEPTANCE_BUILD") return 0;}\n'
    failure = {
        "execution_id": "execution",
        "exit_code": 1,
        "stderr": "hello.c:2:57: error: expected semicolon before return\n" + source * 12,
        "stdout": "",
        "status": "failed",
        "artifacts": [],
    }
    action = ProjectAction(
        tool="run",
        argv=["sh", "-c", "sleep 45; x86_64-w64-mingw32-gcc hello.c -o hello.exe"],
        artifacts=["hello.exe"],
        summary="Compile unchanged first; repair the actual error next.",
    )
    with store.transaction() as db:
        ProjectTools.apply(
            db,
            task["id"],
            ProjectAction(tool="write_file", path="hello.c", content=source, summary="Fixture"),
        )
        files = [
            dict(r)
            for r in db.execute("SELECT path,sha256 FROM work_files WHERE task_id=?", (task["id"],))
        ]
        db.execute(
            "INSERT INTO work_executions(id,task_id,step,action,snapshot_sha256,status,result,"
            "cleanup_pending,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                "execution",
                task["id"],
                2,
                canonical(action.model_dump()),
                snapshot_hash(files),
                "failed",
                canonical(failure),
                0,
                utcnow(),
                utcnow(),
            ),
        )
        for step, definition, result in [
            (1, {"tool": "list_files"}, {"files": files}),
            (2, action.model_dump(), failure),
        ]:
            db.execute(
                "INSERT INTO work_steps VALUES(?,?,?,?,?)",
                (task["id"], step, canonical(definition), canonical(result), utcnow()),
            )
    messages = work._prompt(task, task["session"], model, memories=["optional memory" * 100])
    assert ollama_input_estimate(messages) + model.output_tokens <= model.context
    assert json.loads(messages[1]["content"])["requirements"] == requirements
    state = json.loads(messages[-1]["content"].split(": ", 1)[1].split("\nChoose")[0])
    assert state["latest_execution"]["result"]["exit_code"] == 1
    assert "expected semicolon" in state["latest_execution"]["result"]["stderr"]
    assert state["complete_current_files"][0]["content"] == source
    assert state["complete_current_files"][0]["sha256"] == files[0]["sha256"]
    assert not state["finish_ready"]
