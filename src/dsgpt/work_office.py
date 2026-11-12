"""Fixed office actions and independent binding of reports to collected bytes."""

import hashlib
import io
import json
import struct
import zipfile
import zlib

from .office_inspection import checked_entries, compare_workbooks
from .sandbox import SandboxError
from .storage import canonical

OFFICE_TOOLS = {"render_document", "recalculate_workbook", "extract_render_page"}
OPERATIONS = {
    "render_document": "render",
    "recalculate_workbook": "recalculate",
    "extract_render_page": "extract-page",
}


def png_dimensions(data, expected=None):
    """Validate bounded PNG framing/CRC without adding a host imaging dependency.

    Pixel decoding is performed by the isolated renderer. The host binds these
    original bytes to the manifest and checks dimensions and container integrity.
    """
    if not 45 <= len(data) <= 4 * 1024**2 or data[:16] != b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR":
        raise ValueError("office_png_invalid")
    width, height = struct.unpack(">II", data[16:24])
    if not 1 <= width <= 1600 or not 1 <= height <= 1600 or (
        expected is not None and (width, height) != expected
    ):
        raise ValueError("office_png_invalid")
    offset, pixels = 8, False
    while offset + 12 <= len(data):
        size = int.from_bytes(data[offset:offset + 4], "big")
        end = offset + 8 + size
        if end + 4 > len(data) or zlib.crc32(data[offset + 4:end]) != int.from_bytes(
            data[end:end + 4], "big"
        ):
            raise ValueError("office_png_invalid")
        kind = data[offset + 4:offset + 8]
        pixels |= kind == b"IDAT" and size > 0
        if kind == b"IEND":
            if size or end + 4 != len(data) or not pixels:
                raise ValueError("office_png_invalid")
            return width, height
        offset = end + 4
    raise ValueError("office_png_invalid")


def office_plan(action, assets):
    source = next((x for x in assets if x["path"] == action.path), None)
    if not source:
        raise SandboxError("office_saved_asset_required")
    operation = OPERATIONS[action.tool]
    suffix = {"render": ".zip", "recalculate": ".xlsx", "extract-page": ".png"}[operation]
    token = hashlib.sha256(
        canonical([operation, action.path, source["sha256"], action.page_number]).encode()
    ).hexdigest()[:24]
    name = "office/" + operation + "-" + token
    outputs = [name + suffix, name + ".json"]
    argv = ["/usr/bin/python3", "-I", "/opt/dsgpt/office_worker.py", operation, action.path]
    if operation == "extract-page":
        argv.append(str(action.page_number))
    return {
        "argv": argv + outputs,
        "artifacts": outputs,
        "timeout_seconds": 180,
        "source_sha256": source["sha256"],
        "source_content": source.get("content"),
        "operation": operation,
    }


def office_result(action, plan, artifacts):
    try:
        by_path = {a["path"]: a for a in artifacts}
        output, report_file = [by_path[p] for p in plan["artifacts"]]
        if len(report_file["content"]) > 4 * 1024**2:
            raise ValueError
        report = json.loads(report_file["content"])
        if (
            report["format"] != "dsgpt-office-v1"
            or report["operation"] != plan["operation"]
            or report["source_sha256"] != plan["source_sha256"]
            or report["output_sha256"] != hashlib.sha256(output["content"]).hexdigest()
            or report["output_sha256"] != output["sha256"]
        ):
            raise ValueError
        summary = {
            "operation": plan["operation"],
            "source_path": action.path,
            "source_sha256": plan["source_sha256"],
            "output_path": "receipts/" + output["path"],
            "output_sha256": report["output_sha256"],
            "report_path": "receipts/" + report_file["path"],
            "visual_review_status": "not_performed",
        }
        if plan["operation"] == "render":
            pages = report["pages"]
            if (
                type(report["page_count"]) is not int
                or not 1 <= len(pages) <= 20
                or len(pages) != report["page_count"]
                or report["rendered"] is not True
                or report["visually_reviewed_pages"] != []
            ):
                raise ValueError
            with zipfile.ZipFile(io.BytesIO(output["content"])) as archive:
                checked_entries(archive)
                if set(archive.namelist()) != {"document.pdf", "manifest.json"} | {
                    f"page-{i:03}.png" for i in range(1, len(pages) + 1)
                }:
                    raise ValueError
                embedded = json.loads(archive.read("manifest.json"))
                if embedded != {
                    k: v for k, v in report.items() if k not in {"output_sha256", "output_bytes"}
                }:
                    raise ValueError
                if hashlib.sha256(archive.read("document.pdf")).hexdigest() != report["pdf_sha256"]:
                    raise ValueError
                for index, page in enumerate(pages, 1):
                    if page["page"] != index or page["member"] != f"page-{index:03}.png":
                        raise ValueError
                    data = archive.read(page["member"])
                    if (
                        hashlib.sha256(data).hexdigest() != page["sha256"]
                        or len(data) != page["bytes"]
                        or not data.startswith(b"\x89PNG\r\n\x1a\n")
                    ):
                        raise ValueError
                    png_dimensions(data, (page["width"], page["height"]))
            summary.update(
                rendered=True,
                page_count=len(pages),
                issues=report["issues"][:20],
                next_action="extract_render_page then inspect_image for every page",
            )
        elif plan["operation"] == "recalculate":
            if report["calculate_all_called"] is not True:
                raise ValueError
            from .office_inspection import workbook_cells

            _, cells = workbook_cells(io.BytesIO(output["content"]))
            actual = [
                {"sheet": k[0], "cell": k[1], **v}
                for k, v in sorted(cells.items())
                if v["formula"] is not None
            ]
            if actual != report["exported_formula_cells"]:
                raise ValueError
            compared = compare_workbooks(
                io.BytesIO(plan["source_content"]), io.BytesIO(output["content"])
            )
            if any(report[k] != v for k, v in compared.items()):
                raise ValueError
            errors = sum(c["type"] == "e" for c in actual)
            status = (
                "errors_or_changes"
                if errors
                or report["formula_errors"]
                or compared["content_changes"]
                or not compared["sheet_names_preserved"]
                else "recalculated"
            )
            if (
                report["formula_count"] != len(actual)
                or report["exported_error_count"] != errors
                or report["calculation_status"] != status
            ):
                raise ValueError
            summary.update(
                calculation_status=report["calculation_status"],
                formula_count=report["formula_count"],
                formula_error_count=len(report["formula_errors"]),
                content_change_count=len(report["content_changes"]),
                formatting_preservation_verified=False,
            )
        else:
            if report["page"] != action.page_number:
                raise ValueError
            png_dimensions(output["content"])
            with zipfile.ZipFile(io.BytesIO(plan["source_content"])) as archive:
                checked_entries(archive)
                manifest = json.loads(archive.read("manifest.json"))
                page = manifest["pages"][action.page_number - 1]
                if (
                    manifest["operation"] != "render"
                    or page["page"] != action.page_number
                    or page["member"] != f"page-{action.page_number:03}.png"
                    or archive.read(page["member"]) != output["content"]
                    or page["sha256"] != report["output_sha256"]
                ):
                    raise ValueError
            summary["page"] = action.page_number
        return summary
    except (KeyError, TypeError, ValueError, zipfile.BadZipFile, IndexError) as exc:
        raise SandboxError("office_report_or_output_invalid") from exc
