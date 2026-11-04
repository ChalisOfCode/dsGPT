import asyncio
import json
import threading
from uuid import uuid4

from conftest import new_chat, pair, wait_run

from dsgpt.web_retrieval import ResearchError


def test_schema_v4_upgrade_preserves_runtime_references_and_backup(tmp_path):
    import sqlite3

    from dsgpt.migrations import VERSION_2, VERSION_3, VERSION_4
    from dsgpt.storage import APPLICATION_ID, SCHEMA, SCHEMA_VERSION, Store

    with sqlite3.connect(tmp_path / "dsgpt.db") as db:
        db.executescript(SCHEMA + VERSION_2 + VERSION_3 + VERSION_4)
        db.execute(f"PRAGMA application_id={APPLICATION_ID}")
        db.execute("PRAGMA user_version=4")
        for asset in ("model", "runtime"):
            db.execute(
                "INSERT INTO downloads VALUES(?,?,?,'downloaded',10,NULL,'now','now')",
                (asset, asset, "{}"),
            )
        db.execute("INSERT INTO runtime_installations VALUES('runtime','{}','{}','now')")
        db.execute("INSERT INTO runtime_sources VALUES('runtime','runtime')")
        db.execute("INSERT INTO model_records VALUES('model','{}','now')")
        db.execute("INSERT INTO managed_models VALUES('model','model','runtime',0)")
        db.execute(
            "INSERT INTO memories VALUES('memory',NULL,'Keep','Preserved','user',1,'now','now')"
        )
    store = Store(tmp_path)
    assert store.one("PRAGMA user_version")["user_version"] == SCHEMA_VERSION
    assert store.one("SELECT * FROM managed_models")["runtime_id"] == "runtime"
    assert store.one("SELECT * FROM memories")["content"] == "Preserved"
    assert store.all("SELECT * FROM web_sources") == []
    assert not store.all("PRAGMA foreign_key_check")
    with sqlite3.connect(next(tmp_path.glob(f"before-v4-to-v{SCHEMA_VERSION}-*.db"))) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 4
        assert db.execute("SELECT runtime_id FROM managed_models").fetchone()[0] == "runtime"
        assert db.execute("SELECT content FROM memories").fetchone()[0] == "Preserved"


class Reader:
    def __init__(self, scheduler=None):
        self.calls, self.scheduler = [], scheduler
        self.error = None

    async def read(self, url):
        if self.scheduler:
            assert self.scheduler.active is None  # Network I/O does not occupy model time.
        self.calls.append(url)
        if self.error:
            raise ResearchError(self.error)
        return {
            "url": url,
            "final_url": url,
            "title": "Fixture document",
            "text": "The documented project codename is COBALT.",
            "links": [],
            "published_at": "2026-10-18",
            "retrieved_at": "2026-10-19",
            "content_sha256": "a" * 64,
            "text_truncated": False,
        }


class Answer:
    def __init__(self, source="S1"):
        self.calls, self.source = [], source

    async def stream(self, model, messages, response_schema=None):
        self.calls.append(messages)
        answer = {
            "findings": [
                {"text": "The codename is COBALT.", "inference": False, "sources": [self.source]}
            ],
            "limitations": [],
        }
        yield {"kind": "delta", "data": {"text": json.dumps(answer)}}


def research_run(backend, options=None, identifier=None, chat_id=None):
    return backend.client.post(
        f"/v1/conversations/{chat_id or new_chat(backend)}/messages",
        json={
            "request_id": identifier or str(uuid4()),
            "content": "What is the documented codename?",
            "model_id": "test-na",
            "research": options
            if options is not None
            else {"search": False, "urls": ["https://example.org/a", "https://example.org/b"]},
        },
    )


def test_research_uses_retrieved_citations_and_keeps_raw_page_out_of_source_listing(backend):
    research = backend.app.state.research
    research.reader, research.inference = Reader(backend.app.state.scheduler), Answer()
    result = research_run(backend)
    assert result.status_code == 202
    run = wait_run(backend, result.json()["id"])
    assert run["status"] == "completed", run
    messages = backend.client.get(f"/v1/conversations/{run['conversation_id']}/messages").json()
    assert "[S1](<https://example.org/a>)" in messages[-1]["content"]
    sources = backend.client.get(f"/v1/runs/{run['id']}/sources").json()
    assert sources["retrieval_complete"] and len(sources["sources"]) == 2
    assert all("text" not in s for s in sources["sources"])
    full = backend.client.get(f"/v1/runs/{run['id']}/sources?include_text=true").json()
    assert "COBALT" in full["sources"][0]["text"]
    assert len(research.reader.calls) == 2
    # Both history and atomic snapshots retain the reference used by native source viewers.
    assert messages[-1]["run_id"] == run["id"] and messages[-1]["research"] == 1
    snap = backend.client.get(f"/v1/conversations/{run['conversation_id']}/latest-run").json()
    assert snap["message"]["run_id"] == run["id"] and snap["message"]["research"] == 1


