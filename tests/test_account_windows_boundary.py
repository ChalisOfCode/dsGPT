"""Native Windows protection plus persisted account authority, no browser substitute.

The profile files are synthetic test data. Actual Chromium/Docker/TLS is covered
by separate integration runs; this case exercises real Windows DPAPI and APIs.
"""

import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient
from test_account_browser_profiles import FILES
from test_account_grants import bearer, setup

from dsgpt.account_browser_profiles import AccountBrowserProfiles, AccountProfileError
from dsgpt.account_browser_writes import AccountBrowserWriteError, AccountBrowserWrites
from dsgpt.api import create_app
from dsgpt.config import Settings
from dsgpt.storage import uid


@pytest.mark.skipif(os.name != "nt", reason="Native Windows DPAPI authority integration")
def test_native_saved_profile_authority_restart_and_revoke(tmp_path):
    settings = Settings(tmp_path, allowed_hosts=("testserver",))
    app = create_app(settings)
    assert app.state.account_sessions.protection.available
    owner, device, other, task, _ = setup(app.state.store)
    root = "/v1/account-sessions"
    listing = f"/v1/work/tasks/{task}/account-grants"
    with TestClient(app, client=("127.0.0.1", 12345)) as api:
        response = api.post(root + "/browser", headers=bearer(owner), json={
            "label": "Native protection fixture", "origin": "https://example.org",
            "read_path": "/entry",
        })
        assert response.status_code == 201
        session = response.json()["id"]
        profile = AccountBrowserProfiles(app.state.store, session, owner["device_id"])
        assert profile.save(FILES, expected_revision=0) == 1
        body = dict(task_id=task, task_revision=1, device_id=device["device_id"],
                    profile_revision=1)
        response = api.post(f"{root}/{session}/grants", json=body, headers=bearer(owner))
        assert response.status_code == 201
        grant = response.json()["id"]
        assert api.get(listing, headers=bearer(device)).json()[0]["id"] == grant
        assert api.get(listing, headers=bearer(other)).json() == []
        receipts = AccountBrowserWrites(app.state.store, session, owner["device_id"])
        action = uid()
        receipts.begin(action, origin="https://example.org")

    # A new Windows process restores with the default real DPAPI service. Only
    # opaque IDs/owned directory are arguments; no profile or credential bytes.
    program = """
import asyncio, sys
from dsgpt.storage import Store
from dsgpt.account_sessions import AccountSessions
from dsgpt.account_browser_profiles import AccountBrowserProfiles
from dsgpt.account_browser_writes import AccountBrowserWrites
directory,session,owner,device,task,grant,action=sys.argv[1:]
store=Store(directory)
sessions=AccountSessions(store)
row=sessions._grant_session(device,task,grant)
assert row['profile_revision']==1
profile=AccountBrowserProfiles(store,session,owner)
revision,files=profile.restore()
assert revision==1 and len(files)==3
assert files['Default/Network/Cookies']==b'cookie-sentinel'
assert AccountBrowserWrites(store,session,owner).pending()[0]['id']==action
assert profile.save(files,expected_revision=1)==2
assert sessions.task_grants(device,task)==[]
"""
    subprocess.run(
        [sys.executable, "-c", program, str(tmp_path), session, owner["device_id"],
         device["device_id"], task, grant, action],
        check=True, capture_output=True, timeout=20,
    )
    restarted = create_app(settings)
    with TestClient(restarted, client=("127.0.0.1", 12345)) as api:
        assert api.get(listing, headers=bearer(device)).json() == []
        assert api.post(f"{listing}/{grant}/read", headers=bearer(device)).status_code == 403
        receipts = AccountBrowserWrites(restarted.state.store, session, owner["device_id"])
        assert receipts.pending()[0]["id"] == action
        with pytest.raises(AccountBrowserWriteError):
            receipts.begin(uid(), origin="https://example.org")
        body["profile_revision"] = 2
        response = api.post(f"{root}/{session}/grants", json=body, headers=bearer(owner))
        assert response.status_code == 201
        profile = AccountBrowserProfiles(restarted.state.store, session, owner["device_id"])
        with restarted.state.store.transaction() as db:
            encrypted = bytearray(db.execute(
                "SELECT sealed_profile FROM account_browser_profiles WHERE session_id=?",
                (session,),
            ).fetchone()[0])
            encrypted[-1] ^= 1
            db.execute("UPDATE account_browser_profiles SET sealed_profile=? WHERE session_id=?",
                       (bytes(encrypted), session))
        with pytest.raises(AccountProfileError, match="restore_failed"):
            profile.restore()
        assert api.delete(f"{root}/{session}", headers=bearer(owner)).status_code == 204
        for table in ("account_sessions", "account_browser_profiles", "account_grants",
                      "account_browser_writes"):
            assert not restarted.state.store.all("SELECT * FROM " + table)
    for file in tmp_path.glob("*.db*"):
        for sentinel in FILES.values():
            assert sentinel not in file.read_bytes()
