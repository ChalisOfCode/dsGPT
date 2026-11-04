import asyncio
import json

import pytest

from dsgpt.config import Model
from dsgpt.generation import options
from dsgpt.project_tools import ProjectAction, action_schema
from dsgpt.scheduler import InferenceScheduler
from dsgpt.storage import Store, canonical, utcnow
from dsgpt.web_retrieval import ResearchError
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
        return {
            "results": [
                {
                    "url": f"https://example.org/doc{len(self.calls)}",
                    "title": "Documentation",
                    "snippet": "Read the page",
                }
            ],
            "engine_failures": 1,
        }


class Reader:
    def __init__(self):
        self.calls = []

    async def read(self, url):
        self.calls.append(url)
        return {
            "text": "API example and error explanation",
            "title": "Documentation",
            "links": ["https://example.org/more"],
            "retrieved_at": utcnow(),
        }


def setup(tmp_path, mode="on", files=None):
    store = Store(tmp_path)
    model = Model("local", "Local", "ollama", "http://127.0.0.1:11434", "local")
    refs = WorkReferences(store, Reader())
    work = WorkRegistry(
        store, models={"local": model}, references=refs, scheduler=InferenceScheduler(store)
    )
    task = work.create(
        "Research",
        "Research then implement with evidence",
        "local",
        web_mode=mode,
        start=True,
        source_files=files,
    )
    work.public_research.search = Search()
    return store, work, task["id"]


async def execute(store, work, tid, step, **kwargs):
    with store.transaction() as db:
        db.execute("UPDATE work_tasks SET status='running' WHERE id=?", (tid,))
    return await work.web.execute(tid, step, ProjectAction(summary="Research", **kwargs))


async def test_multiple_queries_reads_and_followups_are_saved_with_provenance(tmp_path):
    store, work, tid = setup(tmp_path)
    first = await execute(store, work, tid, 1, tool="search_web", query="official API docs")
    assert first["engine_failures"] == 1
    assert first["results"][0]["source_id"] == "S1"
    second = await execute(store, work, tid, 2, tool="search_web", query="API compilation error")
    assert second["results"][0]["source_id"] == "S2"
    page = await execute(store, work, tid, 3, tool="open_url", url="https://example.org/doc2")
    assert page["text"] == "API example and error explanation"
    assert page["text_sha256"] and page["retrieved_at"]
    assert page["links"][0]["url"] == "https://example.org/more"
    assert work.public_research.search.calls == ["official API docs", "API compilation error"]
    with store.connect() as db:
        assert work.public_research.follow(db, tid, "S2", 0)["status"] == "pending"


async def test_receipt_survives_restart_without_repeating_network_request(tmp_path):
    store, work, tid = setup(tmp_path)
    result = await execute(store, work, tid, 1, tool="search_web", query="API docs")
    assert result == await execute(store, work, tid, 1, tool="search_web", query="API docs")
    work.web.recover()
    action, recovered = work.web.pending(tid, 1)
    assert recovered == result
    session = store.one("SELECT * FROM work_sessions WHERE task_id=?", (tid,))
    work._commit(tid, session, ProjectAction.model_validate(action), recovered)
    assert work.web.pending(tid, 1) is None
    assert json.loads(store.one("SELECT result FROM work_steps")["result"])["query"] == "API docs"
    assert len(work.public_research.search.calls) == 1


@pytest.mark.parametrize("change", ["pause", "revoke"])
async def test_late_results_discarded_after_pause_or_revocation(tmp_path, change):
    store, work, tid = setup(tmp_path)
    search = work.public_research.search
    search.gate.clear()
    job = asyncio.create_task(execute(store, work, tid, 1, tool="search_web", query="docs"))
    while not search.calls:
        await asyncio.sleep(0)
    with store.transaction() as db:
        if change == "pause":
            db.execute("UPDATE work_tasks SET status='paused',revision=revision+1")
        else:
            db.execute("UPDATE generation_options SET web_mode='off'")
    search.gate.set()
    result = await job
    assert result["error"] in {"research_result_discarded", "work_web_disabled"}
    assert not store.all("SELECT * FROM work_sources")


async def test_off_cannot_be_bypassed_by_model_generated_action(tmp_path):
    store, work, tid = setup(tmp_path, "off")
    result = await execute(store, work, tid, 1, tool="search_web", query="private secret")
    assert result["error"] == "work_web_disabled"
    assert not work.public_research.search.calls
    assert not work.references.reader.calls
    assert "search_web" not in {v["properties"]["tool"]["const"] for v in action_schema()["oneOf"]}


