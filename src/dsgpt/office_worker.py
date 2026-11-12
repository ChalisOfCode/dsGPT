"""Trusted bounded office tools, executed only in the owned networkless tool container.

No conversion or structural check is labeled visual verification. Engine failures
produce no committed report. Originals are never used as output paths.
"""

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from pathlib import Path

if __package__:
    from .office_inspection import (
        INPUT_LIMIT,
        checked_entries,
        compare_workbooks,
        inspect_package,
        slide_issues,
    )
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from office_inspection import (
        INPUT_LIMIT,
        checked_entries,
        compare_workbooks,
        inspect_package,
        slide_issues,
    )

PAGES = 20
OUTPUT_LIMIT = 64 * 1024**2


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def safe_file(raw, *, output=False, limit=INPUT_LIMIT):
    root = Path.cwd().resolve()
    path = Path(raw)
    if (
        path.is_absolute()
        or not path.parts
        or ".." in path.parts
        or any(p.is_symlink() for p in [path, *path.parents])
    ):
        raise ValueError("office_path_invalid")
    resolved = path.resolve()
    if resolved == root or not resolved.is_relative_to(root):
        raise ValueError("office_path_invalid")
    if output:
        if path.exists():
            raise ValueError("office_output_already_exists")
        path.parent.mkdir(parents=True, exist_ok=True)
    elif not path.is_file() or not 0 < path.stat().st_size <= limit:
        raise ValueError("office_input_limit")
    return resolved


def run(argv, timeout=60):
    result = subprocess.run(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=timeout,
        check=True,
        env={**os.environ, "LC_ALL": "C.UTF-8"},
    )
    if len(result.stdout) > 1024**2:
        raise ValueError("office_command_output_limit")
    return result.stdout.decode("utf-8", "strict")


def properties(**values):
    import uno

    result = []
    for name, value in values.items():
        item = uno.createUnoStruct("com.sun.star.beans.PropertyValue")
        item.Name, item.Value = name, value
        result.append(item)
    return tuple(result)


@contextlib.contextmanager
def office(directory):
    import uno

    endpoint = "pipe,name=dsgpt_" + uuid.uuid4().hex
    profile = directory / "profile"
    process = subprocess.Popen(
        [
            "/usr/bin/libreoffice",
            "-env:UserInstallation=" + profile.as_uri(),
            "--headless",
            "--nologo",
            "--nodefault",
            "--norestore",
            "--nofirststartwizard",
            "--accept=" + endpoint + ";urp;StarOffice.ComponentContext",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    desktop = None
    try:
        local = uno.getComponentContext()
        resolver = local.ServiceManager.createInstanceWithContext(
            "com.sun.star.bridge.UnoUrlResolver", local
        )
        until = time.monotonic() + 15
        while True:
            try:
                context = resolver.resolve("uno:" + endpoint + ";urp;StarOffice.ComponentContext")
                break
            except Exception:
                if process.poll() is not None or time.monotonic() >= until:
                    raise ValueError("office_start_failed") from None
                time.sleep(0.1)
        desktop = context.ServiceManager.createInstanceWithContext(
            "com.sun.star.frame.Desktop", context
        )
        yield desktop
    finally:
        if desktop is not None:
            with contextlib.suppress(Exception):
                desktop.terminate()
        if process.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)


def load(desktop, path):
    doc = desktop.loadComponentFromURL(
        path.as_uri(),
        "_blank",
        0,
        properties(
            Hidden=True,
            ReadOnly=True,
            MacroExecutionMode=0,
            UpdateDocMode=0,
            PickListEntry=False,
            RepairPackage=False,
        ),
    )
    if doc is None:
        raise ValueError("office_document_load_failed")
    return doc


def engine(source, destination, directory, mode):
    """Called in a separately timed worker, so a stuck UNO call cannot hang forever."""
    with office(directory) as desktop:
        doc = load(desktop, source)
        try:
            if mode == "recalculate":
                if not doc.supportsService("com.sun.star.sheet.SpreadsheetDocument"):
                    raise ValueError("workbook_required")
                doc.enableAutomaticCalculation(False)
                doc.calculateAll()
                errors, formula_count = [], 0
                sheets = doc.getSheets()
                for index in range(sheets.getCount()):
                    sheet = sheets.getByIndex(index)
                    for region in sheet.queryContentCells(16).getRangeAddresses():
                        size = (region.EndColumn - region.StartColumn + 1) * (
                            region.EndRow - region.StartRow + 1
                        )
                        if formula_count + size > 20000:
                            raise ValueError("workbook_formula_limit")
                        for row in range(region.StartRow, region.EndRow + 1):
                            for column in range(region.StartColumn, region.EndColumn + 1):
                                cell = sheet.getCellByPosition(column, row)
                                formula_count += 1
                                if cell.getError():
                                    errors.append(
                                        {
                                            "sheet": sheet.Name,
                                            "row": row + 1,
                                            "column": column + 1,
                                            "error": cell.getError(),
                                        }
                                    )
                doc.storeToURL(
                    destination.as_uri(),
                    properties(FilterName="Calc MS Excel 2007 XML", Overwrite=False),
                )
                (directory / "engine.json").write_text(
                    json.dumps(
                        {
                            "calculate_all_called": True,
                            "formula_count": formula_count,
                            "formula_errors": errors,
                        }
                    ),
                    encoding="utf-8",
                )
            else:
                filters = {".docx": "writer_pdf_Export", ".pptx": "impress_pdf_Export"}
                doc.storeToURL(
                    destination.as_uri(),
                    properties(FilterName=filters[source.suffix.lower()], Overwrite=False),
                )
        finally:
            doc.close(True)


def convert(source, destination, directory, mode):
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            str(Path(__file__).resolve()),
            "engine",
            mode,
            str(source),
            str(destination),
            str(directory),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=90,
    )
    if result.returncode:
        code = result.stderr.decode("ascii", "replace").strip()
        if not re.fullmatch(r"(?:office|workbook)_[a-z_]{1,70}", code):
            code = "office_engine_failed"
        raise ValueError(code)


