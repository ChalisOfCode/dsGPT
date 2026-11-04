import asyncio
import hashlib
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs

import httpx
import pytest
from conftest import pair, wait_run

from dsgpt.migrations import MIGRATIONS
from dsgpt.search_settings import TEST_QUERY, SearchConfiguration
from dsgpt.storage import APPLICATION_ID, SCHEMA, SCHEMA_VERSION, Store, canonical
from dsgpt.web_retrieval import LocalSearch


def configure(backend, origin="http://127.0.0.1:8888", revision=0):
    return backend.client.put(
        "/v1/research/settings", json={"origin": origin, "revision": revision}
    )


def fixture(backend, handler):
    backend.app.state.search_configuration.search.transport_factory = lambda: httpx.MockTransport(
        handler
    )


def response(payload):
    return httpx.Response(200, stream=httpx.ByteStream(canonical(payload).encode()))


def test_search_configuration_authority_revision_persistence_and_no_implicit_requests(backend):
    calls = []
    fixture(backend, lambda request: calls.append(request))
    initial = backend.client.get("/v1/research/settings").json()
    assert initial["can_configure"] and not initial["configured"]
    assert initial["last_check"] is None and initial["revision"] == 0
    ordinary, _ = pair(backend, ["chat", "models"])
    headers = {"Authorization": "Bearer " + ordinary["token"]}
    assert not backend.client.get("/v1/research/settings", headers=headers).json()["can_configure"]
    for method, path, body in [
        ("PUT", "/v1/research/settings", {"origin": None, "revision": 0}),
        ("POST", "/v1/research/check", {"revision": 0}),
    ]:
        assert backend.client.request(method, path, json=body, headers=headers).status_code == 403
    work, _ = pair(backend, ["work"])
    assert (
        backend.client.get(
            "/v1/research/settings", headers={"Authorization": "Bearer " + work["token"]}
        ).status_code
        == 403
    )
    saved = configure(backend).json()
    assert saved["origin"] == "http://127.0.0.1:8888" and saved["revision"] == 1
    assert backend.app.state.research.search.origin == saved["origin"]
    assert backend.client.get("/v1/research/capabilities").json()["search_configured"]
    assert configure(backend).status_code == 409  # Committed response may have been lost.
    assert calls == []  # Read/save are local only.
    restarted = SearchConfiguration(backend.store, LocalSearch())
    assert restarted.status() == {k: v for k, v in saved.items() if k != "can_configure"}
    assert configure(backend, None, 1).json()["configured"] is False
    assert backend.app.state.research.search.origin is None
    assert calls == []


@pytest.mark.parametrize(
    "origin",
    [
        "https://example.org",
        "http://localhost:8888",
        "http://192.168.1.2:8888",
        "http://127.0.0.1",
        "http://user:password@127.0.0.1:8888",
        "http://127.0.0.1:8888/search",
        "http://127.0.0.1:8888?q=private",
    ],
)
def test_search_settings_reject_nonliteral_or_credentialed_origins(backend, origin):
    assert configure(backend, origin).status_code == 422
    assert backend.client.get("/v1/research/settings").json()["revision"] == 0


def test_configuration_file_precedence_is_read_only_without_losing_saved_value(backend):
    configure(backend)
    search = LocalSearch()
    manager = SearchConfiguration(backend.store, search, "http://[::1]:8889")
    assert manager.status()["configuration_owned"] and search.origin == "http://[::1]:8889"
    with pytest.raises(Exception) as failure:
        manager.update(None, 1)
    assert failure.value.status_code == 409
    assert (
        backend.store.one("SELECT origin FROM search_settings")["origin"] == "http://127.0.0.1:8888"
    )
    assert (
        SearchConfiguration(backend.store, LocalSearch()).status()["origin"]
        == "http://127.0.0.1:8888"
    )


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            {
                "results": [
                    {"url": "https://example.org/doc", "content": "private-looking fixture snippet"}
                ]
            },
            "passed",
        ),
        ({"results": [], "unresponsive_engines": [["engine", "timeout"]]}, "partial"),
        ({"results": []}, "empty"),
        ({}, "failed"),
        ({"results": "invalid"}, "failed"),
        ({"results": [], "unresponsive_engines": "invalid"}, "failed"),
    ],
)
def test_explicit_check_uses_fixed_query_and_sanitized_dated_result(backend, payload, expected):
    configure(backend)
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "POST" and str(request.url) == "http://127.0.0.1:8888/search"
        assert parse_qs(request.content.decode()) == {"q": [TEST_QUERY], "format": ["json"]}
        assert "authorization" not in request.headers and "cookie" not in request.headers
        return response(payload)

    fixture(backend, handler)
    state = backend.client.post("/v1/research/check", json={"revision": 1}).json()
    assert state["last_check"]["status"] == expected and state["last_check"]["checked_at"]
    assert not state["check_in_progress"] and state["revision"] == 1
    assert len(calls) == 1
    assert "private-looking fixture snippet" not in canonical(state)
    assert "authorization" not in backend.store.one("SELECT probe FROM search_settings")["probe"]
    assert backend.client.get("/v1/research/settings").json()["last_check"] == state["last_check"]