@pytest.mark.parametrize("mode,enabled", [("off", False), ("auto", False), ("on", True)])
def test_private_files_require_explicit_web_on(tmp_path, mode, enabled):
    store, work, tid = setup(tmp_path, mode, [{"name": "private.txt", "text": "local only"}])
    assert work.web.enabled(tid) is enabled
    assert options(store, "work", tid)["web_mode"] == ("on" if enabled else "off")


@pytest.mark.parametrize(
    "url",
    [
        "http://example.org",
        "https://127.0.0.1",
        "https://192.168.1.2",
        "https://user:pass@example.org",
        "https://localhost",
    ],
)
async def test_private_urls_never_reach_reader(tmp_path, url):
    store, work, tid = setup(tmp_path)
    result = await execute(store, work, tid, 1, tool="open_url", url=url)
    assert "error" in result
    assert not work.references.reader.calls


async def test_failed_source_never_claims_retrieval_and_removed_source_stays_removed(tmp_path):
    store, work, tid = setup(tmp_path)
    page = await execute(store, work, tid, 1, tool="open_url", url="https://example.org/doc1")
    with store.transaction() as db:
        db.execute("UPDATE work_sources SET status='removed',document=NULL,generation=generation+1")
    assert (
        work.web.current_result(tid, {"tool": "open_url"}, page)["error"]
        == "source_snapshot_no_longer_current"
    )
    assert (await execute(store, work, tid, 2, tool="open_url", url=page["url"]))[
        "error"
    ] == "source_removed"
    result = await execute(store, work, tid, 3, tool="search_web", query="docs")
    assert result["results"] == []

    class Failed:
        async def read(self, url):
            raise ResearchError("research_http_403")

    work.references.reader = Failed()
    failed = await execute(store, work, tid, 4, tool="open_url", url="https://example.org/blocked")
    assert failed["error"] == "research_http_403"
    assert "text" not in failed


async def test_cancelled_request_returns_interrupted_receipt_without_automatic_retry(tmp_path):
    store, work, tid = setup(tmp_path)
    work.public_research.search.gate.clear()
    job = asyncio.create_task(execute(store, work, tid, 1, tool="search_web", query="docs"))
    while not work.public_research.search.calls:
        await asyncio.sleep(0)
    job.cancel()
    with pytest.raises(asyncio.CancelledError):
        await job
    assert work.web.pending(tid, 1)[1]["error"] == "research_interrupted"
    assert not store.all("SELECT * FROM work_sources")


async def test_work_loop_can_research_again_after_new_information(tmp_path):
    store, work, tid = setup(tmp_path)
    actions = iter(
        [
            {"tool": "search_web", "query": "API docs"},
            {"tool": "read_source", "source_id": "S1"},
            {
                "tool": "write_file",
                "path": "notes.txt",
                "content": "First finding needs verification",
            },
            {"tool": "search_web", "query": "API error independent verification"},
            {"tool": "open_url", "url": "https://example.org/doc2"},
            {"tool": "finish"},
        ]
    )

    class Agent:
        async def stream(self, model, messages, response_schema):
            assert "search_web" in canonical(response_schema)
            yield {
                "kind": "delta",
                "data": {"text": canonical({"summary": "Continue", **next(actions)})},
            }

    work.inference = Agent()
    for _ in range(12):
        row = store.one("SELECT * FROM work_tasks WHERE id=?", (tid,))
        if row["status"] == "completed":
            break
        await work._step(row)
    assert work.get(tid)["status"] == "completed"
    assert len(work.public_research.search.calls) == 2
    assert len(store.all("SELECT * FROM work_web_calls WHERE recorded=1")) == 3


def test_existing_task_can_enable_and_revoke_research_without_recreation(tmp_path):
    store, work, tid = setup(tmp_path, "off")
    with store.transaction() as db:
        db.execute("UPDATE work_tasks SET status='paused'")
    updated = work.revise(tid, work.get(tid)["revision"], web_mode="on")
    assert work.web.enabled(tid) and updated["web_mode"] == "on"
    with store.transaction() as db:
        WorkReferences.append(db, tid, ["https://example.org/pending"])
    updated = work.revise(tid, updated["revision"], web_mode="off")
    assert not work.web.enabled(tid)
    assert work.references.pending(tid) is None
    assert store.one("SELECT error_code FROM work_sources")["error_code"] == "work_web_disabled"


