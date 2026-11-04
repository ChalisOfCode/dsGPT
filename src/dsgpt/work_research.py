"""Task-scoped public research: only an explicit user query and saved public links."""

import asyncio
import json

from .storage import utcnow
from .web_retrieval import ResearchError, public_url
from .work_references import WorkReferences


class WorkResearch:
    def __init__(self, store, search=None):
        self.store, self.search = store, search

    def recover(self):
        with self.store.transaction() as db:
            db.execute(
                "UPDATE work_research SET status='failed',error_code='search_interrupted' "
                "WHERE status='running'"
            )

    def status(self, task_id):
        row = self.store.one("SELECT * FROM work_research WHERE task_id=?", (task_id,))
        if row:
            row["follow_links"] = bool(row["follow_links"])
        return row

    async def step(self, task_id):
        query = self.status(task_id)
        if not query or query["status"] != "pending":
            return False
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT * FROM work_tasks WHERE id=? AND status='queued'", (task_id,)
            ).fetchone()
            if not row:
                return True
            revision = row["revision"] + 1
            db.execute(
                "UPDATE work_tasks SET status='running',revision=?,updated_at=? WHERE id=?",
                (revision, utcnow(), task_id),
            )
            db.execute("UPDATE work_research SET status='running' WHERE task_id=?", (task_id,))
        urls, error = [], None
        try:
            if not self.search:
                raise ResearchError("research_search_not_configured")
            result = await self.search.search(query["public_query"])
            for item in result["results"][:6]:
                urls.append(public_url(item["url"]))
        except asyncio.CancelledError:
            with self.store.transaction() as db:
                db.execute(
                    "UPDATE work_research SET status='failed',error_code='search_interrupted' "
                    "WHERE task_id=?",
                    (task_id,),
                )
            raise
        except Exception as exc:
            error = str(exc) if isinstance(exc, ResearchError) else "work_search_failed"
        with self.store.transaction() as db:
            current = db.execute(
                "SELECT status,revision FROM work_tasks WHERE id=?", (task_id,)
            ).fetchone()
            if current["status"] != "running" or current["revision"] != revision:
                db.execute(
                    "UPDATE work_research SET status='failed',error_code='search_result_discarded' "
                    "WHERE task_id=?",
                    (task_id,),
                )
                return True
            WorkReferences.append(db, task_id, urls)
            db.execute(
                "UPDATE work_research SET status=?,error_code=? WHERE task_id=?",
                ("failed" if error else "completed", error, task_id),
            )
            db.execute(
                "UPDATE work_tasks SET status='queued',revision=revision+1,updated_at=? WHERE id=?",
                (utcnow(), task_id),
            )
        return True

    @staticmethod
    def follow(db, task_id, source_id, index):
        if not WorkReferences.allow_links(db, task_id):
            return {"error": "link_following_not_enabled"}
        source = db.execute(
            "SELECT document FROM work_sources WHERE task_id=? AND source_id=? "
            "AND status='retrieved'",
            (task_id, source_id),
        ).fetchone()
        links = json.loads(source[0]).get("links", []) if source else []
        if not 0 <= index < len(links):
            return {"error": "source_link_not_found"}
        url = public_url(links[index])
        prior = db.execute(
            "SELECT source_id,status FROM work_sources WHERE task_id=? AND url=?", (task_id, url)
        ).fetchone()
        if prior:
            return dict(prior)  # Never resurrect a removed source through another link.
        count = db.execute(
            "SELECT count(*) FROM work_sources WHERE task_id=?", (task_id,)
        ).fetchone()[0]
        if count >= 256:
            return {"error": "source_limit_reached", "help": "Up to 256 sources per task."}
        WorkReferences.append(db, task_id, [url])
        return {"url": url, "status": "pending"}
