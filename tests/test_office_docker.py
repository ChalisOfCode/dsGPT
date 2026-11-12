"""Opt-in actual production-image engine checks with independent expected values."""

import hashlib
import io
import json
import os
import zipfile
from pathlib import Path

import pytest
from office_fixtures import document, slides, workbook
from test_work_asset_tools import setup

from dsgpt.office_inspection import workbook_cells
from dsgpt.project_tools import ProjectAction
from dsgpt.sandbox import DockerSandbox
from dsgpt.tool_setup import recipe_digest

pytestmark = pytest.mark.skipif(
    not os.environ.get("DSGPT_OFFICE_IMAGE"), reason="explicit production office image required"
)


@pytest.fixture
async def office_task(tmp_path):
    store, work, tid, _ = setup(tmp_path)
    owner = os.urandom(16).hex()
    sandbox = DockerSandbox(tmp_path, os.environ["DSGPT_OFFICE_IMAGE"], owner)
    work.builds.sandbox, work.builds.image = sandbox, os.environ["DSGPT_OFFICE_IMAGE"]
    info = json.loads(await sandbox.checked(["image", "inspect", work.builds.image]))[0]
    assert info["Config"]["Labels"]["org.dsgpt.recipe"] == recipe_digest()
    yield store, work, tid
    assert not (
        await sandbox.checked(
            [
                "container",
                "ls",
                "--all",
                "--filter",
                "label=org.dsgpt.owner=" + owner,
                "--format",
                "{{.Names}}",
            ]
        )
    ).strip()


async def execute(task, tool, name, body, step):
    store, work, tid = task
    with store.transaction() as db:
        db.execute(
            "INSERT INTO work_inputs VALUES(?,?,?,?,?)",
            (tid, name, body, hashlib.sha256(body).hexdigest(), "{}"),
        )
    result = await work.builds.execute(
        tid,
        step,
        ProjectAction(tool=tool, path="inputs/" + name, summary="Check controlled office specimen"),
    )
    assert "error" not in result, {
        "error": result.get("error"),
        "worker_code": result.get("stderr", "")[:160],
    }
    assert (
        store.one("SELECT original FROM work_inputs WHERE task_id=? AND name=?", (tid, name))[
            "original"
        ]
        == body
    )
    saved = {
        a["path"]: bytes(
            store.one("SELECT content FROM work_artifacts WHERE id=?", (a["id"],))["content"]
        )
        for a in result["artifacts"]
    }
    destination = Path(os.environ["DSGPT_OFFICE_EVIDENCE"])
    destination.mkdir(parents=True, exist_ok=True)
    for path, content in saved.items():
        (destination / Path(path).name).write_bytes(content)
    return result, saved


async def test_real_calc_replaces_wrong_caches_and_reports_errors(office_task):
    for step, errors in enumerate((False, True), 1):
        result, saved = await execute(
            office_task, "recalculate_workbook", f"book{step}.xlsx", workbook(errors=errors), step
        )
        body = next(v for k, v in saved.items() if k.endswith(".xlsx"))
        report = json.loads(next(v for k, v in saved.items() if k.endswith(".json")))
        _, cells = workbook_cells(io.BytesIO(body))
        # Independent constants, not copied from the engine report.
        assert cells[("Values", "B1")]["value"] == "21"
        assert cells[("Values", "B2")]["value"] == "23"
        assert cells[("Values", "B3")]["value"] == "你好 world"
        assert cells[("Values", "B4")]["value"] == "45293"
        assert report["calculate_all_called"] and not report["content_changes"]
        assert report["sheet_names_preserved"]
        if errors:
            assert cells[("Values", "B5")]["type"] == "e"
            assert cells[("Values", "B6")]["type"] == "e"
            assert report["exported_error_count"] == len(report["formula_errors"]) == 2
            assert result["document_validation"]["calculation_status"] == "errors_or_changes"
        else:
            assert result["document_validation"]["calculation_status"] == "recalculated"


async def test_real_writer_impress_and_pdf_pages(office_task):
    for step, (name, body) in enumerate(
        (("report.docx", document()), ("slides.pptx", slides())), 1
    ):
        result, saved = await execute(office_task, "render_document", name, body, step)
        assert result["document_validation"]["page_count"] == 2
        report = json.loads(next(v for k, v in saved.items() if k.endswith(".json")))
        assert report["visual_review_status"] == "not_performed"
        assert report["visually_reviewed_pages"] == []
        if name.endswith(".pptx"):
            assert any(x["kind"] == "outside_slide_canvas" for x in report["issues"])
        else:
            with zipfile.ZipFile(
                io.BytesIO(next(v for k, v in saved.items() if k.endswith(".zip")))
            ) as z:
                pdf = z.read("document.pdf")
        store, work, tid = office_task
        extracted = await work.builds.execute(
            tid,
            step + 10,
            ProjectAction(
                tool="extract_render_page",
                path=result["document_validation"]["output_path"],
                page_number=2,
                summary="Expose checked page for visual review",
            ),
        )
        assert "error" not in extracted
    rendered, _ = await execute(office_task, "render_document", "original.pdf", pdf, 20)
    assert rendered["document_validation"]["page_count"] == 2
