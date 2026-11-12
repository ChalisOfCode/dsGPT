
"""Task-scoped profile reads, with real Chromium where available."""

import asyncio
import sqlite3
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from schema_fixtures import remove_project_groups
from test_account_browser_bridge import FixtureSandbox, needs_browser
from test_account_browser_network import network
from test_account_grants import bearer, setup
from test_account_sessions import REQUEST, FixtureProtection
from test_web_retrieval import Bytes

from dsgpt.account_browser_bridge import AccountBrowserBridge
from dsgpt.account_browser_handoff import AccountBrowserHandoffs
from dsgpt.account_browser_network import AccountBrowserNetworkError
from dsgpt.account_browser_profiles import AccountBrowserProfiles
from dsgpt.account_browser_read import AccountBrowserReadNetwork
from dsgpt.account_sessions import AccountGrantCreate, AccountSessionCreate, AccountSessions
from dsgpt.api import create_app
from dsgpt.config import Settings
from dsgpt.storage import Store

ORIGIN = "https://example.org"
PATH = "/account"
COOKIE = "fixture=private-session-fixture-only"
BODY = b"Private task page fixture"
REQUEST_BROWSER = {"label": "Fixture", "origin": ORIGIN, "read_path": PATH}


def transport(respond):
    def factory(*, validator):
        async def request(req):
            validator(req.url)
            return await respond(req)

        return httpx.MockTransport(request)

    return factory


async def browser_fixture(directory, *, respond=None):
    store = Store(directory)
    owner, device, other, task, other_task = setup(store)
    service = AccountSessions(store, FixtureProtection(), transport(respond) if respond else None)
    from dsgpt.account_sessions import BrowserSessionCreate

    session = await service.create_browser(
        owner["device_id"], BrowserSessionCreate(**REQUEST_BROWSER),
    )
    vault = AccountBrowserProfiles(store, session["id"], owner["device_id"], service.protection)
    body = AccountGrantCreate(
        task_id=task, task_revision=1, device_id=device["device_id"], profile_revision=1,
    )
    return service, owner, device, other, task, other_task, session, vault, body


@pytest.mark.parametrize("failure", ["wrong_path", "post", "anonymous", "redirect",
                                     "html", "set_cookie", "reflected", "reflected_split"])
async def test_delegated_transport_rejects_unapproved_requests_and_content(failure):
    sent = []

    async def respond(request):
        sent.append(request)
        if failure == "redirect":
            return httpx.Response(303, headers={"location": "/next"})
        content = {"reflected": COOKIE.encode(),
                   "reflected_split": COOKIE.replace("session", "ses\0sion").encode()}
        return httpx.Response(
            200,
            headers={"content-type": "text/html" if failure == "html" else "text/plain",
                     **({"set-cookie": COOKIE} if failure == "set_cookie" else {})},
            stream=Bytes(content.get(failure, BODY)),
        )

    reader = AccountBrowserReadNetwork(ORIGIN, PATH, authorize=lambda: None,
                                       transport_factory=transport(respond))
    with pytest.raises(AccountBrowserNetworkError):
        await reader.fetch(
            ORIGIN + ("/other" if failure == "wrong_path" else PATH),
            "POST" if failure == "post" else "GET",
            {} if failure == "anonymous" else {"Cookie": COOKIE},
        )
    assert len(sent) == (0 if failure in {"wrong_path", "post", "anonymous"} else 1)
    assert reader.result is None


async def test_grant_requires_current_saved_profile_and_rejects_replacement(tmp_path):
    service, owner, device, other, task, other_task, session, vault, body = await browser_fixture(
        tmp_path
    )
    with pytest.raises(HTTPException, match="current saved"):
        await service.grant(owner["device_id"], session["id"], body)
    vault.save({"Local State": b"{}"}, expected_revision=0)
    with pytest.raises(HTTPException, match="current saved"):
        await service.grant(owner["device_id"], session["id"],
                            body.model_copy(update={"profile_revision": 2}))
    grant = await service.grant(owner["device_id"], session["id"], body)
    assert grant["profile_revision"] == 1

    async def reader(authorize):
        return authorize()["profile_revision"]

    assert await service.read_grant(
        device["device_id"], task, grant["id"], browser_reader=reader,
    ) == 1
    for actor, target in [(other["device_id"], task), (device["device_id"], other_task)]:
        with pytest.raises(HTTPException) as denied:
            await service.read_grant(actor, target, grant["id"], browser_reader=reader)
        assert denied.value.status_code == 403
    vault.save({"Local State": b"{}"}, expected_revision=1)
    with pytest.raises(HTTPException) as denied:
        await service.read_grant(device["device_id"], task, grant["id"], browser_reader=reader)
    assert denied.value.status_code == 403