def test_find_source_returns_exact_unicode_offsets_and_pages_without_removed_content(tmp_path):
    store, work, tid = setup(tmp_path)
    body = "ß🚀 API pattern[1]. " * 12
    with store.transaction() as db:
        WorkReferences.append(db, tid, ["https://example.org/doc"])
        WorkReferences.save(db, tid, "S1", {"text": body}, None)
        first = WorkReferences.find(db, tid, "S1", "pattern[1]")
        second = WorkReferences.find(db, tid, "S1", "pattern[1]", first["next_offset"])
        assert len(first["matches"]) == len(second["matches"]) == 6
        for match in first["matches"] + second["matches"]:
            assert body[match["offset"] :].startswith("pattern[1]")
        db.execute("UPDATE work_sources SET status='removed',document=NULL")
        assert WorkReferences.find(db, tid, "S1", "pattern")["error"] == "source_not_retrieved"


def test_completed_report_does_not_overflow_next_research_turn(tmp_path):
    from dataclasses import replace

    from dsgpt.inference import ollama_input_estimate
    from dsgpt.project_tools import ProjectTools

    store, work, tid = setup(tmp_path)
    content = "Report with findings and evidence\n" * 400
    action = ProjectAction(
        tool="write_file", path="report.txt", content=content, summary="Report saved"
    )
    with store.transaction() as db:
        result = ProjectTools.apply(db, tid, action)
        db.execute(
            "INSERT INTO work_steps VALUES(?,?,?,?,?)",
            (tid, 1, canonical(action.model_dump()), canonical(result), utcnow()),
        )
        db.execute("UPDATE work_sessions SET step=1")
        WorkReferences.append(db, tid, ["https://example.org/doc1", "https://example.org/doc2"])
    row = work.get(tid)
    model = replace(work.models["local"], context=8192, output_tokens=2048)
    messages = work._prompt(row, row["session"], model, [])
    assert ollama_input_estimate(messages) + model.output_tokens <= model.context
    assert content not in canonical(messages)
    assert "https://example.org/doc1" in canonical(messages)
    assert store.one("SELECT content FROM work_files")["content"] == content


@pytest.mark.parametrize("guided", [False, True])
def test_realistic_source_page_and_links_fit_model_context_with_usable_offsets(tmp_path, guided):
    from dataclasses import replace

    from dsgpt.inference import ollama_input_estimate

    store, work, tid = setup(tmp_path)
    with store.transaction() as db:
        if guided:
            work.specs.initialize(db, tid, "Read evidence and create a report")
            db.execute("UPDATE work_spec_sections SET notes='Verify sources'")
            db.execute("UPDATE work_specs SET brief='Research report'")
        WorkReferences.append(db, tid, ["https://example.org/docs"])
        WorkReferences.save(
            db,
            tid,
            "S1",
            {
                "title": "Documentation",
                "text": "🚀 detailed evidence " * 4000,
                "links": [f"https://example.org/doc/{i}" for i in range(60)],
            },
            None,
        )
        result = WorkReferences.read(db, tid, "S1")
        db.execute(
            "INSERT INTO work_steps VALUES(?,?,?,?,?)",
            (
                tid,
                1,
                canonical({"tool": "read_source", "source_id": "S1", "summary": "Read"}),
                canonical(result),
                utcnow(),
            ),
        )
        db.execute("UPDATE work_sessions SET step=1")
    row = work.get(tid)
    model = replace(work.models["local"], context=8192, output_tokens=2048)
    messages = work._prompt(row, row["session"], model, [])
    assert ollama_input_estimate(messages) + model.output_tokens <= model.context
    results = [m["content"] for m in messages if m["content"].startswith("Recorded tool result: ")]
    assert results
    page = json.loads(results[-1].split(": ", 1)[1])
    assert page["text"] and page["source_id"] == "S1"
    assert page["next_offset"] == len(page["text"])
    if guided:
        section = json.loads(messages[1]["content"])["requirements"]["current_section"]
        if section.get("read"):
            assert section["content"] == ""
            assert section["next_offset"] == section["read"]["offset"] == 0


def test_file_tool_contract_cannot_confuse_web_sources_with_project_files():
    empty = action_schema(reference_sources=True, web_research=True, file_paths=[])["oneOf"]
    assert "read_file" not in [v["properties"]["tool"]["const"] for v in empty]
    assert "read_source" in [v["properties"]["tool"]["const"] for v in empty]
    filled = action_schema(file_paths=["app/main.py"])["oneOf"]
    reader = next(v for v in filled if v["properties"]["tool"]["const"] == "read_file")
    assert reader["properties"]["path"] == {"enum": ["app/main.py"]}