def test_unknown_citations_never_publish_a_fabricated_answer(backend):
    research = backend.app.state.research
    research.reader, research.inference = Reader(), Answer("S99")
    run = wait_run(backend, research_run(backend).json()["id"])
    assert run["status"] == "failed" and run["error_code"] == "research_invalid_answer"
    assert len(research.inference.calls) == 3
    messages = backend.client.get(f"/v1/conversations/{run['conversation_id']}/messages").json()
    assert messages[-1]["content"] == ""


def test_research_input_is_idempotent_private_urls_rejected_and_scoped(backend):
    research = backend.app.state.research
    research.reader, research.inference = Reader(), Answer()
    identifier, chat_id = str(uuid4()), new_chat(backend)
    first = research_run(backend, identifier=identifier, chat_id=chat_id)
    assert first.status_code == 202
    assert research_run(backend, identifier=identifier, chat_id=chat_id).json()["id"] == identifier
    changed = research_run(
        backend, {"search": False, "urls": ["https://example.org/new"]}, identifier, chat_id
    )
    assert changed.status_code == 409
    assert (
        research_run(backend, {"search": False, "urls": ["https://127.0.0.1/"]}).status_code == 422
    )
    assert research_run(backend, {"search": False, "urls": []}).status_code == 422
    assert research_run(backend, {"search": True, "command": "run"}).status_code == 422
    phone, _ = pair(backend, ["diagnostics"])
    assert (
        backend.client.get(
            f"/v1/runs/{identifier}/sources", headers={"Authorization": "Bearer " + phone["token"]}
        ).status_code
        == 403
    )


def test_inaccessible_sources_fail_without_inventing_evidence(backend):
    research = backend.app.state.research
    research.reader, research.inference = Reader(), Answer()
    research.reader.error = "research_source_inaccessible"
    run = wait_run(backend, research_run(backend).json()["id"])
    assert run["status"] == "failed" and run["error_code"] == "research_no_accessible_sources"
    assert not research.inference.calls
    assert all(s["status"] == "unavailable" for s in research.sources(run["id"]))


def test_missing_search_is_reported_but_explicit_sources_can_still_answer(backend):
    research = backend.app.state.research
    research.reader, research.inference = Reader(), Answer()
    run = wait_run(
        backend,
        research_run(backend, {"search": True, "urls": ["https://example.org/doc"]}).json()["id"],
    )
    assert run["status"] == "completed"
    assert (
        "research_search_not_configured"
        in backend.client.get(f"/v1/runs/{run['id']}/sources").json()["warnings"]
    )


def test_completed_retrieval_is_reused_after_queued_worker_recovery(backend):
    research = backend.app.state.research
    research.reader, research.inference = Reader(), Answer()
    run = wait_run(backend, research_run(backend).json()["id"])
    count = len(research.reader.calls)
    asyncio.run(research.prepare(run))
    assert len(research.reader.calls) == count


def test_multi_query_planning_uses_current_question_without_private_memory(backend):
    research = backend.app.state.research
    research.reader = Reader(backend.app.state.scheduler)
    backend.client.post(
        "/v1/memories",
        json={"title": "Codename private memory", "content": "PRIVATE-DO-NOT-SEARCH"},
    )

    class Planner(Answer):
        async def stream(self, model, messages, response_schema=None):
            if "queries" in response_schema["properties"]:
                assert "PRIVATE-DO-NOT-SEARCH" not in json.dumps(messages)
                yield {
                    "kind": "delta",
                    "data": {
                        "text": json.dumps(
                            {
                                "queries": [
                                    "official codename documentation",
                                    "codename release notes",
                                ]
                            }
                        )
                    },
                }
            else:
                async for event in super().stream(model, messages, response_schema):
                    yield event

    class Search:
        origin = "http://127.0.0.1:8888"

        def __init__(self):
            self.queries = []

        async def search(self, query):
            assert backend.app.state.scheduler.active is None
            self.queries.append(query)
            return {
                "results": [{"url": f"https://example.org/source-{len(self.queries)}"}],
                "engine_failures": 0,
            }

    research.inference, research.search = Planner(), Search()
    run = wait_run(backend, research_run(backend, {"search": True}).json()["id"])
    assert run["status"] == "completed", run
    assert len(research.search.queries) == 2 and len(research.reader.calls) == 2


def test_cancellation_during_retrieval_publishes_no_answer_and_keeps_source_state(backend):
    research = backend.app.state.research
    entered = threading.Event()

    class WaitingReader:
        async def read(self, url):
            entered.set()
            await asyncio.Event().wait()

    research.reader, research.inference = WaitingReader(), Answer()
    identifier = research_run(backend).json()["id"]
    assert entered.wait(3)
    assert backend.client.post(f"/v1/runs/{identifier}/cancel").json()["status"] == "cancelled"
    assert not research.inference.calls
    assert research.sources(identifier)[0]["status"] == "pending"