def render(source, directory):
    from PIL import Image, ImageStat

    pdf = directory / "document.pdf"
    if source.suffix.lower() == ".pdf":
        shutil.copyfile(source, pdf)
    else:
        convert(source, pdf, directory, "render")
    info = run(["pdfinfo", str(pdf)])
    count = re.search(r"^Pages:\s+(\d+)\s*$", info, re.M)
    if not count or not 1 <= int(count[1]) <= PAGES:
        raise ValueError("office_page_limit")
    if re.search(r"^Encrypted:\s+yes", info, re.M):
        raise ValueError("office_encrypted_pdf_unsupported")
    count = int(count[1])
    pages, issues = [], []
    for number in range(1, count + 1):
        name = f"page-{number:03}.png"
        # Every page, with bounded raster dimensions suitable for image inspection.
        run(
            [
                "pdftoppm",
                "-f",
                str(number),
                "-l",
                str(number),
                "-singlefile",
                "-png",
                "-scale-to",
                "1600",
                str(pdf),
                str(directory / name.removesuffix(".png")),
            ]
        )
        path = directory / name
        with Image.open(path) as image:
            width, height = image.size
            if (
                min(width, height) < 1
                or max(width, height) > 1600
                or path.stat().st_size > 4 * 1024**2
            ):
                raise ValueError("office_page_geometry_invalid")
            if ImageStat.Stat(image.convert("L")).var[0] < 0.1:
                issues.append({"page": number, "kind": "possibly_blank"})
        pages.append(
            {
                "page": number,
                "member": name,
                "width": width,
                "height": height,
                "sha256": digest(path),
                "bytes": path.stat().st_size,
            }
        )
    return {
        "rendered": True,
        "page_count": count,
        "pages": pages,
        "structural_checks_completed": ["page_count", "raster_geometry", "blank_page_probe"],
        "issues": issues,
        "visually_reviewed_pages": [],
        "visual_review_status": "not_performed",
        "pdf_sha256": digest(pdf),
    }


