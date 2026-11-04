import asyncio
from uuid import uuid4

import pytest
from fastapi import HTTPException

from dsgpt.project_tools import ProjectAction, ProjectTools
from dsgpt.storage import Store
from dsgpt.work import WorkRegistry
from dsgpt.work_references import WorkReferences


class Search:
    def __init__(self):
        self.calls = []
        self.gate = asyncio.Event()
        self.gate.set()

    async def search(self, query):
        self.calls.append(query)
        await self.gate.wait()
        return {"results": [{"url": "https://example.org/reference"}]}


async def test_only_user_public_query_leaves_task_and_retries_are_idempotent(tmp_path):
    store = Store(tmp_path)
    work = WorkRegistry(store)
    identifier = str(uuid4())
    args = dict(public_query="Public documentation", follow_links=True, request_id=identifier)
    task = work.create("Private title", "PRIVATE SECRET requirements", **args)
    assert work.create("Private title", "PRIVATE SECRET requirements", **args)["id"] == task["id"]
    with pytest.raises(HTTPException):
        work.create(
            "Private title", "PRIVATE SECRET requirements", **{**args, "public_query": "Changed"}
        )
    search = Search()
    work.public_research.search = search
    with store.transaction() as db:
        db.execute("UPDATE work_tasks SET status='queued' WHERE id=?", (task["id"],))
    assert await work.public_research.step(task["id"])
    assert not await work.public_research.step(task["id"])
    assert search.calls == ["Public documentation"]
    assert store.one("SELECT url FROM work_sources")["url"] == "https://example.org/reference"
    assert store.one("SELECT status FROM work_tasks")["status"] == "queued"


async def test_pause_during_public_search_discards_late_result(tmp_path):
    store = Store(tmp_path)
    work = WorkRegistry(store)
    task = work.create("Private", "private", public_query="Public documentation")
    search = Search()
    search.gate.clear()
    work.public_research.search = search
    with store.transaction() as db:
        db.execute("UPDATE work_tasks SET status='queued'")
    job = asyncio.create_task(work.public_research.step(task["id"]))
    while not search.calls:
        await asyncio.sleep(0)
    with store.transaction() as db:
        db.execute("UPDATE work_tasks SET status='paused',revision=revision+1")
    search.gate.set()
    await job
    assert not store.all("SELECT * FROM work_sources")
    assert work.get(task["id"])["public_research"]["error_code"] == "search_result_discarded"
    work.revise(task["id"], work.get(task["id"])["revision"], retry_sources=True)
    assert work.public_research.status(task["id"])["status"] == "pending"


def test_following_requires_opt_in_and_uses_only_retained_link_indices(tmp_path):
    store = Store(tmp_path)
    work = WorkRegistry(store)
    disabled = work.create("Default", "private", reference_urls=["https://example.org/root"])
    allowed = work.create(
        "Enabled", "private", reference_urls=["https://example.org/root"], follow_links=True
    )
    with store.transaction() as db:
        for task in [disabled, allowed]:
            WorkReferences.save(
                db,
                task["id"],
                "S1",
                {"text": "Public source", "links": ["https://example.org/linked"]},
                None,
            )
        action = ProjectAction(
            tool="follow_source", source_id="S1", link_index=0, summary="Read link"
        )
        assert (
            ProjectTools.apply(db, disabled["id"], action)["error"] == "link_following_not_enabled"
        )
        assert ProjectTools.apply(db, allowed["id"], action)["status"] == "pending"
        assert WorkReferences.read(db, allowed["id"], "S1")["links"][0]["index"] == 0
        assert "links" not in WorkReferences.read(db, disabled["id"], "S1")
        db.execute(
            "UPDATE work_sources SET status='removed',document=NULL "
            "WHERE task_id=? AND source_id='S2'",
            (allowed["id"],),
        )
        assert ProjectTools.apply(db, allowed["id"], action)["status"] == "removed"
        action.link_index = 3
        assert ProjectTools.apply(db, allowed["id"], action)["error"] == "source_link_not_found"


def test_interrupted_search_is_not_replayed(tmp_path):
    store = Store(tmp_path)
    work = WorkRegistry(store)
    task = work.create("Public search", "private", public_query="Public documentation")
    with store.transaction() as db:
        db.execute("UPDATE work_research SET status='running'")
    work.public_research.recover()
    assert work.public_research.status(task["id"])["status"] == "failed"
