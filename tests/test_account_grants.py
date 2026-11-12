import asyncio
import sqlite3

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from schema_fixtures import remove_project_groups
from test_account_sessions import REQUEST, SECRET, FixtureProtection

from dsgpt.account_sessions import AccountGrantCreate, AccountSessionCreate
from dsgpt.api import create_app
from dsgpt.config import Settings
from dsgpt.security import Auth
from dsgpt.storage import Store, uid, utcnow


def setup(store):
    auth = Auth(store)
    owner = auth.initialize_owner()
    device = auth.redeem(auth.create_pairing(["work"])["code"], "Granted fixture")
    other = auth.redeem(auth.create_pairing(["work"])["code"], "Other fixture")
    task, other_task = uid(), uid()
    with store.transaction() as db:
        for identifier in (task, other_task):
            db.execute(
                "INSERT INTO work_tasks(id,title,requirements,status,created_at,updated_at) "
                "VALUES(?,?,?,'draft',?,?)",
                (identifier, "Fixture", "Read the approved page", utcnow(), utcnow()),
            )
    return owner, device, other, task, other_task


def bearer(device):
    return {"Authorization": "Bearer " + device["token"]}


def test_owner_grants_exact_task_device_and_read_scope_persistently(tmp_path):
    settings = Settings(tmp_path, allowed_hosts=("testserver",))
    app = create_app(settings)
    owner, device, other, task, other_task = setup(app.state.store)
    app.state.account_sessions.protection = FixtureProtection()
    path = "/v1/account-sessions"
    body = {"task_id": task, "task_revision": 1, "device_id": device["device_id"]}
    with TestClient(app, client=("127.0.0.1", 12345)) as api:
        session = api.post(path, json=REQUEST, headers=bearer(owner)).json()["id"]
        grants = f"{path}/{session}/grants"
        for patch, expected in (
            ({"task_revision": 2}, 409),
            ({"task_id": uid()}, 409),
            ({"device_id": uid()}, 403),
            ({"lifetime_seconds": 3601}, 422),
            ({"permission": "write"}, 422),
        ):
            assert (
                api.post(grants, json={**body, **patch}, headers=bearer(owner)).status_code
                == expected
            )
        assert api.post(grants, json=body, headers=bearer(device)).status_code == 403
        granted = api.post(grants, json=body, headers=bearer(owner))
        assert granted.status_code == 201, granted.text
        grant = granted.json()["id"]
        assert SECRET not in api.get(grants, headers=bearer(owner)).text

    restarted = create_app(settings)
    restarted.state.account_sessions.protection = FixtureProtection()
    seen = []

    class ReadBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"Private fixture"

    def factory(*, validator):
        def respond(request):
            validator(request.url)
            seen.append(str(request.url))
            assert (
                request.method == "GET" and request.headers["cookie"] == REQUEST["session_cookie"]
            )
            return httpx.Response(200, headers={"Content-Type": "text/plain"}, stream=ReadBody())

        return httpx.MockTransport(respond)

    restarted.state.account_sessions.transport_factory = factory
    read = f"/v1/work/tasks/{task}/account-grants/{grant}/read"
    with TestClient(restarted, client=("192.0.2.9", 12345)) as remote:
        assert remote.post(grants, json=body, headers=bearer(owner)).status_code == 403
        assert remote.post(read, headers=bearer(other)).status_code == 403
        assert (
            remote.post(read.replace(task, other_task), headers=bearer(device)).status_code == 403
        )
        assert seen == []
        listing = f"/v1/work/tasks/{task}/account-grants"
        assert remote.get(listing, headers=bearer(other)).json() == []
        assert remote.get(listing.replace(task, other_task), headers=bearer(device)).json() == []
        metadata, = remote.get(listing, headers=bearer(device)).json()
        assert metadata["id"] == grant and metadata["task_revision"] == 1
        assert "sealed_cookie" not in metadata and SECRET not in str(metadata)
        assert remote.post(read, headers=bearer(device)).json()["text"] == "Private fixture"
        assert seen == ["https://example.org/account"]
        local = TestClient(restarted, client=("127.0.0.1", 12346))
        assert local.delete(f"{grants}/{grant}", headers=bearer(owner)).status_code == 204
        assert remote.post(read, headers=bearer(device)).status_code == 403
        assert len(seen) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["grant", "session", "device", "task", "expiry"])
async def test_inflight_read_never_returns_after_authorization_changes(tmp_path, change):
    from dsgpt.account_sessions import AccountSessions

    store = Store(tmp_path)
    owner, device, _, task, _ = setup(store)
    entered, resume = asyncio.Event(), asyncio.Event()

    class BlockedBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            entered.set()
            await resume.wait()
            yield b"Private response must be discarded"

    def factory(*, validator):
        def respond(request):
            validator(request.url)
            return httpx.Response(200, headers={"Content-Type": "text/plain"}, stream=BlockedBody())

        return httpx.MockTransport(respond)

    service = AccountSessions(store, FixtureProtection(), factory)
    session = await service.create(owner["device_id"], AccountSessionCreate(**REQUEST))
    grant = await service.grant(
        owner["device_id"],
        session["id"],
        AccountGrantCreate(
            task_id=task,
            task_revision=1,
            device_id=device["device_id"],
        ),
    )
    pending = asyncio.create_task(service.read_grant(device["device_id"], task, grant["id"]))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        with pytest.raises(HTTPException, match="already in progress"):
            await service.read_grant(device["device_id"], task, grant["id"])
        if change == "grant":
            await asyncio.wait_for(
                service.revoke_grant(owner["device_id"], session["id"], grant["id"]), 1
            )
        elif change == "session":
            await asyncio.wait_for(service.revoke(owner["device_id"], session["id"]), 1)
            assert not store.all("SELECT * FROM account_grants")
        elif change == "device":
            Auth(store).revoke(device["device_id"])
        else:
            with store.transaction() as db:
                db.execute(
                    "UPDATE work_tasks SET revision=revision+1 WHERE id=?"
                    if change == "task"
                    else "UPDATE account_grants SET expires_at=0 WHERE task_id=?",
                    (task,),
                )
        resume.set()
        with pytest.raises(HTTPException) as denied:
            await asyncio.wait_for(pending, 1)
        assert denied.value.status_code == 403
        # No private response or raw credential is persisted by the broker.
        for database in tmp_path.glob("dsgpt.db*"):
            assert b"Private response" not in database.read_bytes()
            assert SECRET.encode() not in database.read_bytes()
    finally:
        resume.set()
        if not pending.done():
            pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)


def test_v26_upgrade_preserves_protected_sessions(tmp_path):
    store = Store(tmp_path)
    owner, _, _, _, _ = setup(store)
    with store.transaction() as db:
        db.execute(
            "INSERT INTO account_sessions VALUES(?,?,?,?,?,?,?)",
            (
                uid(),
                owner["device_id"],
                "Preserved",
                "https://example.org",
                "/account",
                utcnow(),
                b"opaque",
            ),
        )
    before = store.all("SELECT * FROM account_sessions")
    with sqlite3.connect(store.path) as db:
        db.execute("DROP TABLE account_browser_profiles")
        db.execute("DROP TABLE account_browser_writes")
        db.execute("DROP TABLE account_grants")
        remove_project_groups(db)
        db.execute("PRAGMA user_version=26")
    upgraded = Store(tmp_path)
    assert upgraded.all("SELECT * FROM account_sessions") == before
    assert upgraded.all("SELECT * FROM account_grants") == []
    assert len(list(tmp_path.glob("before-v26-*.db"))) == 1
