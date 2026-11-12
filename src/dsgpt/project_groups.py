"""Explicit, version-bound associations; never rewrite imports or broaden permissions."""

import hashlib
import json
import re
from pathlib import PurePosixPath
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .storage import canonical, uid, utcnow

RULE = "project-hints-v1"
LIMIT = 50
GENERIC = {"continue", "update", "new chat", "chat", "project", "app", "main", "readme"}
REPO = re.compile(
    r"https://github\.com/([A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100})(?=[/\s#?\"'<>)]|$)"
)
PACKAGE = re.compile(
    r'\b(?:applicationId|namespace|package)\s*(?:=\s*)?["\']?([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){2,5})\b'
)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceRef(Strict):
    kind: Literal["history", "task", "input"]
    id: UUID
    name: str = Field(default="", max_length=255)

    @model_validator(mode="after")
    def named_input(self):
        if bool(self.name) != (self.kind == "input"):
            raise ValueError("Only input references have names")
        return self


class GroupPreview(Strict):
    sources: list[SourceRef] = Field(min_length=1, max_length=LIMIT)
    group_id: UUID | None = None


class GroupApply(GroupPreview):
    request_id: UUID
    preview_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    name: str = Field(default="", max_length=120)
    decision: Literal["accepted", "rejected", "ungrouped"] = "accepted"


class GroupRename(Strict):
    revision: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=120)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def identity(ref):
    return canonical([ref["kind"], str(ref["id"]), ref.get("name", "")])


def permitted(current, kind):
    return ("chat" if kind == "history" else "work") in current["scopes"]


def owner(current):
    if current["role"] != "owner" or "admin" not in current["scopes"]:
        raise HTTPException(403, "Only the owner can edit project groups")


def title_key(title):
    value = PurePosixPath(title).stem.casefold().strip()
    return value if 5 <= len(value) <= 80 and value not in GENERIC else None


def hints(text, title):
    # Inert text only. URLs are not opened and instruction-like text is never executed.
    repos = {m.group(1).casefold().rstrip(".").removesuffix(".git") for m in REPO.finditer(text)}
    repos = {v for v in repos if not v.startswith(("owner/", "user/", "example/"))}
    packages = {
        m.group(1)
        for m in PACKAGE.finditer(text)
        if not m.group(1).startswith(("com.example.", "org.example.", "com.test."))
    }
    key = title_key(title)
    return sorted(
        [
            *(("repository", r) for r in repos),
            *(("package", p) for p in packages),
            *((("title", key),) if key else ()),
        ]
    )[:20]


