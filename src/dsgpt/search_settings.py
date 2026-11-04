"""Owner-managed local search address and explicit, public-query readiness checks."""

import asyncio
import json

from fastapi import HTTPException

from .storage import canonical, utcnow
from .web_retrieval import LocalSearch, ResearchError, local_search_origin

TEST_QUERY = "SearXNG documentation"


class SearchConfiguration:
    def __init__(self, store, search, configured_origin=None):
        self.store, self.search = store, search
        self.configured_origin = local_search_origin(configured_origin)
        self.check_lock = asyncio.Lock()
        self.search.origin = self.effective_origin(self.row())

    def row(self):
        return self.store.one("SELECT * FROM search_settings WHERE id=1")

    def effective_origin(self, row):
        return local_search_origin(self.configured_origin or row["origin"])

    def status(self):
        row = self.row()
        origin = self.effective_origin(row)
        probe = json.loads(row["probe"]) if row["probe"] else None
        if probe and (probe["origin"] != origin or probe["revision"] != row["revision"]):
            probe = None
        return {
            "origin": origin,
            "revision": row["revision"],
            "updated_at": row["updated_at"] or None,
            "configuration_owned": self.configured_origin is not None,
            "configured": origin is not None,
            "test_query": TEST_QUERY,
            "check_in_progress": self.check_lock.locked(),
            "last_check": {k: v for k, v in probe.items() if k not in {"origin", "revision"}}
            if probe
            else None,
        }

    def update(self, origin, revision):
        try:
            origin = local_search_origin(origin)
        except ValueError as exc:
            raise HTTPException(
                422, "Use a literal loopback HTTP address with an explicit port"
            ) from exc
        with self.store.transaction() as db:
            row = db.execute("SELECT * FROM search_settings WHERE id=1").fetchone()
            if self.configured_origin is not None:
                raise HTTPException(409, "Search is managed by the backend configuration file")
            if revision != row["revision"]:
                raise HTTPException(409, "Search settings changed; reload before editing")
            active = db.execute(
                "SELECT 1 FROM runs r JOIN run_research s ON s.run_id=r.id "
                "WHERE r.status IN ('queued','running') "
                "AND json_extract(s.definition,'$.search')=1 LIMIT 1"
            ).fetchone()
            active_work = db.execute(
                "SELECT 1 FROM work_research r JOIN work_tasks t ON t.id=r.task_id "
                "WHERE r.status IN ('pending','running') AND r.public_query IS NOT NULL "
                "AND t.status IN ('queued','running') LIMIT 1"
            ).fetchone()
            if active or active_work:
                raise HTTPException(
                    409, "Wait for or cancel accepted web research before changing search"
                )
            db.execute(
                "UPDATE search_settings SET origin=?,revision=revision+1,updated_at=?,probe=NULL "
                "WHERE id=1",
                (origin, utcnow()),
            )
        # No await separates the committed configuration from the live adapter update.
        self.search.origin = origin
        return self.status()

    async def check(self, revision):
        row = self.row()
        origin = self.effective_origin(row)
        if revision != row["revision"]:
            raise HTTPException(409, "Search settings changed; refresh before testing")
        if not origin:
            raise HTTPException(409, "Configure the local search service first")
        if self.check_lock.locked():
            raise HTTPException(409, "A search test is already in progress")
        async with self.check_lock:
            try:
                # Pin this accepted test to its original service across awaited I/O.
                adapter = LocalSearch(origin, self.search.transport_factory)
                result = await adapter.search(TEST_QUERY)
                count, failures = len(result["results"]), result["engine_failures"]
                state = "partial" if failures else "passed" if count else "empty"
                error = None
            except ResearchError as exc:
                state, count, failures, error = "failed", 0, 0, str(exc)
            except Exception:
                state, count, failures, error = "failed", 0, 0, "research_search_failed"
            probe = {
                "origin": origin,
                "revision": revision,
                "checked_at": utcnow(),
                "status": state,
                "result_count": count,
                "engine_failures": failures,
                "error_code": error,
            }
            with self.store.transaction() as db:
                current = db.execute("SELECT * FROM search_settings WHERE id=1").fetchone()
                if current["revision"] != revision or self.effective_origin(current) != origin:
                    raise HTTPException(
                        409, "Settings changed during the test; its result was discarded"
                    )
                db.execute("UPDATE search_settings SET probe=? WHERE id=1", (canonical(probe),))
        return self.status()