def validate(mode, raw_source, raw_output, raw_report):
    source = safe_file(raw_source)
    output, report_path = safe_file(raw_output, output=True), safe_file(raw_report, output=True)
    if len({source, output, report_path}) != 3:
        raise ValueError("office_output_conflict")
    suffix = source.suffix.lower()
    if suffix not in ({".xlsx"} if mode == "recalculate" else {".pdf", ".docx", ".pptx"}):
        raise ValueError("office_format_unsupported")
    before = digest(source)
    if suffix != ".pdf":
        inspect_package(source)
    with tempfile.TemporaryDirectory(prefix=".dsgpt-office-", dir=Path.cwd()) as temp:
        directory = Path(temp)
        copied = directory / ("input" + suffix)
        shutil.copyfile(source, copied)
        fonts = sorted(set(run(["fc-list", "--format=%{family}\t%{style}\n"]).splitlines()))
        report = {
            "format": "dsgpt-office-v1",
            "operation": mode,
            "source_sha256": before,
            "source_bytes": source.stat().st_size,
            "engine": run(["/usr/bin/libreoffice", "--version"]).strip(),
            "font_inventory_sha256": hashlib.sha256("\n".join(fonts).encode()).hexdigest(),
            "font_inventory": fonts,
            "renderer_package": run(["dpkg-query", "-W", "-f=${Version}", "poppler-utils"]),
            "macros_enabled": False,
            "external_updates_enabled": False,
            "limitations": [
                "Office compatibility and font substitution require review",
                "Rendering or calculation is not visual verification",
            ],
        }
        staged = directory / ("output.xlsx" if mode == "recalculate" else "render.zip")
        if mode == "recalculate":
            convert(copied, staged, directory, "recalculate")
            report.update(json.loads((directory / "engine.json").read_text()))
            report.update(compare_workbooks(copied, staged))
            # Exported error caches independently corroborate the live engine errors.
            errors = [c for c in report["exported_formula_cells"] if c["type"] == "e"]
            report["exported_error_count"] = len(errors)
            report["calculation_status"] = (
                "errors_or_changes"
                if errors
                or report["formula_errors"]
                or report["content_changes"]
                or not report["sheet_names_preserved"]
                else "recalculated"
            )
        else:
            report.update(render(copied, directory))
            if suffix == ".pptx":
                report["issues"].extend(slide_issues(copied))
                report["structural_checks_completed"].append("simple_slide_canvas")
            with zipfile.ZipFile(staged, "x", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.write(directory / "document.pdf", "document.pdf")
                for page in report["pages"]:
                    archive.write(directory / page["member"], page["member"])
                archive.writestr("manifest.json", json.dumps(report, ensure_ascii=False))
        if not staged.is_file() or not 0 < staged.stat().st_size <= OUTPUT_LIMIT:
            raise ValueError("office_output_limit")
        report["output_sha256"], report["output_bytes"] = digest(staged), staged.stat().st_size
        body = json.dumps(report, ensure_ascii=False, allow_nan=False).encode()
        if len(body) > 4 * 1024**2 or digest(source) != before:
            raise ValueError("office_report_limit_or_source_changed")
        # Exclusive creates; a pre-existing output can never be overwritten.
        with output.open("xb") as stream:
            stream.write(staged.read_bytes())
        with report_path.open("xb") as stream:
            stream.write(body)


def extract(raw_source, number, raw_output, raw_report):
    def require(condition):
        if not condition:
            raise ValueError("office_page_bundle_invalid")

    source = safe_file(raw_source, limit=OUTPUT_LIMIT)
    output, report_path = safe_file(raw_output, output=True), safe_file(raw_report, output=True)
    with zipfile.ZipFile(source) as archive:
        checked_entries(archive)
        manifest = json.loads(archive.read("manifest.json"))
        require(manifest["format"] == "dsgpt-office-v1" and manifest["operation"] == "render")
        require(1 <= number <= manifest["page_count"] <= PAGES)
        page = manifest["pages"][number - 1]
        require(page["page"] == number and page["member"] == f"page-{number:03}.png")
        body = archive.read(page["member"])
        require(len(body) == page["bytes"] <= 4 * 1024**2)
        require(hashlib.sha256(body).hexdigest() == page["sha256"])
        import io

        from PIL import Image

        with Image.open(io.BytesIO(body)) as image:
            require(image.format == "PNG" and image.size == (page["width"], page["height"]))
            image.verify()
    with output.open("xb") as stream:
        stream.write(body)
    with report_path.open("x", encoding="utf-8") as stream:
        json.dump(
            {
                "format": "dsgpt-office-v1",
                "operation": "extract-page",
                "source_sha256": digest(source),
                "output_sha256": page["sha256"],
                "page": number,
                "visual_review_status": "not_performed",
            },
            stream,
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["render", "recalculate", "extract-page", "engine"])
    parser.add_argument("arguments", nargs="+")
    args = parser.parse_args()
    try:
        if args.mode == "engine":
            mode, source, output, directory = args.arguments
            engine(Path(source), Path(output), Path(directory), mode)
        elif args.mode == "extract-page":
            source, page, output, report = args.arguments
            extract(source, int(page), output, report)
        else:
            source, output, report = args.arguments
            validate(args.mode, source, output, report)
    except Exception as exc:
        # Document text, formulas, passwords and engine diagnostics are private data.
        code = str(exc) if type(exc) is ValueError else "office_operation_failed"
        if not re.fullmatch(r"(?:office|workbook)_[a-z_]{1,70}", code):
            code = "office_operation_failed"
        print(code, file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
