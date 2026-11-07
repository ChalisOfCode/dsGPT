"""New-file actions cannot select paths that guided execution always rejects."""

import itertools
import re

import pytest
from test_work_inline_original import Inference, setup, step

from dsgpt.project_tools import ProjectAction, ProjectTools, action_schema, new_file_path_pattern


def variant(schema, tool):
    return next(v for v in schema["oneOf"] if v["properties"]["tool"]["const"] == tool)


def test_existing_paths_excluded_but_neighbors_and_unicode_remain_available():
    existing = ["src/Task.kt", "src/Task.kt.bak", "src/Task(2)[x]-$.kt", "雪/é.kt"]
    schema = action_schema(specification=True, file_paths=existing)
    rule = variant(schema, "write_file")["properties"]["path"]
    pattern = re.compile(rule["pattern"])
    assert rule["minLength"] == 1 and rule["maxLength"] == 240
    for path in existing:
        assert pattern.fullmatch(path) is None
        for neighbor in [path + "x", path[:-1], "new/" + path, path.swapcase()]:
            if neighbor not in existing:
                assert pattern.fullmatch(neighbor), neighbor
    assert variant(schema, "edit_file")["properties"]["path"]["enum"] == existing
    assert variant(schema, "read_file")["properties"]["path"]["enum"] == existing


def test_trie_complement_exhaustively_preserves_other_short_strings():
    existing = ["a", "ab", "aba", "bb", "bba"]
    pattern = re.compile(new_file_path_pattern(existing))
    for length in range(6):
        for chars in itertools.product("abc", repeat=length):
            value = "".join(chars)
            assert bool(pattern.fullmatch(value)) == (bool(value) and value not in existing)


def test_pattern_enforces_path_length_without_relying_on_schema_siblings():
    existing = ["a" * 240, "b" * 239]
    pattern = re.compile(new_file_path_pattern(existing))
    for path in ["", "c" * 241, *existing]:
        assert not pattern.fullmatch(path)
    for path in ["a" * 239, "a" * 239 + "b", "b" * 240, "c" * 240]:
        assert pattern.fullmatch(path)


def test_scaffold_paths_do_not_repeat_expanded_grammar_subtrees():
    package = "android/app/src/main/java/com/example/" + "p" + "a" * 32
    existing = ["android/settings.gradle", "android/build.gradle",
                "android/gradle.properties", "android/app/build.gradle",
                "android/app/src/main/AndroidManifest.xml",
                package + "/MainActivity.kt", "android/README.md"]
    pattern = new_file_path_pattern(existing)
    # The runtime expands a group's rules before applying its repetition. Even
    # a single optional repetition can exceed its complexity guard after schema
    # conversion. Repeat individual characters, never the expanded path subtree.
    assert not re.search(r"\)[?*+{]", pattern)
    compiled = re.compile(pattern)
    for path in existing:
        assert not compiled.fullmatch(path)
        for length in range(1, len(path)):
            prefix = path[:length]
            assert bool(compiled.fullmatch(prefix)) == (prefix not in existing)
        assert compiled.fullmatch(path + ".new")
    assert compiled.fullmatch(package + "/TaskLedger.kt")


@pytest.mark.parametrize("specification,paths", [(False, ["old.py"]), (True, []), (True, None)])
def test_unguided_or_missing_inventory_does_not_gain_exclusions(specification, paths):
    prop = variant(action_schema(specification=specification, file_paths=paths), "write_file")
    assert "pattern" not in prop["properties"]["path"]


async def test_controller_refreshes_creation_grammar_without_weakening_runtime(tmp_path):
    store, work, tid = setup(tmp_path)
    work.inference = Inference()
    await step(work, tid)
    work.inference = Inference({"tool": "write_file", "path": "other.txt",
                               "content": "new", "summary": "Create a distinct module"})
    await step(work, tid)
    schema = work.inference.calls[0][1]
    rule = variant(schema, "write_file")["properties"]["path"]["pattern"]
    assert not re.fullmatch(rule, "notes.txt")
    assert re.fullmatch(rule, "other.txt")
    original = store.one("SELECT content FROM work_files WHERE task_id=? AND path='notes.txt'",
                         (tid,))["content"]
    # A nonconforming runtime response is still rejected by the transaction.
    work.inference = Inference({"tool": "write_file", "path": "notes.txt",
                               "content": "overwrite", "summary": "Rejected overwrite"})
    await step(work, tid)
    assert store.one("SELECT content FROM work_files WHERE task_id=? AND path='notes.txt'",
                     (tid,))["content"] == original
    # The existing targeted edit contract still applies with its current hash.
    row = store.one("SELECT * FROM work_files WHERE task_id=? AND path='notes.txt'", (tid,))
    with store.transaction() as db:
        result = ProjectTools.apply(db, tid, ProjectAction(tool="edit_file", path="notes.txt",
            old_text=original, new_text="changed", expected_sha256=row["sha256"], summary="Edit"))
    assert "error" not in result