def test_search_check_refuses_redirects_and_transport_failures(backend):
    configure(backend)
    calls = []

    def redirect(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": "https://example.org/private"})

    fixture(backend, redirect)
    result = backend.client.post("/v1/research/check", json={"revision": 1}).json()
    assert result["last_check"]["error_code"] == "research_search_unavailable" and len(calls) == 1

    def failed(request):
        raise httpx.ConnectError("sensitive local transport detail", request=request)

    fixture(backend, failed)
    result = backend.client.post("/v1/research/check", json={"revision": 1}).json()
    assert result["last_check"]["error_code"] == "research_search_failed"
    assert "sensitive" not in canonical(result)


def test_changed_settings_discard_late_probe_and_refuse_concurrent_checks(backend):
    configure(backend)
    started, release = threading.Event(), threading.Event()
    calls = []

    async def handler(request):
        calls.append(str(request.url))
        started.set()
        while not release.is_set():
            await asyncio.sleep(0.005)
        return response({"results": []})

    fixture(backend, handler)
    with ThreadPoolExecutor() as pool:
        running = pool.submit(
            lambda: backend.client.post("/v1/research/check", json={"revision": 1})
        )
        assert started.wait(3)
        assert backend.client.get("/v1/research/settings").json()["check_in_progress"]
        assert backend.client.post("/v1/research/check", json={"revision": 1}).status_code == 409
        assert configure(backend, "http://127.0.0.1:9999", 1).status_code == 200
        release.set()
        assert running.result(timeout=5).status_code == 409
    assert calls == ["http://127.0.0.1:8888/search"]
    assert backend.client.get("/v1/research/settings").json()["last_check"] is None


def test_search_change_is_blocked_during_accepted_web_research(backend):
    from test_research import Answer, Reader, research_run

    configure(backend)
    backend.app.state.research.reader = Reader()
    backend.app.state.research.inference = Answer()
    started, release = threading.Event(), threading.Event()

    async def handler(request):
        started.set()
        while not release.is_set():
            await asyncio.sleep(0.005)
        return response({"results": [{"url": "https://example.org/doc"}]})

    fixture(backend, handler)
    run = research_run(backend, {"search": True}).json()
    assert started.wait(3)
    assert configure(backend, None, 1).status_code == 409
    release.set()
    wait_run(backend, run["id"])
    assert configure(backend, None, 1).status_code == 200


def test_schema7_upgrade_preserves_work_references_receipts_and_backup(tmp_path):
    old_hash = hashlib.sha256(b"preserved creation").hexdigest()
    with sqlite3.connect(tmp_path / "dsgpt.db") as db:
        db.executescript(SCHEMA + "".join(MIGRATIONS[v] for v in range(2, 8)))
        db.execute(f"PRAGMA application_id={APPLICATION_ID}")
        db.execute("PRAGMA user_version=7")
        db.execute(
            "INSERT INTO work_tasks VALUES('task','Keep','Requirements','paused',1,'now','now')"
        )
        db.execute("INSERT INTO work_creation_requests VALUES('task',?)", (old_hash,))
        db.execute(
            "INSERT INTO work_sources VALUES('task','S1','https://example.org/doc','retrieved',?,NULL,'now','now')",
            (json.dumps({"text": "COBALT"}),),
        )
    store = Store(tmp_path)
    assert store.one("PRAGMA user_version")["user_version"] == SCHEMA_VERSION
    assert store.one("SELECT request_hash FROM work_creation_requests")["request_hash"] == old_hash
    assert (
        json.loads(store.one("SELECT document FROM work_sources")["document"])["text"] == "COBALT"
    )
    assert store.one("SELECT * FROM search_settings")["revision"] == 0
    with sqlite3.connect(next(tmp_path.glob(f"before-v7-to-v{SCHEMA_VERSION}-*.db"))) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 7
        assert db.execute("SELECT status FROM work_tasks").fetchone()[0] == "paused"
        assert not db.execute(
            "SELECT name FROM sqlite_master WHERE name='search_settings'"
        ).fetchall()
