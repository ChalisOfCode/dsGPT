"""Bounded, independent OOXML inspection; never executes document content."""

import decimal
import re
import stat
import zipfile
from pathlib import PurePosixPath
from xml.etree import ElementTree as ET

INPUT_LIMIT = 32 * 1024**2
EXPANDED_LIMIT = 128 * 1024**2
CELL_LIMIT = 20000
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def checked_entries(archive):
    entries = archive.infolist()
    if len(entries) > 4096 or sum(x.file_size for x in entries) > EXPANDED_LIMIT:
        raise ValueError("office_archive_limit")
    names = set()
    for row in entries:
        name = row.filename
        if (
            not name
            or name.startswith("/")
            or "\\" in name
            or ":" in name
            or ".." in PurePosixPath(name).parts
            or name.casefold() in names
            or row.flag_bits & 1
            or row.file_size > 32 * 1024**2
            or stat.S_IFMT(row.external_attr >> 16) not in (0, stat.S_IFREG, stat.S_IFDIR)
        ):
            raise ValueError("office_archive_unsafe")
        names.add(name.casefold())
    return entries


def xml(archive, name):
    data = archive.read(name)
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("office_xml_entities_denied")
    return ET.fromstring(data)


def inspect_package(source):
    """Reject active/external data before an engine sees it, preserve plain hyperlinks."""
    with zipfile.ZipFile(source) as archive:
        for row in checked_entries(archive):
            name = row.filename.casefold()
            if any(
                part in name
                for part in (
                    "vbaproject",
                    "/activex/",
                    "/embeddings/",
                    "externallinks/",
                    "connections.xml",
                )
            ):
                raise ValueError("office_active_or_external_content_unsupported")
            if name.endswith(".rels"):
                for rel in xml(archive, row.filename):
                    if rel.get("TargetMode") == "External" and not rel.get("Type", "").endswith(
                        "/hyperlink"
                    ):
                        raise ValueError("office_external_resource_unsupported")
            if name.endswith(".xml"):
                # Also catches malicious declarations in non-relationship parts.
                xml(archive, row.filename)


def workbook_cells(source):
    """Read exported formulas/caches independently of LibreOffice's live cell objects."""
    with zipfile.ZipFile(source) as archive:
        checked_entries(archive)
        names = set(archive.namelist())
        formats, styles = {}, ["builtin:0"]
        if "xl/styles.xml" in names:
            style_xml = xml(archive, "xl/styles.xml")
            formats = {
                x.get("numFmtId"): x.get("formatCode")
                for x in style_xml.findall("s:numFmts/s:numFmt", NS)
            }
            styles = [
                formats.get(x.get("numFmtId", "0"), "builtin:" + x.get("numFmtId", "0"))
                for x in style_xml.findall("s:cellXfs/s:xf", NS)
            ]
        shared = []
        if "xl/sharedStrings.xml" in names:
            shared = ["".join(x.itertext()) for x in xml(archive, "xl/sharedStrings.xml")]
        book = xml(archive, "xl/workbook.xml")
        if book.find("s:externalReferences", NS) is not None:
            raise ValueError("workbook_external_reference_unsupported")
        rels = {x.get("Id"): x.get("Target") for x in xml(archive, "xl/_rels/workbook.xml.rels")}
        sheets, cells = [], {}
        for sheet in book.findall("s:sheets/s:sheet", NS):
            title = sheet.attrib["name"]
            if title in sheets:
                raise ValueError("workbook_duplicate_sheet")
            sheets.append(title)
            target = rels[
                sheet.attrib[
                    "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
                ]
            ]
            member = target.lstrip("/") if target.startswith("/") else "xl/" + target
            if member not in names or ".." in PurePosixPath(member).parts:
                raise ValueError("workbook_sheet_path_invalid")
            for cell in xml(archive, member).findall(".//s:sheetData/s:row/s:c", NS):
                ref, kind = cell.attrib["r"], cell.get("t", "n")
                if not re.fullmatch(r"[A-Z]{1,3}[1-9][0-9]{0,6}", ref):
                    raise ValueError("workbook_cell_address_invalid")
                formula = cell.find("s:f", NS)
                if formula is not None and formula.get("t", "normal") != "normal":
                    raise ValueError("workbook_shared_or_array_formula_unsupported")
                value = cell.findtext("s:v", default="", namespaces=NS)
                if kind == "s":
                    value, kind = shared[int(value)], "str"
                elif kind == "inlineStr":
                    value, kind = "".join(cell.find("s:is", NS).itertext()), "str"
                elif kind == "n" and value:
                    number = decimal.Decimal(value)
                    if not number.is_finite():
                        raise ValueError("workbook_nonfinite_number")
                    value = str(number.normalize())
                if formula is None and not value:
                    continue  # Ignore formatting-only blank cells.
                key = (title, ref)
                if key in cells or len(cells) >= CELL_LIMIT:
                    raise ValueError("workbook_cell_limit_or_duplicate")
                cells[key] = {
                    "formula": formula.text if formula is not None else None,
                    "type": kind,
                    "value": value,
                    "style": cell.get("s", "0"),
                    "number_format": styles[int(cell.get("s", "0"))],
                }
        if not 1 <= len(sheets) <= 32:
            raise ValueError("workbook_sheet_limit")
        return sheets, cells


