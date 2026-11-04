import hashlib
import json

import pytest

from dsgpt.config import Model
from dsgpt.project_tools import ProjectAction, ProjectTools
from dsgpt.storage import Store, canonical
from dsgpt.work import WorkRegistry


@pytest.mark.parametrize("target", ["source", "exe"])
def test_work_sees_current_scoped_file_revisions_without_bodies_or_example_tasks(tmp_path, target):
    store = Store(tmp_path)
    model = Model("local", "Local", "ollama", "http://127.0.0.1:11434", "local")
    work = WorkRegistry(store, models={model.id: model})
    task = work.create("Repair", "Repair existing source", model.id, build_target=target)
    other = work.create("Other project", "Separate data", model.id)

    def write(task_id, path, content, expected=None):
        with store.transaction() as db:
            return ProjectTools.apply(
                db,
                task_id,
                ProjectAction(
                    tool="write_file",
                    path=path,
                    content=content,
                    expected_sha256=expected,
                    summary="Fixture source",
                ),
            )

    first = write(task["id"], "critical.py", "PRIVATE_FILE_BODY_1")
    foreign = write(other["id"], "foreign_secret.py", "OTHER_PROJECT_BODY")
    for index in range(12):
        write(task["id"], f"z{index:02d}_" + "a" * 190 + ".txt", "Additional source")

    def prompt():
        return work._prompt(task, task["session"], model, memories=[])

    messages = prompt()
    assert "notes.txt" not in messages[0]["content"]
    inventory = json.loads(messages[1]["content"])["project_files"]
    assert inventory["total"] == 13
    assert 0 < len(inventory["files"]) <= 10
    assert inventory["omitted"] == 13 - len(inventory["files"])
    assert sum(len(canonical(row).encode()) for row in inventory["files"]) <= 1500
    current = inventory["files"][0]
    assert current["path"] == "critical.py" and current["sha256"] == first["sha256"]
    assert current["revision"] == 1 and current["bytes"] == len("PRIVATE_FILE_BODY_1")
    serialized = canonical(messages)
    for excluded in [
        "PRIVATE_FILE_BODY_1",
        "OTHER_PROJECT_BODY",
        "foreign_secret.py",
        foreign["sha256"],
    ]:
        assert excluded not in serialized

    write(task["id"], "critical.py", "PRIVATE_FILE_BODY_2", first["sha256"])
    refreshed = json.loads(prompt()[1]["content"])["project_files"]["files"][0]
    assert refreshed["revision"] == 2
    assert refreshed["sha256"] == hashlib.sha256(b"PRIVATE_FILE_BODY_2").hexdigest()
