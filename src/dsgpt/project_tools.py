"""Transactional project tools. Content is data in SQLite, never a host path or command.

This capability tier can draft and inspect source files. Executing those files needs
a separately validated isolated runner; there is deliberately no host-shell fallback.
"""

import copy
import hashlib
import io
import json
import re
import zipfile
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .storage import canonical, utcnow
from .work_references import WorkReferences

MAX_PROJECT_BYTES = 16_000_000
MAX_FILE_BYTES = 262_144
MAX_FILES = 128


def safe_path(raw):
    if (
        not raw
        or len(raw) > 240
        or raw.startswith("/")
        or "\\" in raw
        or ":" in raw
        or any(ord(c) < 32 or ord(c) == 127 for c in raw)
        or any(p in {"", ".", ".."} or p.endswith((".", " ")) for p in raw.split("/"))
    ):
        raise ValueError("invalid_project_path")
    for part in PurePosixPath(raw).parts:
        if re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(?:\..*)?", part):
            raise ValueError("invalid_project_path")
        if any(c in '<>"|?*' for c in part) or part.casefold() == ".git":
            raise ValueError("invalid_project_path")
    return raw


class BrowserStep(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["click", "type"]
    selector: str = Field(min_length=1, max_length=300)
    text: str = Field(default="", max_length=2000)


class ProjectAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    tool: Literal[
        "write_file",
        "read_file",
        "list_files",
        "remember",
        "finish",
        "blocked",
        "list_sources",
        "read_source",
        "find_source",
        "run",
        "read_build_log",
        "browser",
        "follow_source",
        "edit_file",
        "search_files",
        "read_requirements",
        "list_requirements",
        "mark_requirement",
        "scaffold_app",
        "build_project",
        "search_web",
        "open_url",
        "inspect_image",
        "download_file",
        "transcribe_media",
        "read_asset",
        "list_assets",
        "assemble_transcript",
    ]
    summary: str = Field(min_length=1, max_length=4000)
    path: str | None = Field(default=None, max_length=240)
    content: str | None = Field(default=None, max_length=MAX_FILE_BYTES)
    expected_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    title: str | None = Field(default=None, max_length=200)
    offset: int = Field(default=0, ge=0, le=768 * 1024**2)
    start_seconds: float = Field(default=0.0, ge=0, le=604800, allow_inf_nan=False)
    duration_seconds: float = Field(default=300.0, ge=1, le=900, allow_inf_nan=False)
    source_id: str | None = Field(default=None, max_length=20, pattern=r"^S[1-9][0-9]*$")
    argv: list[str] | None = Field(default=None, min_length=1, max_length=128)
    artifacts: list[str] = Field(default_factory=list, max_length=2)
    timeout_seconds: int = Field(default=300, ge=1, le=900)
    execution_id: str | None = Field(default=None, pattern=r"^[a-f0-9-]{36}$")
    old_text: str | None = Field(default=None, max_length=MAX_FILE_BYTES)
    new_text: str | None = Field(default=None, max_length=MAX_FILE_BYTES)
    query: str | None = Field(default=None, min_length=1, max_length=500)
    url: str | None = Field(default=None, min_length=1, max_length=4096)
    requirement_id: int = Field(default=1, ge=1, le=10000)
    evidence_paths: list[str] = Field(default_factory=list, max_length=12)
    platform: Literal["android", "windows"] = "android"
    target: Literal["apk", "exe", "apps"] = "apk"

    link_index: int = Field(default=0, ge=0, le=59)
    browser_steps: list[BrowserStep] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def valid_arguments(self):
        if self.tool != "read_asset" and self.offset > MAX_FILE_BYTES:
            raise ValueError("offset_out_of_range")
        if self.tool in {"transcribe_media", "read_asset", "assemble_transcript"}:
            safe_path(self.path or "")
            if not self.path.startswith(("inputs/", "receipts/")):
                raise ValueError("saved_input_or_receipt_path_required")
            allowed = {"tool", "summary", "path"} | (
                {"start_seconds", "duration_seconds"}
                if self.tool == "transcribe_media"
                else {"offset"}
                if self.tool == "read_asset"
                else set()
            )
            if any(
                getattr(self, key) != field.get_default(call_default_factory=True)
                for key, field in type(self).model_fields.items()
                if key not in allowed
            ):
                raise ValueError("unexpected_asset_tool_argument")
        if self.tool == "list_assets":
            allowed = {"tool", "summary", "offset", "query"}
            if any(
                getattr(self, key) != field.get_default(call_default_factory=True)
                for key, field in type(self).model_fields.items()
                if key not in allowed
            ):
                raise ValueError("unexpected_asset_tool_argument")
        if self.tool in {"write_file", "read_file", "browser", "edit_file", "inspect_image"}:
            safe_path(self.path or "")
        if self.tool == "edit_file" and (
            not self.old_text or self.new_text is None or not self.expected_sha256
        ):
            raise ValueError("edit_requires_exact_old_text_new_text_and_current_hash")
        if self.tool in {"search_files", "search_web", "find_source"} and not self.query:
            raise ValueError("search_query_required")
        if self.tool in {"open_url", "download_file"} and not self.url:
            raise ValueError("public_url_required")
        if self.tool == "download_file":
            safe_path(self.path or "")
            self.path = self.path.removeprefix("inputs/")
            if "/" in self.path or len(self.path) > 160:
                raise ValueError("download_requires_filename_without_folders")
        if self.tool == "mark_requirement":
            if not self.content or len(self.content) > 2000 or not self.evidence_paths:
                raise ValueError("requirement_evidence_required")
            for path in self.evidence_paths:
                safe_path(path)
        if self.tool in {"write_file", "remember"} and self.content is None:
            raise ValueError("content_required")
        if self.tool == "remember" and (not self.title or len(self.content) > 4000):
            raise ValueError("invalid_project_memory")
        if self.tool in {"read_source", "follow_source", "find_source"} and not self.source_id:
            raise ValueError("source_id_required")
        if self.content is not None and len(self.content.encode()) > MAX_FILE_BYTES:
            raise ValueError("file_too_large")
        if self.tool == "run":
            if (
                not self.argv
                or not self.argv[0]
                or any("\0" in a for a in self.argv)
                or sum(len(a.encode()) for a in self.argv) > 8192
            ):
                raise ValueError("invalid_sandbox_command")
            for path in self.artifacts:
                safe_path(path)
            if len(set(self.artifacts)) != len(self.artifacts):
                raise ValueError("duplicate_artifact_path")
        if self.tool == "read_build_log" and not self.execution_id:
            raise ValueError("execution_id_required")
        return self


def new_file_path_pattern(paths):
    """Exclude exact existing names using a regular trie, without lookarounds.

    The runtime grammar supports character classes and alternatives, not JSON
    Schema's `not` or regex lookahead. Prefixes and extensions remain selectable;
    ordinary path validation and the transaction still decide whether they exist.
    """
    root = {}
    for path in paths:
        node = root
        for char in path:
            node = node.setdefault(char, {})
        node[None] = True

    def escape(char):
        return "\\" + char if char in r"\.^$*+?{}[]|()" else char

    def class_escape(char):
        return f"\\x{ord(char):02x}" if char in "\\]-^" else char

    # GBNF patterns operate on serialized JSON, not decoded string values.
    # Never let a path consume a quote/backslash and inject another JSON field.
    forbidden = r'"\x5c\x00-\x1f'
    path_char = "[^" + forbidden + "]"
    choices = []

    def walk(node, prefix, depth):
        remaining = 240 - depth
        children = sorted(c for c in node if c is not None)
        if prefix and None not in node:
            choices.append(prefix)
        if not remaining:
            return
        if not children:
            choices.append(prefix + path_char + "{1," + str(remaining) + "}")
            return
        choices.append(prefix + "[^" + forbidden + "".join(class_escape(c) for c in children)
                       + "]" + path_char + "{0," + str(remaining - 1) + "}")
        for char in children:
            walk(node[char], prefix + escape(char), depth + 1)

    # Keep alternatives flat. An optional group around a large subtree expands
    # into thousands of grammar rules and exceeds the runtime parser's repetition
    # complexity bound, even when schema-to-grammar conversion succeeds.
    walk(root, "", 0)
    return "^(" + "|".join(choices) + ")$"



def action_schema(
    file_hashes=None,
    reference_sources=False,
    isolated_execution=False,
    follow_links=False,
    specification=False,
    web_research=False,
    file_paths=None,
    download_urls=None,
    asset_paths=None,
    completion_only=False,
    already_visible_read=None,
    visible_requirement_page=None,
    requirement_lengths=None,
    file_revisions=None,
    visible_read_pages=None,
):
    """Make tool-specific required arguments visible to the runtime's JSON grammar."""
    base = ProjectAction.model_json_schema()["properties"]
    variants = []
    tools = [
        ("write_file", ["path", "content"], ["expected_sha256"]),
        ("read_file", ["path"], ["offset"]),
        ("edit_file", ["path", "old_text", "new_text", "expected_sha256"], []),
        ("search_files", ["query"], ["offset"]),
        ("remember", ["title", "content"], []),
        ("list_files", [], ["offset"]),
        ("finish", [], []),
        ("blocked", [], []),
    ]
    if specification:
        tools.extend(
            [
                ("read_requirements", ["requirement_id"], ["offset"]),
                ("list_requirements", [], ["offset"]),
                ("mark_requirement", ["requirement_id", "content", "evidence_paths"], []),
            ]
        )
    if reference_sources:
        tools.extend([("list_sources", [], ["offset"]), ("read_source", ["source_id"], ["offset"])])
        tools.append(("find_source", ["source_id", "query"], ["offset"]))
    if follow_links:
        tools.append(("follow_source", ["source_id", "link_index"], []))
    if web_research:
        tools.extend([("search_web", ["query"], []), ("open_url", ["url"], [])])
        if isolated_execution:
            tools.append(("download_file", ["url", "path"], []))
    if isolated_execution:
        tools.extend(
            [
                ("run", ["argv"], ["artifacts", "timeout_seconds"]),
                ("inspect_image", ["path"], []),
                ("transcribe_media", ["path"], ["start_seconds", "duration_seconds"]),
                ("read_asset", ["path"], ["offset"]),
                ("list_assets", [], ["offset", "query"]),
                ("assemble_transcript", ["path"], []),
                ("browser", ["path"], ["browser_steps"]),
                ("read_build_log", ["execution_id"], ["offset"]),
                ("scaffold_app", ["platform", "title"], []),
                ("build_project", ["target"], []),
            ]
        )
    if completion_only:
        tools = [("finish", [], []), ("blocked", [], [])]
    for tool, required, optional in tools:
        if file_paths == [] and tool in {"read_file", "edit_file", "browser"}:
            continue
        if asset_paths == [] and tool in {"transcribe_media", "read_asset", "assemble_transcript"}:
            continue
        properties = {"tool": {"const": tool}, "summary": base["summary"]}
        for key in required + optional:
            definition = dict(base[key])
            if key in required and "anyOf" in definition:
                definition = next(v for v in definition["anyOf"] if v.get("type") != "null")
            properties[key] = definition
        if "offset" in properties and tool != "read_asset":
            properties["offset"]["maximum"] = MAX_FILE_BYTES
        if (
            tool in {"transcribe_media", "read_asset", "assemble_transcript"}
            and asset_paths is not None
        ):
            properties["path"] = {"enum": asset_paths}
        if tool in {"write_file", "edit_file"} and file_hashes is not None:
            # A model cannot invent a compare-and-swap token. Only the current task's
            # observed revisions are valid candidates; the transaction rechecks them.
            properties["expected_sha256"] = (
                {"enum": [None, *file_hashes] if tool == "write_file" else file_hashes}
                if file_hashes or tool == "write_file"
                else {"type": "string", "pattern": "^[a-f0-9]{64}$"}
            )
        if tool == "write_file" and specification:
            properties["expected_sha256"] = {"type": "null"}
            if file_paths:
                properties["path"] = {
                    "type": "string", "minLength": 1, "maxLength": 240,
                    "pattern": new_file_path_pattern(file_paths),
                }
        if tool in {"read_file", "edit_file", "browser"} and file_paths is not None:
            properties["path"] = {"enum": file_paths}
        if tool == "read_file" and file_paths is not None and already_visible_read is not None:
            visible = (
                {already_visible_read} if isinstance(already_visible_read, str)
                else set(already_visible_read)
            )
            remaining = [p for p in file_paths if p not in visible]
            if not remaining:
                continue
            properties["path"] = {"enum": remaining}
        if tool == "read_file" and file_paths is not None and visible_read_pages:
            for path in properties["path"]["enum"]:
                low = 0
                excluded = sorted(set(visible_read_pages.get(path, ())))
                for stop in [*excluded, MAX_FILE_BYTES + 1]:
                    if low < stop:
                        choice = copy.deepcopy(properties)
                        choice["path"] = {"const": path}
                        choice["offset"] = {"type": "integer", "minimum": low,
                                            "maximum": stop - 1}
                        needed = ["tool", "summary", *required]
                        if low:
                            needed.append("offset")
                        variants.append({"type": "object", "properties": choice,
                                         "required": needed, "additionalProperties": False})
                    low = stop + 1
            continue
        if tool == "download_file" and download_urls:
            properties["url"] = {"enum": download_urls}
        if tool == "download_file":
            properties["path"] = {
                "type": "string",
                "minLength": 1,
                "maxLength": 167,
                "pattern": r"^(inputs/)?[^/\\]+$",
            }
        if tool == "edit_file" and file_revisions is not None:
            # Bind each compare-and-swap token to its own path. Independent enums
            # permit a valid hash from an unrelated file, which execution rejects.
            # The transaction still checks the revision again before applying edits.
            for path in file_paths if file_paths is not None else file_revisions:
                if path not in file_revisions:
                    continue
                choice = copy.deepcopy(properties)
                choice["path"] = {"const": path}
                choice["expected_sha256"] = {"const": file_revisions[path]}
                variants.append({"type": "object", "properties": choice,
                                 "required": ["tool", "summary", *required],
                                 "additionalProperties": False})
            continue
        if tool == "read_requirements" and requirement_lengths is not None:
            for ordinal, length in enumerate(requirement_lengths, 1):
                ranges = [(0, length)]
                if visible_requirement_page and visible_requirement_page[0] == ordinal:
                    offset = visible_requirement_page[1]
                    end = visible_requirement_page[-1]
                    ranges = [(0, min(length, offset - 1)), (end + 1, length)]
                for low, high in ranges:
                    if low > high:
                        continue
                    choice = copy.deepcopy(properties)
                    choice["requirement_id"] = {"const": ordinal}
                    choice["offset"] = {"type": "integer", "minimum": low, "maximum": high}
                    needed = ["tool", "summary", *required]
                    if low > 0:
                        needed.append("offset")
                    variants.append({"type": "object", "properties": choice,
                                     "required": needed, "additionalProperties": False})
            continue
        if tool == "read_requirements" and visible_requirement_page is not None:
            ordinal, offset = visible_requirement_page[:2]
            end = visible_requirement_page[-1]
            # Exclude the verified displayed pair or end-of-section suffix.
            ranges = [
                ("requirement_id", 1, ordinal - 1),
                ("requirement_id", ordinal + 1, 10000),
                ("offset", 0, offset - 1),
                ("offset", end + 1, MAX_FILE_BYTES),
            ]
            for field, low, high in ranges:
                if low > high:
                    continue
                choice = copy.deepcopy(properties)
                choice[field] = {"type": "integer", "minimum": low, "maximum": high}
                needed = ["tool", "summary", *required]
                if field == "offset":
                    choice["requirement_id"] = {"const": ordinal}
                    if low > 0:
                        needed.append("offset")
                variants.append({"type": "object", "properties": choice,
                                 "required": needed, "additionalProperties": False})
            continue
        variants.append(
            {
                "type": "object",
                "properties": properties,
                "required": ["tool", "summary", *required],
                "additionalProperties": False,
            }
        )
    return {"oneOf": variants, "$defs": ProjectAction.model_json_schema().get("$defs", {})}


def source_page(row, path, offset):
    excerpt = row["content"][offset:].encode()[:3000].decode("utf-8", errors="ignore")
    return {
        "path": path,
        "sha256": row["sha256"],
        "content": excerpt,
        "offset": offset,
        "total_characters": len(row["content"]),
        "next_offset": offset + len(excerpt)
        if offset + len(excerpt) < len(row["content"])
        else None,
        "has_more": offset + len(excerpt) < len(row["content"]),
    }


class ProjectTools:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def apply(db, task_id, action):
        """Called only inside the same transaction that records the step and checkpoint."""
        tool = action.tool
        if tool == "read_asset":
            from .work_asset_tools import read_asset

            return read_asset(db, task_id, action.path, action.offset)
        if tool == "list_assets":
            from .work_asset_tools import list_assets

            return list_assets(db, task_id, action.offset, action.query)
        if tool in {"transcribe_media", "assemble_transcript"}:
            return {"error": "transcription_requires_isolated_work"}
        if tool in {"read_requirements", "list_requirements", "mark_requirement"}:
            from .work_specs import WorkSpecs

            if tool == "read_requirements":
                return WorkSpecs.read(db, task_id, action.requirement_id, action.offset)
            if tool == "list_requirements":
                return WorkSpecs.listing(db, task_id, action.offset)
            return WorkSpecs.coverage(db, task_id, action)
        if tool == "scaffold_app":
            from .app_builder import scaffold

            return scaffold(db, task_id, action)
        if tool == "build_project":
            return {"error": "sandbox_not_ready"}
        if tool == "search_files":
            hits = []
            for file in db.execute(
                "SELECT path,content,sha256 FROM work_files WHERE task_id=? ORDER BY path",
                (task_id,),
            ):
                start = 0
                while len(hits) < action.offset + 11:
                    index = file["content"].find(action.query, start)
                    if index < 0:
                        break
                    hits.append(
                        {
                            "path": file["path"],
                            "offset": index,
                            "sha256": file["sha256"],
                            "excerpt": file["content"][max(0, index - 80) : index + 200],
                        }
                    )
                    start = index + len(action.query)
                if len(hits) >= action.offset + 11:
                    break
            return {
                "matches": hits[action.offset : action.offset + 10],
                "next_offset": action.offset + 10 if len(hits) > action.offset + 10 else None,
            }
        if tool == "follow_source":
            from .work_research import WorkResearch

            return WorkResearch.follow(db, task_id, action.source_id, action.link_index)
        if tool == "find_source":
            return WorkReferences.find(db, task_id, action.source_id, action.query, action.offset)
        if tool == "run":
            return {"error": "sandbox_not_ready"}
        if tool == "read_build_log":
            row = db.execute(
                "SELECT result FROM work_executions WHERE id=? AND task_id=?",
                (action.execution_id, task_id),
            ).fetchone()
            if not row or row[0] is None:
                return {"error": "execution_not_found"}
            text = row[0]
            excerpt = text[action.offset :].encode()[:3000].decode("utf-8", errors="ignore")
            return {
                "execution_id": action.execution_id,
                "content": excerpt,
                "offset": action.offset,
                "next_offset": action.offset + len(excerpt)
                if action.offset + len(excerpt) < len(text)
                else None,
                "has_more": action.offset + len(excerpt) < len(text),
                "total_characters": len(text),
            }
        if tool in {"finish", "blocked"}:
            return {"status": tool, "summary": action.summary, "execution_verified": False}
        if tool == "list_sources":
            return WorkReferences.tool_list(db, task_id, action.offset)
        if tool == "read_source":
            return WorkReferences.read(db, task_id, action.source_id, action.offset)
        if tool == "list_files":
            files = [
                dict(r)
                for r in db.execute(
                    "SELECT path,sha256,revision,length(CAST(content AS BLOB)) AS bytes "
                    "FROM work_files WHERE task_id=? ORDER BY path LIMIT 16 OFFSET ?",
                    (task_id, action.offset),
                )
            ]
            total = db.execute(
                "SELECT count(*) FROM work_files WHERE task_id=?", (task_id,)
            ).fetchone()[0]
            return {
                "files": files,
                "total": total,
                "next_offset": action.offset + len(files)
                if action.offset + len(files) < total
                else None,
            }
        if tool == "remember":
            from .storage import uid

            now, mid = utcnow(), uid()
            db.execute(
                "INSERT INTO memories VALUES(?,?,?,?,?,?,?,?)",
                (mid, task_id, action.title, action.content, "agent", 1, now, now),
            )
            return {"memory_id": mid, "scope": "project", "source": "agent"}
        row = db.execute(
            "SELECT * FROM work_files WHERE task_id=? AND path=?", (task_id, action.path)
        ).fetchone()
        if tool == "edit_file":
            if not row or row["sha256"] != action.expected_sha256:
                return {"error": "file_changed_read_before_overwrite"}
            count = row["content"].count(action.old_text)
            if count != 1:
                return {
                    "error": "edit_match_not_unique",
                    "matches": count,
                    "help": (
                        "No edit was applied. Provide exact, uniquely matching old_text. "
                        "A read_file page may end mid-expression; that is not a source error. "
                        "Reuse displayed source; follow its next_offset for unseen text "
                        "instead of repeating the same page or inventing its continuation."
                    ),
                }
            if action.old_text == action.new_text:
                return {
                    **source_page(row, action.path, 0),
                    "error": "edit_has_no_change",
                    "help": "The proposed replacement equals the original text. No bytes changed. "
                    "The current source page is attached. If the desired line already exists, "
                    "implement the missing code it refers to, or test the behavior. Only edit "
                    "this location again if the replacement actually changes it.",
                }
            content = row["content"].replace(action.old_text, action.new_text, 1)
            if len(content.encode()) > MAX_FILE_BYTES:
                return {"error": "file_too_large"}
            return ProjectTools.apply(
                db,
                task_id,
                ProjectAction(
                    tool="write_file",
                    path=action.path,
                    content=content,
                    expected_sha256=action.expected_sha256,
                    summary=action.summary,
                ),
            )
        if tool == "read_file":
            if not row:
                return {"error": "file_not_found"}
            return source_page(row, action.path, action.offset)
        if (row and row["sha256"] != action.expected_sha256) or (
            not row and action.expected_sha256
        ):
            return {"error": "file_changed_read_before_overwrite"}
        paths = [
            r[0] for r in db.execute("SELECT path FROM work_files WHERE task_id=?", (task_id,))
        ]
        if any(p.casefold() == action.path.casefold() and p != action.path for p in paths):
            return {"error": "case_conflicting_path"}
        for existing in paths:
            if existing.casefold().startswith(
                action.path.casefold() + "/"
            ) or action.path.casefold().startswith(existing.casefold() + "/"):
                return {"error": "path_is_file_or_directory"}
        total = db.execute(
            "SELECT COALESCE(SUM(length(CAST(content AS BLOB))),0) FROM work_files WHERE task_id=?",
            (task_id,),
        ).fetchone()[0]
        size = len(action.content.encode())
        if (
            not row
            and len(paths) >= MAX_FILES
            or total - (len(row["content"].encode()) if row else 0) + size > MAX_PROJECT_BYTES
        ):
            return {"error": "project_storage_limit"}
        sha = hashlib.sha256(action.content.encode()).hexdigest()
        revision = row["revision"] + 1 if row else 1
        db.execute(
            "INSERT INTO work_files VALUES(?,?,?,?,?,?) ON CONFLICT(task_id,path) "
            "DO UPDATE SET content=excluded.content,sha256=excluded.sha256,"
            "revision=excluded.revision,updated_at=excluded.updated_at",
            (task_id, action.path, action.content, sha, revision, utcnow()),
        )
        return {"path": action.path, "sha256": sha, "bytes": size, "revision": revision}

    def export(self, task_id):
        output = io.BytesIO()
        with self.store.transaction() as db:
            rows = db.execute(
                "SELECT * FROM work_files WHERE task_id=? ORDER BY path", (task_id,)
            ).fetchall()
            task = dict(db.execute("SELECT * FROM work_tasks WHERE id=?", (task_id,)).fetchone())
            sources = WorkReferences.export(db, task_id)
            build = db.execute(
                "SELECT target FROM work_build_profiles WHERE task_id=?", (task_id,)
            ).fetchone()
            evidence = None
            if build:
                from .builds import WorkBuilds

                evidence = WorkBuilds.finish_evidence(db, task_id, build[0])
            with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
                for row in rows:
                    archive.writestr("project/" + safe_path(row["path"]), row["content"])
                originals = db.execute(
                    "SELECT * FROM work_inputs WHERE task_id=?", (task_id,)
                ).fetchall()
                for original in originals:
                    archive.writestr("inputs/" + safe_path(original["name"]), original["original"])
                if originals:
                    archive.writestr(
                        "inputs.json",
                        canonical(
                            [
                                {
                                    "name": r["name"],
                                    "sha256": r["sha256"],
                                    "extraction": json.loads(r["extraction"]),
                                }
                                for r in originals
                            ]
                        ),
                    )
                if sources:
                    archive.writestr(
                        "sources.json",
                        canonical({"format": "dsgpt-work-sources-v1", "sources": sources}),
                    )
                archive.writestr(
                    "manifest.json",
                    canonical(
                        {
                            "task": task,
                            "execution_verified": False,
                            "build_evidence": evidence,
                            "reference_sources": len(sources),
                            "files": [
                                {k: r[k] for k in ("path", "sha256", "revision")} for r in rows
                            ],
                            "warning": "See recorded build results; native artifact execution is "
                            "not verified."
                            if evidence
                            else "Generated source has not been executed or tested.",
                        }
                    ),
                )
                from .work_specs import WorkSpecs

                spec = WorkSpecs.export(db, task_id)
                if spec:
                    archive.writestr("requirements.txt", task["requirements"])
                    archive.writestr("requirements-review.json", canonical(spec))
        return output.getvalue()