def compare_workbooks(before, after):
    original_sheets, original = workbook_cells(before)
    output_sheets, output = workbook_cells(after)
    changes, caches = [], []
    for key in sorted(set(original) | set(output)):
        a, b = original.get(key), output.get(key)
        location = {"sheet": key[0], "cell": key[1]}
        if a is None or b is None or a["formula"] != b["formula"]:
            changes.append({**location, "kind": "formula_or_cell_changed"})
        elif a["formula"] is None and (a["type"], a["value"]) != (b["type"], b["value"]):
            changes.append({**location, "kind": "nonformula_value_changed"})
        if b and b["formula"] is not None:
            caches.append({**location, **b})
    return {
        "sheet_names_preserved": original_sheets == output_sheets,
        "content_changes": changes,
        "exported_formula_cells": caches,
        "formatting_preservation_verified": False,
    }


def slide_issues(source):
    """Check simple slide objects against the actual canvas; no overlap/visual claim."""
    p = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
    a = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    issues = []
    with zipfile.ZipFile(source) as archive:
        checked_entries(archive)
        size = xml(archive, "ppt/presentation.xml").find(p + "sldSz")
        width, height = int(size.attrib["cx"]), int(size.attrib["cy"])
        if width <= 0 or height <= 0:
            raise ValueError("office_slide_geometry_invalid")
        for name in archive.namelist():
            if not re.fullmatch(r"ppt/slides/slide[0-9]+\.xml", name):
                continue
            tree = xml(archive, name).find(p + "cSld/" + p + "spTree")
            for index, shape in enumerate(tree):
                if shape.tag == p + "grpSp":
                    issues.append(
                        {"slide_part": name, "object": index, "kind": "group_geometry_unchecked"}
                    )
                    continue
                transform = shape.find(p + "spPr/" + a + "xfrm")
                if transform is None:
                    continue
                offset, extent = transform.find(a + "off"), transform.find(a + "ext")
                x, y = int(offset.attrib["x"]), int(offset.attrib["y"])
                w, h = int(extent.attrib["cx"]), int(extent.attrib["cy"])
                if min(x, y, w, h) < 0 or x + w > width or y + h > height:
                    issues.append(
                        {"slide_part": name, "object": index, "kind": "outside_slide_canvas"}
                    )
                if transform.get("rot", "0") != "0":
                    issues.append(
                        {"slide_part": name, "object": index, "kind": "rotated_geometry_unchecked"}
                    )
    return issues
