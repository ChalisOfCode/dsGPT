"""Bounded, inert reader for the supported ChatGPT export mapping format.

ZIP members are read in memory, never extracted. The export is untrusted data,
not model instructions, HTML, code, credentials or a filesystem manifest.
"""

import hashlib
import io
import json
import math
import os
import re
import stat
import zipfile
import zlib
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from .storage import canonical

MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_JSON_BYTES = 32 * 1024 * 1024
MAX_ENTRIES = 10000
MAX_CONVERSATIONS = 1000
MAX_NODES = 50000
MAX_MESSAGE_BYTES = 128 * 1024
PARSER_VERSION = "chatgpt-mapping-v1"
JSON_NAME = re.compile(r"conversations(?:[-_]\d+)?\.json\Z")


class ArchiveError(ValueError):
    """Messages contain fixed validation descriptions, never archive text or paths."""


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def text(value, maximum, label, empty=False):
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise ArchiveError("Invalid " + label)
    try:
        encoded = value.encode("utf-8")
    except UnicodeError as exc:
        raise ArchiveError("Invalid Unicode in " + label) from exc
    if len(encoded) > maximum or any(ord(c) < 32 and c not in "\t\r\n" for c in value):
        raise ArchiveError("Oversized or invalid " + label)
    return value


def timestamp(value):
    if value is None:
        return None
    if type(value) not in (int, float):
        raise ArchiveError("Invalid source timestamp")
    try:
        if not math.isfinite(value):
            raise ArchiveError("Invalid source timestamp")
        return datetime.fromtimestamp(value, UTC).isoformat()
    except (ValueError, OverflowError, OSError) as exc:
        raise ArchiveError("Source timestamp is outside the supported range") from exc


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ArchiveError("Duplicate JSON object key")
        result[key] = value
    return result


def _constant(value):
    raise ArchiveError("Nonfinite JSON number")


def _json(data):
    if len(data) > MAX_JSON_BYTES:
        raise ArchiveError("Conversation JSON exceeds 32 MiB")
    try:
        value = json.loads(
            data.decode("utf-8-sig"), object_pairs_hook=_pairs, parse_constant=_constant
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ArchiveError("Invalid UTF-8 conversation JSON") from exc
    if not isinstance(value, list):
        raise ArchiveError("Conversation JSON must contain an array")
    return value


def _members(data):
    if not data.startswith(b"PK"):
        return [("conversations.json", data)]
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ENTRIES:
                raise ArchiveError("ZIP has too many entries")
            selected, names, basenames, total = [], set(), set(), 0
            for info in infos:
                name = info.filename
                text(name, 1024, "ZIP member name")
                path = PurePosixPath(name)
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or "\\" in name
                    or ":" in name
                    or "\x00" in info.orig_filename
                    or name.casefold() in names
                    or stat.S_ISLNK(info.external_attr >> 16)
                ):
                    raise ArchiveError("Unsafe or duplicate ZIP member")
                names.add(name.casefold())
                if info.is_dir() or not JSON_NAME.fullmatch(path.name):
                    continue
                if path.name in basenames:
                    raise ArchiveError("Ambiguous conversation JSON members")
                basenames.add(path.name)
                total += info.file_size
                if (
                    total > MAX_JSON_BYTES
                    or info.flag_bits & 1
                    or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                    or info.file_size > max(1, info.compress_size) * 200
                ):
                    raise ArchiveError("Conversation ZIP member exceeds supported bounds")
                selected.append(info)
            if not selected:
                raise ArchiveError("No supported conversation JSON member found")
            if len(selected) > 1 and "conversations.json" in basenames:
                raise ArchiveError("Mixed single and numbered conversation JSON members")
            result = []
            remaining = MAX_JSON_BYTES
            for info in sorted(selected, key=lambda i: i.filename):
                with archive.open(info) as member:
                    raw = member.read(remaining + 1)
                if len(raw) != info.file_size or len(raw) > remaining:
                    raise ArchiveError("Conversation ZIP member size mismatch")
                remaining -= len(raw)
                result.append((info.filename, raw))
            return result
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError, zlib.error) as exc:
        raise ArchiveError("Invalid or unsupported ZIP archive") from exc


