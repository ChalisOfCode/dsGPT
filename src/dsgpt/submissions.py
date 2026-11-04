"""Versioned hashes of accepted API inputs, independent of derived tool output."""

import hashlib

from fastapi import HTTPException

from .storage import canonical

TABLES = {"chat": "chat_submission_receipts", "work": "work_submission_receipts"}


def fingerprint(body, *, conversation_id=None, normalized=None):
    payload = body.model_dump(mode="json", exclude={"request_id"})
    # Preserve established pure-input equivalences (URL fragments/duplicates, query
    # whitespace) without invoking a decoder, network operation or model registry.
    payload.update(normalized or {})
    return hashlib.sha256(canonical([1, conversation_id, payload]).encode()).hexdigest()


def accepted(db, kind, request_id, request_hash):
    if request_hash is None:
        return False
    row = db.execute(
        f"SELECT request_hash FROM {TABLES[kind]} WHERE request_id=?", (request_id,)
    ).fetchone()
    if row is None:
        return False
    if row[0] != request_hash:
        raise HTTPException(409, "Request id was already used for different input")
    return True


def remember(db, kind, request_id, request_hash):
    # Called in the same transaction as acceptance (or a verified legacy replay).
    # Store only the digest: no second copy of prompts or private document bytes.
    if request_hash is not None:
        db.execute(f"INSERT INTO {TABLES[kind]} VALUES(?,?)", (request_id, request_hash))
