"""Current-source presentation, separate from immutable engine reports."""

import json

from .builds import current_file_receipts


def summary(db, task_id, execution):
    result = execution.get("result") or {}
    office = result.get("document_validation") if isinstance(result, dict) else None
    if not isinstance(office, dict):
        return None
    current = current_file_receipts(db, task_id)
    outputs = {"receipts/" + a["path"]: a for a in current}
    output = outputs.get(office.get("output_path"))
    if not output or output["execution_id"] != execution["id"]:
        return "Historical document result. Current-source validation is unavailable."
    operation = office.get("operation")
    if operation == "recalculate":
        state = office.get("calculation_status")
        return (
            ("Recalculated." if state == "recalculated" else "Calculation has errors or changes.")
            + f" Formulas: {office.get('formula_count', 0)}."
            + f" Formula errors: {office.get('formula_error_count', 0)}."
            + f" Changed cells: {office.get('content_change_count', 0)}."
            + " Formatting preservation and visual layout are unverified."
            + " Read the report before using the exported workbook."
        )
    if operation == "extract-page":
        return (f"Rendered page {office.get('page', '?')} extracted. "
                "Extraction is not visual review.")
    if operation != "render":
        return None
    pages = {}
    for row in db.execute(
        "SELECT id,result FROM work_executions WHERE task_id=? AND status='completed'",
        (task_id,),
    ):
        child = json.loads(row["result"] or "{}").get("document_validation", {})
        if (
            child.get("operation") == "extract-page"
            and child.get("source_path") == office["output_path"]
            and child.get("source_sha256") == office["output_sha256"]
            and type(child.get("page")) is int
            and 1 <= child["page"] <= office["page_count"]
        ):
            saved = outputs.get(child.get("output_path"))
            if saved and saved["execution_id"] == row["id"]:
                pages[(child["output_path"], saved["sha256"])] = child["page"]
    reviewed = set()
    for row in db.execute(
        "SELECT action,result FROM work_steps WHERE task_id=? "
        "AND json_extract(action,'$.tool')='inspect_image'", (task_id,),
    ):
        action, inspection = json.loads(row["action"]), json.loads(row["result"])
        if inspection.get("error") or inspection.get("path") != action.get("path"):
            continue
        page = pages.get((inspection.get("path"), inspection.get("sha256")))
        if page and isinstance(inspection.get("brief"), str) and inspection["brief"].strip():
            reviewed.add(page)
    listed = ", ".join(map(str, sorted(reviewed))) or "none"
    return (
        f"Rendered {office['page_count']} pages. Limited structural findings: "
        f"{len(office.get('issues', []))}. Visual review recorded for pages: {listed} "
        f"({len(reviewed)}/{office['page_count']}). "
        "Read the image-review findings in recent activity; review coverage is not a layout pass. "
        "Fonts and Office compatibility may differ. Status reflects this receipt read."
    )