def _conversation(record, member):
    if not isinstance(record, dict):
        raise ArchiveError("Unsupported conversation record")
    source_id = text(record.get("id", record.get("conversation_id")), 200, "conversation ID")
    if "conversation_id" in record and record["conversation_id"] != source_id:
        raise ArchiveError("Conflicting conversation identifiers")
    title = text(record.get("title"), 1200, "conversation title")
    if len(title) > 300:
        raise ArchiveError("Conversation title exceeds 300 characters")
    created, updated = timestamp(record.get("create_time")), timestamp(record.get("update_time"))
    mapping = record.get("mapping")
    if not isinstance(mapping, dict) or not mapping or len(mapping) > MAX_NODES:
        raise ArchiveError("Missing or oversized conversation mapping")
    parents, children = {}, {key: 0 for key in mapping}
    for key, node in mapping.items():
        text(key, 200, "node ID")
        if not isinstance(node, dict) or node.get("id", key) != key:
            raise ArchiveError("Invalid conversation node")
        parent = node.get("parent")
        if parent is not None and (not isinstance(parent, str) or parent not in mapping):
            raise ArchiveError("Conversation node has a missing parent")
        parents[key] = parent
        if parent is not None:
            children[parent] += 1
    # Validate the entire graph in linear time, including unselected branches.
    resolved = set()
    for key in mapping:
        visiting = set()
        cursor = key
        while cursor is not None and cursor not in resolved:
            if cursor in visiting:
                raise ArchiveError("Conversation graph contains a cycle")
            visiting.add(cursor)
            cursor = parents[cursor]
        resolved.update(visiting)
    current = record.get("current_node")
    inferred = current is None
    if inferred:
        leaves = [key for key, count in children.items() if count == 0]
        if len(leaves) != 1:
            raise ArchiveError("Ambiguous active conversation branch")
        current = leaves[0]
    if not isinstance(current, str) or current not in mapping:
        raise ArchiveError("Active conversation node is missing")
    branch, cursor = [], current
    while cursor is not None:
        branch.append(cursor)
        cursor = parents[cursor]
    branch.reverse()
    counts = {
        "inactive_nodes_omitted": len(mapping) - len(branch),
        "nonchat_messages_omitted": 0,
        "unsupported_parts_omitted": 0,
        "empty_messages_omitted": 0,
        "missing_message_dates": 0,
        "branch_inferred": int(inferred),
    }
    messages = []
    for key in branch:
        message = mapping[key].get("message")
        if message is None:
            continue
        if not isinstance(message, dict) or not isinstance(message.get("author"), dict):
            raise ArchiveError("Malformed message")
        role = message["author"].get("role")
        if role not in ("user", "assistant"):
            counts["nonchat_messages_omitted"] += 1
            continue
        metadata = message.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ArchiveError("Malformed message metadata")
        # Tool calls, hidden messages and nonfinal channels must never become live instructions.
        if (
            message.get("recipient") not in (None, "all")
            or message.get("channel") not in (None, "final")
            or metadata.get("is_visually_hidden_from_conversation")
        ):
            counts["nonchat_messages_omitted"] += 1
            continue
        content = message.get("content")
        if not isinstance(content, dict):
            raise ArchiveError("Malformed message content")
        parts = content.get("parts")
        if content.get("content_type") not in ("text", "multimodal_text"):
            counts["unsupported_parts_omitted"] += 1
            continue
        if not isinstance(parts, list):
            raise ArchiveError("Message parts must be an array")
        strings = []
        for part in parts:
            if isinstance(part, str):
                strings.append(text(part, MAX_MESSAGE_BYTES, "message text", empty=True))
            else:
                counts["unsupported_parts_omitted"] += 1
        body = text("\n".join(strings), MAX_MESSAGE_BYTES, "message text", empty=True)
        if not body.strip():
            counts["empty_messages_omitted"] += 1
            continue
        date = timestamp(message.get("create_time"))
        counts["missing_message_dates"] += int(date is None)
        messages.append({"source_node_id": key, "role": role, "content": body, "created_at": date})
    if not messages:
        raise ArchiveError("Conversation has no supported visible text messages")
    normalized = {
        "source_id": source_id,
        "title": title,
        "created_at": created,
        "updated_at": updated,
        "current_node": current,
        "messages": messages,
        "omissions": counts,
        "parser": PARSER_VERSION,
    }
    return {**normalized, "sha256": digest(normalized), "member": member, "nodes": len(mapping)}


def read_archive(path):
    """Read only the explicitly selected regular file; never follow a file symlink."""
    path = Path(path)
    if path.is_symlink():
        raise ArchiveError("Select a regular export file, not a symlink")
    fd = os.open(
        path,
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_BINARY", 0),
    )
    with os.fdopen(fd, "rb") as file:
        info = os.fstat(file.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_ARCHIVE_BYTES:
            raise ArchiveError("Export must be a regular file of at most 64 MiB")
        data = file.read(MAX_ARCHIVE_BYTES + 1)
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ArchiveError("Export exceeds 64 MiB")
    records, seen, nodes = [], set(), 0
    members = _members(data)
    for name, raw in members:
        for record in _json(raw):
            if len(records) >= MAX_CONVERSATIONS:
                raise ArchiveError("Export exceeds 1000 conversations")
            item = _conversation(record, name)
            nodes += item["nodes"]
            if nodes > MAX_NODES:
                raise ArchiveError("Export exceeds 50000 graph nodes")
            if item["source_id"] in seen:
                raise ArchiveError("Duplicate conversation ID within export")
            seen.add(item["source_id"])
            records.append(item)
    if not records:
        raise ArchiveError("Export contains no supported conversations")
    return {"archive_sha256": hashlib.sha256(data).hexdigest(), "conversations": records}


def select(archive, source_ids):
    wanted = set(source_ids)
    available = {item["source_id"] for item in archive["conversations"]}
    if wanted - available:
        raise ArchiveError("Selected conversation is absent from export")
    return [item for item in archive["conversations"] if not wanted or item["source_id"] in wanted]


def preview(archive, source_ids=()):
    records = select(archive, source_ids)
    return {
        "parser": PARSER_VERSION,
        "archive_sha256": archive["archive_sha256"],
        "selected_conversations": len(records),
        "selected_messages": sum(len(r["messages"]) for r in records),
        "conversations": [
            {
                k: r[k]
                for k in (
                    "source_id",
                    "title",
                    "created_at",
                    "updated_at",
                    "current_node",
                    "sha256",
                    "member",
                    "omissions",
                )
            }
            | {"messages": len(r["messages"])}
            for r in records
        ],
        "limitations": [
            "Only the active branch's visible user/assistant text is imported",
            "Inactive branches, tool/system messages and nontext assets are omitted",
            "Unknown dates stay unknown in provenance; chat ordering uses import time as fallback",
            "Original archive stays at the chosen path; it is not copied or sent to any service",
            "No automatic memory promotion, semantic retrieval or project inference",
        ],
    }
