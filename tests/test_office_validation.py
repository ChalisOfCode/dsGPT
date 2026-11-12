"""Bounded parser/orchestration checks; engine acceptance runs separately in Docker."""

import asyncio
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


@pytest.mark.parametrize(
    "tool,name", [("render_document", "book.pdf"), ("recalculate_workbook", "book.xlsx")]
)
async def test_interrupted_office_never_exports_or_replays_and_cleanup_failure_blocks(
    tmp_path, tool, name,
):
    entered = asyncio.Event()

    class Interrupted(OfficeFixture):
        calls = 0
        fail_cleanup = True

        async def execute(self, *args, **kwargs):
            self.calls += 1
            entered.set()
            await asyncio.Event().wait()

        async def cleanup(self, identifier):
            if self.fail_cleanup:
                raise SandboxError("controlled_cleanup_failure")

    sandbox = Interrupted()
    store, work, tid, _ = setup(tmp_path, sandbox=sandbox)
    original = workbook() if name.endswith("xlsx") else b"%PDF-1.7 controlled interruption"
    with store.transaction() as db:
        db.execute("INSERT INTO work_inputs VALUES(?,?,?,?,?)", (
            tid, name, original, hashlib.sha256(original).hexdigest(), "{}",
        ))
    running = asyncio.create_task(
        work.builds.execute(tid, 1, action(tool=tool, path="inputs/" + name))
    )
    await asyncio.wait_for(entered.wait(), 2)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert not work.builds.ready
    assert not store.all("SELECT * FROM work_artifacts")
    await work.builds.recover()
    assert not work.builds.ready and work.builds.status()["cleanup_pending"] == 1
    sandbox.fail_cleanup = False
    await work.builds.recover()
    pending_action, result = work.builds.pending(tid, 1)
    assert pending_action["tool"] == tool
    assert result.get("error") and not result.get("document_validation")
    assert not result.get("artifacts") and sandbox.calls == 1
    retained = store.one(
        "SELECT original FROM work_inputs WHERE task_id=? AND name=?", (tid, name)
    )
    assert bytes(retained["original"]) == original


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


def test_host_png_checks_need_no_imaging_dependency():
    import zipfile

    from office_fixtures import document

    from dsgpt.work_office import png_dimensions

    with zipfile.ZipFile(io.BytesIO(document())) as archive:
        body = archive.read("word/media/square.png")
    assert png_dimensions(body) == (32, 32)
    for bad in (body[:-1], body + b"extra", body[:40] + b"bad" + body[43:]):
        with pytest.raises(ValueError, match="office_png_invalid"):
            png_dimensions(bad)
    with pytest.raises(ValueError, match="office_png_invalid"):
        png_dimensions(body, (100, 100))


async def test_receipt_summary_distinguishes_coverage_and_stale_evidence(tmp_path):
    from dsgpt.office_evidence import summary
    from dsgpt.storage import canonical, utcnow

    store, work, tid, _ = setup(tmp_path, sandbox=OfficeFixture())
    original = workbook()
    with store.transaction() as db:
        db.execute("INSERT INTO work_inputs VALUES(?,?,?,?,?)", (
            tid, "book.xlsx", original, hashlib.sha256(original).hexdigest(), "{}",
        ))
    parent = await work.builds.execute(tid, 1, action())
    row = {"id": parent["execution_id"], "result": parent}
    with store.connect() as db:
        assert "Recalculated. Formulas: 4" in summary(db, tid, row)
        assert "visual layout are unverified" in summary(db, tid, row)
    child = await work.builds.execute(
        tid, 2, action(path=parent["document_validation"]["output_path"])
    )
    # Projection-only fixture: no image review or real render is claimed by this test.
    parent["document_validation"].update(operation="render", page_count=2, issues=[])
    child["document_validation"].update(operation="extract-page", page=1)
    with store.transaction() as db:
        for result in (parent, child):
            db.execute("UPDATE work_executions SET result=? WHERE id=?", (
                canonical(result), result["execution_id"],
            ))
        assert "none (0/2)" in summary(db, tid, row)
        path = child["document_validation"]["output_path"]
        review = {"path": path, "sha256": "f" * 64, "brief": "Readable, possible clipping"}
        db.execute("INSERT INTO work_steps VALUES(?,?,?,?,?)", (
            tid, 3, canonical({"tool": "inspect_image", "path": path}), canonical(review), utcnow(),
        ))
        assert "none (0/2)" in summary(db, tid, row)
        review["sha256"] = child["document_validation"]["output_sha256"]
        db.execute("UPDATE work_steps SET result=? WHERE task_id=?", (canonical(review), tid))
        assert "pages: 1 (1/2)" in summary(db, tid, row)
        assert "not a layout pass" in summary(db, tid, row)
        db.execute("UPDATE work_inputs SET sha256=? WHERE task_id=?", ("0" * 64, tid))
        assert summary(db, tid, row).startswith("Historical document result")