class ProjectGroups:
    def __init__(self, store):
        self.store = store

    def _source(self, db, ref, current, with_hints=False):
        ref = {**ref, "id": str(ref["id"]), "name": ref.get("name", "")}
        if not permitted(current, ref["kind"]):
            raise HTTPException(403, "Device lacks source permission")
        text = ""
        if ref["kind"] == "history":
            row = db.execute(
                "SELECT s.source_sha256,c.title,c.revision FROM history_sources s "
                "JOIN conversations c ON c.id=s.conversation_id WHERE c.id=? "
                "AND s.removed=0 AND c.hidden=0",
                (ref["id"],),
            ).fetchone()
            if not row:
                raise HTTPException(409, "Source changed, hidden or removed; refresh")
            base, title, revision = row
            if with_hints:
                # Bounded prefix of imported turns only, not unrelated local conversation turns.
                parts = db.execute(
                    "SELECT substr(m.content,1,8192) FROM messages m JOIN history_messages h "
                    "ON h.message_id=m.id WHERE m.conversation_id=? ORDER BY m.ordinal LIMIT 8",
                    (ref["id"],),
                )
                text = "\n".join(r[0] for r in parts)
        else:
            row = db.execute(
                "SELECT title,revision,substr(requirements,1,65536) FROM work_tasks WHERE id=?",
                (ref["id"],),
            ).fetchone()
            if not row:
                raise HTTPException(409, "Source removed; refresh")
            title, revision, text = row
            base = digest([title, revision, text])
            if ref["kind"] == "input":
                row = db.execute(
                    "SELECT sha256 FROM work_inputs WHERE task_id=? AND name=?",
                    (ref["id"], ref["name"]),
                ).fetchone()
                if not row:
                    raise HTTPException(409, "Input removed; refresh")
                base, title, text = row[0], ref["name"], ""
                if with_hints and PurePosixPath(title).suffix.lower() in {".txt", ".md", ".json"}:
                    body = db.execute(
                        "SELECT substr(original,1,65536) FROM work_inputs "
                        "WHERE task_id=? AND name=?",
                        (ref["id"], ref["name"]),
                    ).fetchone()[0]
                    text = bytes(body).decode("utf-8", errors="replace")
        result = {
            **ref,
            "key": identity(ref),
            "title": title,
            "source_sha256": base,
            "snapshot_sha256": digest([ref, base, title, revision]),
        }
        if with_hints:
            result["hints"] = hints(text, title)
            result["coverage"] = "Bounded metadata/text hints; not complete source inspection"
        return result

    def sources(self, current, kind, offset):
        if not permitted(current, kind):
            raise HTTPException(403, "Device lacks source permission")
        with self.store.connect() as db:
            if kind == "history":
                refs = [
                    {"kind": kind, "id": r[0]}
                    for r in db.execute(
                        "SELECT s.conversation_id FROM history_sources s JOIN conversations c "
                        "ON c.id=s.conversation_id WHERE s.removed=0 AND c.hidden=0 "
                        "ORDER BY s.conversation_id LIMIT 50 OFFSET ?",
                        (offset,),
                    )
                ]
            elif kind == "task":
                refs = [
                    {"kind": kind, "id": r[0]}
                    for r in db.execute(
                        "SELECT id FROM work_tasks ORDER BY id LIMIT 50 OFFSET ?", (offset,)
                    )
                ]
            else:
                refs = [
                    {"kind": kind, "id": r[0], "name": r[1]}
                    for r in db.execute(
                        "SELECT task_id,name FROM work_inputs "
                        "ORDER BY task_id,name LIMIT 50 OFFSET ?",
                        (offset,),
                    )
                ]
            return [self._source(db, r, current) for r in refs]

    def _group(self, db, identifier, current):
        row = db.execute(
            "SELECT * FROM project_groups WHERE id=? AND deleted=0", (str(identifier),)
        ).fetchone()
        if not row or not set(json.loads(row["scopes"])).issubset(current["scopes"]):
            raise HTTPException(404, "Group unavailable for this device")
        return dict(row)

    def _preview(self, db, body, current):
        owner(current)
        refs = {identity(r.model_dump()): r.model_dump() for r in body.sources}
        if len(refs) != len(body.sources):
            raise HTTPException(422, "Select distinct source references")
        sources = [self._source(db, refs[k], current, True) for k in sorted(refs)]
        group = self._group(db, body.group_id, current) if body.group_id else None
        decisions = [
            dict(r)
            for s in sources
            for r in db.execute(
                "SELECT source_key,group_id,decision,source_sha256 FROM project_group_links "
                "WHERE source_key=? ORDER BY group_id",
                (s["key"],),
            )
        ]
        candidates = {}
        for s in sources:
            for kind, value in s["hints"]:
                candidates.setdefault((kind, value), []).append(s["key"])
        suggestions = [
            {
                "evidence_kind": k,
                "value": v,
                "members": members,
                "strength": "weak name match" if k == "title" else "exact identifier",
            }
            for (k, v), members in sorted(candidates.items())
            if len(members) > 1
        ][:50]
        ambiguous = [
            s["key"]
            for s in sources
            if sum(1 for k, _ in s["hints"] if k in {"repository", "package"}) > 1
        ]
        value = {
            "rule": RULE,
            "sources": sources,
            "group": group,
            "decisions": decisions,
            "suggestions": suggestions,
            "ambiguous": ambiguous,
        }
        value["preview_sha256"] = digest(value)
        return value

    def preview(self, body, current):
        with self.store.connect() as db:
            return self._preview(db, body, current)

    def apply(self, body, current):
        owner(current)
        request_hash = digest(body.model_dump(mode="json"))
        with self.store.transaction() as db:
            old = db.execute(
                "SELECT request_sha256,result FROM project_group_requests WHERE id=?",
                (str(body.request_id),),
            ).fetchone()
            if old:
                if old[0] != request_hash:
                    raise HTTPException(409, "Request identity was already used")
                # Never recreate links, removed groups or source content on a retry.
                result = json.loads(old[1])
                result["replayed"] = True
                return result
            if db.execute("SELECT count(*) FROM project_group_requests").fetchone()[0] >= 4096:
                raise HTTPException(409, "Grouping request limit reached")
            preview = self._preview(db, body, current)
            if preview["preview_sha256"] != body.preview_sha256:
                raise HTTPException(409, "Sources, decisions or group changed; preview again")
            group = preview["group"]
            name = body.name.strip()
            if body.decision != "ungrouped" and not group and not name:
                raise HTTPException(422, "Choose a group name")
            if body.decision == "rejected" and not group:
                raise HTTPException(422, "Choose an existing group to reject")
            identifier = (group["id"] if group else uid()) if body.decision != "ungrouped" else ""
            now = utcnow()
            scopes = (
                {"chat" if s["kind"] == "history" else "work" for s in preview["sources"]}
                if body.decision == "accepted"
                else set()
            )
            if identifier:
                if group:
                    scopes.update(json.loads(group["scopes"]))
                    db.execute(
                        "UPDATE project_groups SET revision=revision+1,scopes=?,updated_at=? "
                        "WHERE id=?",
                        (canonical(sorted(scopes)), now, identifier),
                    )
                else:
                    if (
                        db.execute(
                            "SELECT count(*) FROM project_groups WHERE deleted=0"
                        ).fetchone()[0]
                        >= 256
                    ):
                        raise HTTPException(409, "Group limit reached")
                    db.execute(
                        "INSERT INTO project_groups VALUES(?,?,1,?,?,?,0)",
                        (identifier, name, canonical(sorted(scopes)), now, now),
                    )
            for source in preview["sources"]:
                if body.decision == "accepted":
                    db.execute(
                        "DELETE FROM project_group_links WHERE group_id='' AND source_key=?",
                        (source["key"],),
                    )
                if body.decision == "ungrouped":
                    db.execute(
                        "UPDATE project_groups SET revision=revision+1,updated_at=? WHERE id IN "
                        "(SELECT group_id FROM project_group_links WHERE source_key=?)",
                        (now, source["key"]),
                    )
                    db.execute(
                        "DELETE FROM project_group_links WHERE source_key=?", (source["key"],)
                    )
                db.execute(
                    "INSERT INTO project_group_links VALUES(?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(group_id,source_key) DO UPDATE SET "
                    "source_sha256=excluded.source_sha256,"
                    "decision=excluded.decision,rule=excluded.rule,updated_at=excluded.updated_at",
                    (
                        identifier,
                        source["key"],
                        source["kind"],
                        source["id"],
                        source["snapshot_sha256"],
                        body.decision,
                        RULE,
                        now,
                    ),
                )
            if db.execute("SELECT count(*) FROM project_group_links").fetchone()[0] > 4096:
                raise HTTPException(409, "Grouping link limit reached")
            result = {
                "group_id": identifier or None,
                "count": len(preview["sources"]),
                "decision": body.decision,
                "replayed": False,
            }
            db.execute(
                "INSERT INTO project_group_requests VALUES(?,?,?)",
                (str(body.request_id), request_hash, canonical(result)),
            )
            return result

    def list(self, current, offset=0):
        if not set(current["scopes"]).intersection({"chat", "work"}):
            raise HTTPException(403, "Device lacks source permission")
        with self.store.connect() as db:
            rows = db.execute("SELECT * FROM project_groups WHERE deleted=0 ORDER BY id").fetchall()
            eligible = [
                dict(r) for r in rows if set(json.loads(r["scopes"])).issubset(current["scopes"])
            ]
            return eligible[offset : offset + 50]

    def members(self, identifier, current):
        with self.store.connect() as db:
            group = self._group(db, identifier, current)
            links = db.execute(
                "SELECT * FROM project_group_links WHERE group_id=? "
                "AND decision='accepted' ORDER BY source_key",
                (str(identifier),),
            )
            result = []
            for link in links:
                kind, source_id, name = json.loads(link["source_key"])
                try:
                    source = self._source(
                        db, {"kind": kind, "id": source_id, "name": name}, current
                    )
                except HTTPException:
                    continue
                if source["snapshot_sha256"] == link["source_sha256"]:
                    result.append(source)
            return {"group": group, "members": result}

    def rename(self, identifier, body, current):
        owner(current)
        with self.store.transaction() as db:
            group = self._group(db, identifier, current)
            if group["revision"] != body.revision or not body.name.strip():
                raise HTTPException(409, "Group changed; reload")
            db.execute(
                "UPDATE project_groups SET name=?,revision=revision+1,updated_at=? WHERE id=?",
                (body.name.strip(), utcnow(), str(identifier)),
            )
        return {"updated": True}

    def delete(self, identifier, revision, current):
        owner(current)
        with self.store.transaction() as db:
            group = self._group(db, identifier, current)
            if group["revision"] != revision:
                raise HTTPException(409, "Group changed; reload")
            db.execute(
                "UPDATE project_groups SET name='',deleted=1,revision=revision+1 WHERE id=?",
                (str(identifier),),
            )
            db.execute("DELETE FROM project_group_links WHERE group_id=?", (str(identifier),))
        return {"deleted": True}
