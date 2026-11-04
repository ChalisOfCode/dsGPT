"""A source/log page must stop at EOF without losing UTF-8 boundary characters."""

import hashlib
import json
import sqlite3

import pytest

from dsgpt.project_tools import ProjectAction, ProjectTools


@pytest.fixture
def database():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(
        "CREATE TABLE work_files(task_id,path,content,sha256);"
        "CREATE TABLE work_executions(id,task_id,result);"
    )
    yield db
    db.close()


def reader(db, tool, original):
    task_id = "task"
    if tool == "read_file":
        db.execute(
            "INSERT INTO work_files VALUES(?,?,?,?)",
            (task_id, "source.txt", original, hashlib.sha256(original.encode()).hexdigest()),
        )
        arguments = {"path": "source.txt"}
    else:
        identifier = "00000000-0000-0000-0000-000000000001"
        db.execute("INSERT INTO work_executions VALUES(?,?,?)", (identifier, task_id, original))
        arguments = {"execution_id": identifier}

    def read(offset=0, task=task_id):
        return ProjectTools.apply(
            db,
            task,
            ProjectAction(tool=tool, summary="Read saved content", offset=offset, **arguments),
        )

    return read


@pytest.mark.parametrize("tool", ["read_file", "read_build_log"])
@pytest.mark.parametrize(
    "original",
    [
        "",
        "Short complete text",
        "a" * 3000,
        "a" * 2999 + "🙂 final",
        "á🙂日本語\n" * 900,
        json.dumps({"stdout": "Compiler: café 🏁\n" * 800}, ensure_ascii=False),
    ],
)
def test_complete_source_or_log_paging_terminates_losslessly(database, tool, original):
    read = reader(database, tool, original)
    offset, pages = 0, []
    for _ in range(len(original.encode()) // 2997 + 2):
        page = read(offset)
        assert page["offset"] == offset
        assert page["total_characters"] == len(original)
        assert len(page["content"].encode()) <= 3000
        pages.append(page["content"])
        if page["next_offset"] is None:
            assert page["has_more"] is False
            assert offset + len(page["content"]) >= len(original)
            break
        assert page["has_more"] is True
        assert offset < page["next_offset"] < len(original)
        offset = page["next_offset"]
    else:
        pytest.fail("Source/log paging did not terminate")
    assert "".join(pages) == original

    for end in (len(original), len(original) + 25):
        page = read(end)
        assert page["content"] == ""
        assert page["next_offset"] is None
        assert page["has_more"] is False
        assert page["total_characters"] == len(original)


@pytest.mark.parametrize("tool", ["read_file", "read_build_log"])
def test_paging_cannot_read_another_tasks_content(database, tool):
    read = reader(database, tool, "private task file")
    result = read(task="another-task")
    assert result == {"error": "file_not_found" if tool == "read_file" else "execution_not_found"}
