"""Bounded DOCX text extraction. Never executes content or follows relationships."""

import base64
import binascii
import hashlib
import io
import re
import zipfile
import zlib
from pathlib import PurePosixPath
from xml.etree import ElementTree as ET

from fastapi import HTTPException

MAX_DOCUMENT_BYTES = 524_288
MAX_DOCUMENT_TOTAL = 786_432
MAX_XML_BYTES = 1_048_576
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
NOTICE = (
    "DOCX main-body text only. Formatting, numbering, images, text boxes, headers, "
    "footers, comments, footnotes, equations and embedded objects are not interpreted. "
    "Tracked deletions and field instructions are excluded; visible field results may be stale. "
    "Hidden-text formatting is not applied. Links are never opened. "
    "The original document is retained for download."
)


def reject(detail="Unsupported or malformed DOCX document"):
    raise HTTPException(422, detail)


def xml(data):
    if len(data) > MAX_XML_BYTES:
        reject("DOCX XML exceeds the extraction limit")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeError:
        reject("DOCX XML must use UTF-8")
    if "\x00" in text or re.search(r"<!\s*(DOCTYPE|ENTITY)", text, re.I):
        reject("DTD/entity declarations are not supported")
    try:
        return ET.fromstring(text)
    except (ET.ParseError, LookupError, ValueError):
        reject()


def extract_docx(name, encoded):
    if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_DOCUMENT_BYTES + 2) // 3):
        raise HTTPException(413, "DOCX files are limited to 512 KiB each")
    try:
        original = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        reject("Invalid document encoding")
    if not original or len(original) > MAX_DOCUMENT_BYTES:
        raise HTTPException(413, "DOCX files are limited to 512 KiB each")
    try:
        with zipfile.ZipFile(io.BytesIO(original)) as archive:
            entries = archive.infolist()
            if len(entries) > 256 or sum(e.file_size for e in entries) > 8 * MAX_XML_BYTES:
                reject("DOCX package exceeds the extraction limit")
            names = set()
            for entry in entries:
                path = PurePosixPath(entry.filename)
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or "\\" in entry.filename
                    or ":" in entry.filename
                    or entry.filename.casefold() in names
                    or entry.flag_bits & 1
                    or entry.compress_type not in {0, 8}
                    or entry.file_size > 4 * MAX_XML_BYTES
                ):
                    reject("Unsupported DOCX package member")
                names.add(entry.filename.casefold())
            if any("vbaproject" in n or n.endswith(".bin") for n in names):
                reject("Macro and embedded binary packages are not supported")
            content_types = xml(archive.read("[Content_Types].xml"))
            main_type = (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
            )
            if not any(
                e.get("PartName") == "/word/document.xml" and e.get("ContentType") == main_type
                for e in content_types
            ):
                reject("A standard non-macro DOCX main document is required")
            document = xml(archive.read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError, OSError, zlib.error):
        reject()
    if document.tag != W + "document":
        reject("Unsupported WordprocessingML namespace")
    body = document.find(W + "body")
    if body is None:
        reject()
    chunks, used, nodes = [], 0, 0
    stack = [(body, 0, False)]
    excluded = {W + n for n in ["del", "moveFrom", "drawing", "pict", "object", "txbxContent"]}
    while stack:
        node, depth, closing = stack.pop()
        if closing:
            value = "\t" if node.tag == W + "tc" else "\n"
        else:
            nodes += 1
            if depth > 64 or nodes > 50_000:
                reject("DOCX structure exceeds the extraction limit")
            if node.tag in excluded:
                continue
            value = (
                (node.text or "")
                if node.tag == W + "t"
                else (
                    "\t"
                    if node.tag == W + "tab"
                    else "\n"
                    if node.tag in {W + "br", W + "cr"}
                    else ""
                )
            )
            if node.tag in {W + "p", W + "tc", W + "tr"}:
                stack.append((node, depth, True))
            stack.extend((child, depth + 1, False) for child in reversed(node))
        used += len(value.encode("utf-8"))
        if used > 65_536:
            raise HTTPException(413, "Extracted document text exceeds 64 KiB; split the document")
        chunks.append(value)
    text = "".join(chunks).strip()
    if not text:
        reject("No supported main-body text found; scanned/image-only documents need OCR")
    return {
        "name": name,
        "text": text,
        "bytes": len(original),
        "sha256": hashlib.sha256(original).hexdigest(),
        "original_base64": base64.b64encode(original).decode("ascii"),
        "document": {
            "format": "docx",
            "extractor": "docx-main-text-v1",
            "text_bytes": len(text.encode()),
            "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "notice": NOTICE,
        },
    }
