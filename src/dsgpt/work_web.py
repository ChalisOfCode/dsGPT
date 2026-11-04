"""Repeatable public research during Work, with durable per-action receipts.

Only the public search query/URL leaves the process. No project upload, cookies,
host browser or host shell is available. Web On explicitly permits queries derived
from task context; Web Auto with attachments remains disabled at task creation.
"""

import asyncio
import json

from .storage import canonical, utcnow
from .web_retrieval import ResearchError, public_url
from .work_media import WorkMedia
from .work_references import WorkReferences

MAX_SEARCHES = 64
MAX_SOURCES = 256


class WorkWeb:
    def __init__(self, store, research, references):
        self.store, self.research, self.references = store, research, references
        self.media = WorkMedia(store)

    def enabled(self, task_id):
        return bool(
            self.store.one(
                "SELECT 1 FROM generation_options WHERE kind='work' AND id=? "
                "AND web_mode IN ('auto','on')",
                (task_id,),
            )
        )

    def recover(self):
        with self.store.transaction() as db:
            db.execute(
                "UPDATE work_web_calls SET status='done',result=?,updated_at=? "
                "WHERE status='running'",
                (
                    canonical(
                        {
                            "error": "research_interrupted",
                            "help": "The request may have reached the source. "
                            "Choose a new action if needed.",
                        }
                    ),
                    utcnow(),
                ),
            )

    def pending(self, task_id, step):
        row = self.store.one(
            "SELECT action,result FROM work_web_calls WHERE task_id=? AND step=? "
            "AND status='done' AND recorded=0",
            (task_id, step),
        )
        return (json.loads(row["action"]), json.loads(row["result"])) if row else None

    def current_result(self, task_id, action, result):
        """A removed/refreshed page cannot reappear through an old tool receipt."""
        result = dict(result)
        if action.get("tool") == "download_file" and result.get("sha256"):
            current = self.store.one(
                "SELECT sha256 FROM work_inputs WHERE task_id=? AND name=?",
                (task_id, action.get("path")),
            )
            if not current or current["sha256"] != result["sha256"]:
                return {"error": "download_snapshot_no_longer_current"}
        if action.get("tool") == "open_url" and result.get("source_id"):
            current = self.store.one(
                "SELECT status,generation FROM work_sources WHERE task_id=? AND source_id=?",
                (task_id, result["source_id"]),
            )
            if (
                not current
                or current["status"] != "retrieved"
                or current["generation"] != result.get("generation")
            ):
                return {"error": "source_snapshot_no_longer_current"}
        if action.get("tool") == "search_web":
            result["results"] = [
                item
                for item in result.get("results", [])
                if self.store.one(
                    "SELECT 1 FROM work_sources WHERE task_id=? AND source_id=? "
                    "AND status!='removed'",
                    (task_id, item.get("source_id")),
                )
            ]
        return result

    async def execute(self, task_id, step, action):
        definition = canonical(action.model_dump())
        with self.store.transaction() as db:
            prior = db.execute(
                "SELECT * FROM work_web_calls WHERE task_id=? AND step=?", (task_id, step)
            ).fetchone()
            if prior:
                if prior["action"] != definition:
                    return {"error": "research_step_conflict"}
                return (
                    json.loads(prior["result"])
                    if prior["result"]
                    else {"error": "research_already_running"}
                )
            task = db.execute(
                "SELECT status,revision FROM work_tasks WHERE id=?", (task_id,)
            ).fetchone()
            if not task or task["status"] != "running":
                return {"error": "research_task_not_running"}
            revision = task["revision"]
            db.execute(
                "INSERT INTO work_web_calls VALUES(?,?,?,?,'running',NULL,0,?,?)",
                (task_id, step, definition, revision, utcnow(), utcnow()),
            )
        payload, document, error = None, None, None
        temporary, downloaded = None, None
        try:
            if not self.enabled(task_id):
                raise ResearchError("work_web_disabled")
            if action.tool == "download_file":
                if not self.store.one(
                    "SELECT 1 FROM work_build_profiles WHERE task_id=?", (task_id,)
                ):
                    raise ResearchError("download_requires_isolated_work")
                url = public_url(action.url)
                payload = self.media.cached(task_id, url, action.path)
                if payload is None:
                    temporary = self.media.temporary()
                    payload, downloaded = await self.media.fetch(url, action.path, temporary.name)
            elif action.tool == "search_web":
                count = self.store.one(
                    "SELECT count(*) AS n FROM work_web_calls WHERE task_id=? "
                    "AND json_extract(action,'$.tool')='search_web'",
                    (task_id,),
                )["n"]
                if count > MAX_SEARCHES:
                    raise ResearchError("work_search_budget_reached")
                if not self.research.search:
                    raise ResearchError("research_search_not_configured")
                payload = await self.research.search.search(action.query)
            else:
                url = public_url(action.url)
                source = self.store.one(
                    "SELECT * FROM work_sources WHERE task_id=? AND url=?", (task_id, url)
                )
                if source and source["status"] == "removed":
                    raise ResearchError("source_removed")
                if source and source["status"] == "retrieved":
                    with self.store.connect() as db:
                        payload = WorkReferences.read(db, task_id, source["source_id"])
                else:
                    if self.references.counts(task_id)["total"] >= MAX_SOURCES and not source:
                        raise ResearchError("source_limit_reached")
                    document, error = await self.references.fetch({"task_id": task_id, "url": url})
                    payload = {
                        "url": url,
                        "source_generation": source["generation"] if source else None,
                    }
        except asyncio.CancelledError:
            if temporary:
                temporary.cleanup()
            with self.store.transaction() as db:
                db.execute(
                    "UPDATE work_web_calls SET status='done',result=?,updated_at=? "
                    "WHERE task_id=? AND step=?",
                    (canonical({"error": "research_interrupted"}), utcnow(), task_id, step),
                )
            raise
        except Exception as exc:
            error = str(exc) if isinstance(exc, ResearchError) else "work_research_failed"
        try:
            return self._save(task_id, step, action, revision, payload, document, error, downloaded)
        finally:
            if temporary:
                temporary.cleanup()

    def _save(self, task_id, step, action, revision, payload, document, error, downloaded):
        with self.store.transaction() as db:
            task = db.execute(
                "SELECT status,revision FROM work_tasks WHERE id=?", (task_id,)
            ).fetchone()
            if not task or task["status"] != "running" or task["revision"] != revision:
                result = {"error": "research_result_discarded"}
            elif not self.enabled(task_id):
                result = {"error": "work_web_disabled"}
            elif error:
                result = {
                    "error": error,
                    "query": action.query,
                    "url": action.url,
                    "help": (
                        "File not saved. Re-read the exact requested URL or an observed link; "
                        "never invent a replacement address. A player page is not a direct file."
                        if action.tool == "download_file"
                        else "This is not evidence. Try another public source or query."
                    ),
                }
            elif action.tool == "download_file":
                try:
                    result = (
                        self.media.save(db, task_id, action.path, payload, downloaded)
                        if downloaded
                        else self.current_result(task_id, action.model_dump(), payload)
                    )
                except ResearchError as exc:
                    result = {"error": str(exc)}
            elif action.tool == "search_web":
                result = self._save_search(db, task_id, action.query, payload)
            elif payload.get("source_id"):
                result = self.current_result(task_id, action.model_dump(), payload)
            else:
                source = db.execute(
                    "SELECT * FROM work_sources WHERE task_id=? AND url=?",
                    (task_id, payload["url"]),
                ).fetchone()
                if source and (
                    source["status"] == "removed"
                    or source["generation"] != payload["source_generation"]
                ):
                    result = {"error": "source_snapshot_no_longer_current"}
                else:
                    WorkReferences.append(db, task_id, [payload["url"]])
                    source = db.execute(
                        "SELECT * FROM work_sources WHERE task_id=? AND url=?",
                        (task_id, payload["url"]),
                    ).fetchone()
                    db.execute(
                        "UPDATE work_sources SET status='pending' WHERE task_id=? AND source_id=?",
                        (task_id, source["source_id"]),
                    )
                    WorkReferences.save(db, task_id, source["source_id"], document, None)
                    result = WorkReferences.read(db, task_id, source["source_id"])
            db.execute(
                "UPDATE work_web_calls SET status='done',result=?,updated_at=? "
                "WHERE task_id=? AND step=?",
                (canonical(result), utcnow(), task_id, step),
            )
        return result

    @staticmethod
    def _save_search(db, task_id, query, payload):
        results = []
        count = db.execute(
            "SELECT count(*) FROM work_sources WHERE task_id=?", (task_id,)
        ).fetchone()[0]
        for item in payload.get("results", [])[:6]:
            try:
                url = public_url(item["url"])
            except (ResearchError, KeyError, TypeError):
                continue
            source = db.execute(
                "SELECT * FROM work_sources WHERE task_id=? AND url=?", (task_id, url)
            ).fetchone()
            if source and source["status"] == "removed":
                continue
            if not source:
                if count >= MAX_SOURCES:
                    continue
                WorkReferences.append(db, task_id, [url])
                count += 1
                source = db.execute(
                    "SELECT * FROM work_sources WHERE task_id=? AND url=?", (task_id, url)
                ).fetchone()
            results.append(
                {
                    "source_id": source["source_id"],
                    "url": url,
                    "status": source["status"],
                    "title": str(item.get("title", ""))[:160],
                    "snippet": str(item.get("snippet", ""))[:320],
                }
            )
        return {
            "query": query,
            "results": results,
            "retrieved_at": payload.get("retrieved_at", utcnow()),
            "engine_failures": payload.get("engine_failures", 0),
            "source_limit_reached": count >= MAX_SOURCES,
            "suggested_read": {"tool": "read_source", "source_id": results[0]["source_id"]}
            if results
            else None,
            "next": "Read relevant source IDs before relying on snippets. "
            "Search again when a new question or error needs evidence.",
        }
