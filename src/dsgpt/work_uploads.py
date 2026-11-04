"""Authenticated, resumable bounded uploads. Binary data never enters model context."""

import base64
import hashlib
import shutil

from fastapi import HTTPException

from .project_tools import safe_path
from .storage import uid, utcnow

MAX_UPLOAD = 256 * 1024**2
MAX_INPUTS = 512 * 1024**2
CHUNK = 256 * 1024


class WorkUploads:
    def __init__(self, store):
        self.store = store

    def start(self, owner, name, size):
        try:
            safe_path(name)
            if "/" in name or len(name) > 160:
                raise ValueError()
        except ValueError as exc:
            raise HTTPException(422, "Choose a portable filename without folders") from exc
        if not 1 <= size <= MAX_UPLOAD:
            raise HTTPException(413, "Work files are limited to 256 MiB each")
        with self.store.transaction() as db:
            # Expired, unclaimed uploads are disposable; task originals are independent.
            db.execute("DELETE FROM work_uploads WHERE julianday('now')-julianday(updated_at)>7")
            used = db.execute("SELECT coalesce(sum(size),0) FROM work_uploads").fetchone()[0]
            if (
                used + size > 2 * MAX_INPUTS
                or shutil.disk_usage(self.store.directory).free < 3 * size + 64 * 1024**2
            ):
                raise HTTPException(
                    413, "Upload storage is full; remove unused uploads or free disk space"
                )
            identifier = uid()
            db.execute(
                "INSERT INTO work_uploads VALUES(?,?,?,?,0,NULL,zeroblob(?),?)",
                (identifier, owner, name, size, size, utcnow()),
            )
        return self.status(owner, identifier)

    def status(self, owner, identifier):
        row = self.store.one(
            "SELECT id,name,size,received,sha256 FROM work_uploads WHERE id=? AND owner=?",
            (identifier, owner),
        )
        if not row:
            raise HTTPException(404, "Upload not found or expired")
        return {**row, "chunk_bytes": CHUNK, "ready": row["sha256"] is not None}

    def chunk(self, owner, identifier, offset, encoded):
        try:
            data = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise HTTPException(422, "Invalid upload chunk") from exc
        if not 1 <= len(data) <= CHUNK:
            raise HTTPException(413, "Chunk must contain 1 to 262144 bytes")
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT rowid,size,received,sha256 FROM work_uploads WHERE id=? AND owner=?",
                (identifier, owner),
            ).fetchone()
            if not row:
                raise HTTPException(404, "Upload not found")
            if offset < 0 or offset + len(data) > row["size"] or offset > row["received"]:
                raise HTTPException(409, "Chunk offset does not match the saved upload")
            with db.blobopen("work_uploads", "content", row["rowid"]) as blob:
                blob.seek(offset)
                if offset < row["received"] or row["sha256"]:
                    if offset + len(data) > row["received"] or blob.read(len(data)) != data:
                        raise HTTPException(409, "Retried chunk differs from saved bytes")
                else:
                    blob.write(data)
                    db.execute(
                        "UPDATE work_uploads SET received=?,updated_at=? WHERE id=?",
                        (offset + len(data), utcnow(), identifier),
                    )
        return self.status(owner, identifier)

    def finish(self, owner, identifier):
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT rowid,size,received,sha256 FROM work_uploads WHERE id=? AND owner=?",
                (identifier, owner),
            ).fetchone()
            if not row:
                raise HTTPException(404, "Upload not found")
            if row["received"] != row["size"]:
                raise HTTPException(409, "Upload is incomplete; resume from the saved offset")
            with db.blobopen("work_uploads", "content", row["rowid"], readonly=True) as blob:
                hasher = hashlib.sha256()
                while chunk := blob.read(CHUNK):
                    hasher.update(chunk)
                digest = hasher.hexdigest()
            db.execute(
                "UPDATE work_uploads SET sha256=?,updated_at=? WHERE id=?",
                (digest, utcnow(), identifier),
            )
        return self.status(owner, identifier)

    def originals(self, owner, identifiers):
        if len(set(identifiers)) != len(identifiers):
            raise HTTPException(422, "Choose distinct uploads")
        rows, total = [], 0
        for identifier in identifiers:
            meta = self.status(owner, identifier)
            if not meta["ready"]:
                raise HTTPException(409, "Finish uploading each selected file first")
            total += meta["size"]
            if total > MAX_INPUTS:
                raise HTTPException(413, "Work inputs exceed 512 MiB total")
            row = self.store.one(
                "SELECT content FROM work_uploads WHERE id=? AND owner=?", (identifier, owner)
            )
            rows.append(
                {
                    "name": meta["name"],
                    "original": row["content"],
                    "sha256": meta["sha256"],
                    "extraction": {
                        "format": "asset",
                        "bytes": meta["size"],
                        "notice": "Original file available in isolated Work tools under inputs/.",
                    },
                }
            )
        return rows

    def delete(self, owner, identifier):
        with self.store.transaction() as db:
            db.execute("DELETE FROM work_uploads WHERE id=? AND owner=?", (identifier, owner))
        return {"deleted": True}
