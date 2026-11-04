"""Private document extraction using the existing checked offline sandbox."""

import base64
import binascii
import hashlib
import json
from pathlib import Path, PurePosixPath

from fastapi import HTTPException

from . import document_worker
from .attachments import prepare
from .documents import MAX_DOCUMENT_BYTES, extract_docx
from .sandbox import SandboxError
from .storage import canonical, uid, utcnow

DOCUMENT_EXTENSIONS = {".docx", ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".xlsx", ".pptx"}
NOTICE = (
    "Local extraction with page/part provenance. OCR uses English and can misread text. "
    "Layout, charts, formulas, embedded objects and reading order may be omitted or incorrect. "
    "Spreadsheet values may be cached; formulas are never executed. Links are never opened. "
    "The original file is retained for review and download. Images also require a local vision "
    "model for visual interpretation; OCR alone does not describe pictures."
)


class DocumentProcessor:
    def __init__(self, store, builds):
        self.store, self.builds = store, builds

    async def prepare(self, values):
        extracted = {}
        for value in values:
            encoded = value.get("original_base64")
            if encoded is None:
                continue
            name = value["name"]
            extension = PurePosixPath(name).suffix.lower()
            if extension not in DOCUMENT_EXTENSIONS:
                raise HTTPException(422, "Choose DOCX, PDF, PNG, JPEG, WebP, XLSX or PPTX")
            if extension == ".docx":
                extracted[name, encoded] = extract_docx(name, encoded)
                continue
            try:
                original = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError):
                raise HTTPException(422, "Invalid document encoding") from None
            if not original or len(original) > MAX_DOCUMENT_BYTES:
                raise HTTPException(413, "Original files are limited to 512 KiB each")
            if not self.builds.ready or not self.builds.sandbox:
                raise HTTPException(
                    409,
                    {
                        "code": "document_tools_not_ready",
                        "help": "Install document tools and verify them in Work settings.",
                    },
                )
            if self.builds.lock.locked():
                raise HTTPException(409, "An isolated operation is active; retry after it finishes")
            async with self.builds.lock:
                identifier, now = uid(), utcnow()
                digest = hashlib.sha256(original).hexdigest()
                with self.store.transaction() as db:
                    db.execute(
                        "INSERT INTO work_executions(id,action,snapshot_sha256,image_id,status,"
                        "created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                        (
                            identifier,
                            '{"tool":"private_document_extract"}',
                            digest,
                            self.builds.image,
                            "running",
                            now,
                            now,
                        ),
                    )
                request = canonical({"extension": extension[1:], "original_base64": encoded})
                files = [
                    {
                        "path": "request.json",
                        "content": request,
                        "sha256": hashlib.sha256(request.encode()).hexdigest(),
                    }
                ]
                program = Path(document_worker.__file__).read_text()
                files.append(
                    {
                        "path": "worker.py",
                        "content": program,
                        "sha256": hashlib.sha256(program.encode()).hexdigest(),
                    }
                )
                try:
                    result = await self.builds.sandbox.execute(
                        identifier,
                        files,
                        ["/usr/bin/python3", "-I", "worker.py"],
                        ["result.json"],
                        120,
                    )
                    if result["exit_code"] != 0 or len(result["artifacts"]) != 1:
                        raise ValueError("Document tools unavailable or extraction failed")
                    payload = result["artifacts"][0]["content"]
                    if len(payload) > 524288:
                        raise ValueError("Document extraction exceeded output limit")
                    document = json.loads(payload)
                    if "error" in document:
                        raise ValueError(document["error"])
                    text = document["text"]
                    if not isinstance(text, str) or len(text.encode()) > 65536:
                        raise ValueError("Invalid extracted text")
                    metadata = {k: document[k] for k in ["format", "image", "pages"]}
                    metadata.update(
                        extractor="isolated-document-v1",
                        notice=NOTICE,
                        text_bytes=len(text.encode()),
                        text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                    )
                    if document.get("dimensions"):
                        metadata["dimensions"] = document["dimensions"]
                    extracted[name, encoded] = {
                        "name": name,
                        "text": text,
                        "bytes": len(original),
                        "sha256": digest,
                        "original_base64": encoded,
                        "document": metadata,
                    }
                    with self.store.transaction() as db:
                        db.execute(
                            "UPDATE work_executions SET status='completed',result=?,"
                            "cleanup_pending=0,updated_at=? WHERE id=?",
                            ('{"extracted":true}', utcnow(), identifier),
                        )
                except (SandboxError, OSError, TimeoutError, ValueError, KeyError) as exc:
                    # Retain a cleanup receipt; startup/probe verifies container ownership.
                    with self.store.transaction() as db:
                        db.execute(
                            "UPDATE work_executions SET status='failed',result=?,"
                            "updated_at=? WHERE id=?",
                            ('{"error":"document_extraction_failed"}', utcnow(), identifier),
                        )
                    raise HTTPException(
                        422, "Document extraction failed: " + str(exc)[:300]
                    ) from exc
        return prepare(values, documents=True, extractor=lambda name, data: extracted[name, data])