@pytest.mark.parametrize("change", ["grant", "device", "task", "expiry", "profile", "session"])
async def test_revocation_quiesces_delegated_reader_before_releasing_response(tmp_path, change):
    service, owner, device, _, task, _, session, vault, body = await browser_fixture(tmp_path)
    vault.save({"Local State": b"{}"}, expected_revision=0)
    grant = await service.grant(owner["device_id"], session["id"], body)
    entered, cleaned = asyncio.Event(), asyncio.Event()

    class ParkedBridge:
        def __init__(self, sandbox, vault, network, live):
            self.revision = None

        async def start(self):
            self.revision = 1

        async def navigate(self, url):
            entered.set()
            await asyncio.Future()

        async def abort(self):
            cleaned.set()

    controller = AccountBrowserHandoffs(
        service, SimpleNamespace(sandbox=object(), ready=True), bridge_factory=ParkedBridge
    )
    read = asyncio.create_task(
        service.read_grant(device["device_id"], task, grant["id"],
                           browser_reader=controller.read_grant)
    )
    try:
        await asyncio.wait_for(entered.wait(), 2)
        with pytest.raises(HTTPException, match="already in use"):
            await controller.start(owner["device_id"], session["id"])
        if change == "grant":
            await service.revoke_grant(owner["device_id"], session["id"], grant["id"])
        elif change == "profile":
            vault.save({"Local State": b"{}"}, expected_revision=1)
        elif change == "session":
            await service.revoke(owner["device_id"], session["id"])
        else:
            sql, identifier = {
                "device": ("UPDATE devices SET revoked=1 WHERE id=?", device["device_id"]),
                "task": ("UPDATE work_tasks SET revision=revision+1 WHERE id=?", task),
                "expiry": ("UPDATE account_grants SET expires_at=0 WHERE id=?", grant["id"]),
            }[change]
            with service.store.transaction() as db:
                db.execute(sql, (identifier,))
        with pytest.raises(HTTPException) as denied:
            await asyncio.wait_for(read, 2)
        assert denied.value.status_code == 403
        assert cleaned.is_set() and controller.delegated is None
    finally:
        if not read.done():
            read.cancel()
        await asyncio.gather(read, return_exceptions=True)


@needs_browser
async def test_real_chromium_reuses_saved_cookie_for_exact_scoped_read(tmp_path, caplog):
    seen = []

    async def read_response(request):
        seen.append((str(request.url), request.method))
        assert request.headers["cookie"] == COOKIE
        assert request.headers["accept"] == "text/plain"
        return httpx.Response(200, headers={"content-type": "text/plain"}, stream=Bytes(BODY))

    service, owner, device, _, task, _, session, vault, body = await browser_fixture(
        tmp_path / "store", respond=read_response
    )

    async def sign_in_fixture(request):
        return httpx.Response(
            200,
            headers={"content-type": "text/html",
                     "set-cookie": COOKIE + "; Max-Age=600; Secure; HttpOnly"},
            stream=Bytes(b"<p>Controlled profile fixture</p>"),
        )

    seed, reader = tmp_path / "seed", tmp_path / "read"
    seed.mkdir()
    reader.mkdir()
    bridge = AccountBrowserBridge(
        FixtureSandbox(seed), vault, network(sign_in_fixture), lambda: None,
    )
    try:
        await bridge.start()
        await bridge.navigate(ORIGIN + PATH)
        assert await bridge.close() == 1
    finally:
        await bridge.abort()
    grant = await service.grant(owner["device_id"], session["id"], body)
    box = FixtureSandbox(reader)
    # Exercise the real paired-device route with a fresh backend instance.
    app = create_app(Settings(tmp_path / "store", allowed_hosts=("testserver",)))
    app.state.account_sessions.protection = service.protection
    app.state.account_sessions.transport_factory = transport(read_response)
    listing = f"/v1/work/tasks/{task}/account-grants"
    with TestClient(app, client=("192.0.2.9", 12345)) as api:
        app.state.builds.sandbox = box
        app.state.builds.ready = True
        eligible, = api.get(listing, headers=bearer(device)).json()
        assert eligible["id"] == grant["id"] and eligible["profile_revision"] == 1
        response = api.post(f"{listing}/{grant['id']}/read", headers=bearer(device))
        assert response.headers["cache-control"] == "no-store"
        assert response.json() == {
            "session_id": session["id"], "text": BODY.decode(), "truncated": False,
        }
        assert app.state.account_browsers.delegated is None
    assert seen == [(ORIGIN + PATH, "GET")]
    assert box.cleaned and vault.restore()[0] == 1
    assert COOKIE not in caplog.text and BODY.decode() not in caplog.text
    for database in (tmp_path / "store").glob("*.db*"):
        assert COOKIE.split("=")[1].encode() not in database.read_bytes()
        assert BODY not in database.read_bytes()


async def test_v29_migration_preserves_legacy_grants_and_profiles(tmp_path):
    service, owner, _, _, _, _, session, vault, body = await browser_fixture(tmp_path)
    vault.save({"Local State": b"{}"}, expected_revision=0)
    legacy = await service.create(owner["device_id"], AccountSessionCreate(**REQUEST))
    grant = await service.grant(
        owner["device_id"], legacy["id"], body.model_copy(update={"profile_revision": None}),
    )
    old_profile = service.store.one("SELECT * FROM account_browser_profiles")
    with sqlite3.connect(service.store.path) as db:
        db.execute("ALTER TABLE account_grants DROP COLUMN profile_revision")
        remove_project_groups(db)
        db.execute("PRAGMA user_version=29")
    reopened = Store(tmp_path)
    assert reopened.one("SELECT * FROM account_browser_profiles") == old_profile
    assert reopened.one("SELECT profile_revision FROM account_grants WHERE id=?",
                        (grant["id"],)) == {"profile_revision": None}
    assert reopened.one("SELECT id FROM account_sessions WHERE id=?", (session["id"],))
