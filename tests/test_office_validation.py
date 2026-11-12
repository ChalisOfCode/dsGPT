"""Bounded parser/orchestration checks; engine acceptance runs separately in Docker."""

import hashlib
import io
import json

import pytest
from office_fixtures import packed, workbook
from pydantic import ValidationError
from test_work_asset_tools import setup

from dsgpt import office_worker, work_assets
from dsgpt.office_inspection import compare_workbooks, inspect_package, workbook_cells
from dsgpt.project_tools import ProjectAction, action_schema
from dsgpt.sandbox import SandboxError
from dsgpt.work_office import office_plan, office_result


def action(**values):
    return ProjectAction(
        **{
            "tool": "recalculate_workbook",
            "path": "inputs/book.xlsx",
            "summary": "Recalculate",
            **values,
        }
    )


def test_actions_are_scoped_and_not_command_overrides():
    variants = action_schema(isolated_execution=True, asset_paths=["inputs/book.xlsx"])["oneOf"]
    by_name = {v["properties"]["tool"]["const"]: v for v in variants}
    assert by_name["recalculate_workbook"]["properties"]["path"] == {"enum": ["inputs/book.xlsx"]}
    for values in (
        {"path": "../other.xlsx"},
        {"path": "book.xlsx"},
        {"argv": ["anything"]},
        {"timeout_seconds": 900},
        {"page_number": 2},
    ):
        with pytest.raises(ValidationError):
            action(**values)
    for number in (0, 21):
        with pytest.raises(ValidationError):
            action(tool="extract_render_page", page_number=number)


def test_independent_formula_cache_and_content_comparison():
    original = workbook()
    _, before = workbook_cells(io.BytesIO(original))
    assert before[("Values", "B1")]["value"] == "999"
    report = compare_workbooks(io.BytesIO(original), io.BytesIO(workbook(cached="21")))
    assert report["sheet_names_preserved"] and not report["content_changes"]
    assert len(report["exported_formula_cells"]) == 4
    assert report["exported_formula_cells"][0]["value"] == "21"
    assert not report["formatting_preservation_verified"]


def test_active_content_traversal_duplicate_and_entities_rejected():
    for content in (
        workbook(unsafe=True),
        packed({"../outside": "x"}),
        packed({"A.xml": "<a/>", "a.xml": "<b/>"}),
        packed({"a.xml": '<!DOCTYPE a [<!ENTITY x "secret">]><a>&x;</a>'}),
    ):
        with pytest.raises(ValueError):
            inspect_package(io.BytesIO(content))


def test_no_overwrite_or_symlink_and_size_guards(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "existing").write_bytes(b"original")
    with pytest.raises(ValueError, match="already_exists"):
        office_worker.safe_file("existing", output=True)
    with pytest.raises(ValueError, match="invalid"):
        office_worker.safe_file("../outside", output=True)
    (tmp_path / "link").symlink_to(tmp_path / "existing")
    with pytest.raises(ValueError, match="invalid"):
        office_worker.safe_file("link")
    assert (tmp_path / "existing").read_bytes() == b"original"


class OfficeFixture:
    """No real calculation: generated receipt data exercises host validation only."""

    async def cleanup(self, identifier):
        pass

    async def execute(self, identifier, files, argv, artifacts, timeout, **kwargs):
        source = next(x for x in files if x["path"] == argv[4])
        output = workbook(cached="21")
        report = {
            "format": "dsgpt-office-v1",
            "operation": "recalculate",
            "source_sha256": source["sha256"],
            "output_sha256": hashlib.sha256(output).hexdigest(),
            "calculate_all_called": True,
            "formula_count": 4,
            "formula_errors": [],
            "exported_error_count": 0,
            "calculation_status": "recalculated",
            **compare_workbooks(io.BytesIO(source["content"]), io.BytesIO(output)),
        }
        return {
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
            "artifacts": [
                {"path": p, "content": b, "sha256": hashlib.sha256(b).hexdigest()}
                for p, b in zip(artifacts, [output, json.dumps(report).encode()], strict=True)
            ],
        }


async def test_saved_hash_binding_and_stale_source_invalidates_receipts(tmp_path):
    store, work, tid, _ = setup(tmp_path, sandbox=OfficeFixture())
    original = workbook()
    with store.transaction() as db:
        db.execute(
            "INSERT INTO work_inputs VALUES(?,?,?,?,?)",
            (tid, "book.xlsx", original, hashlib.sha256(original).hexdigest(), "{}"),
        )
    result = await work.builds.execute(tid, 1, action())
    assert "error" not in result
    assert result["document_validation"]["visual_review_status"] == "not_performed"
    dependent = await work.builds.execute(
        tid, 2, action(path=result["document_validation"]["output_path"])
    )
    assert "error" not in dependent
    with store.transaction() as db:
        assert len(work_assets.inventory(db, tid)["receipts"]) == 4
        changed = workbook(cached="123")
        db.execute(
            "UPDATE work_inputs SET original=?,sha256=? WHERE task_id=? AND name=?",
            (changed, hashlib.sha256(changed).hexdigest(), tid, "book.xlsx"),
        )
        assert work_assets.inventory(db, tid)["receipts"] == []


def test_tampered_collected_output_cannot_validate():
    source = workbook()
    plan = office_plan(
        action(), [{"path": "inputs/book.xlsx", "sha256": hashlib.sha256(source).hexdigest()}]
    )
    with pytest.raises(SandboxError, match="invalid"):
        office_result(action(), plan, [])
    replacement = office_plan(action(), [{"path": "inputs/book.xlsx", "sha256": "f" * 64}])
    assert plan["artifacts"] != replacement["artifacts"]
