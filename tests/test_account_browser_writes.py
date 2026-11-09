import asyncio
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from dsgpt.account_browser_network import AccountBrowserNetwork, AccountBrowserNetworkError
from dsgpt.account_browser_writes import AccountBrowserWriteError, AccountBrowserWrites
from dsgpt.storage import SCHEMA_VERSION, Store, uid, utcnow


def make_ledger(path):
    store = Store(path)
    owner, session = uid(), uid()
    with store.transaction() as db:
        db.execute(
            "INSERT INTO devices VALUES(?,?,?,?,?,?,?)",
            (owner, "Fixture", "owner", uid(), "[]", utcnow(), 0),
        )
        db.execute(
            "INSERT INTO account_sessions VALUES(?,?,?,?,?,?,?)",
            (session, owner, "Fixture", "https://example.org", "/account", utcnow(), b"opaque"),
        )
    return AccountBrowserWrites(store, session, owner)


def reopen(ledger):
    return AccountBrowserWrites(Store(ledger.store.directory), ledger.session_id, ledger.owner_id)


def browser(ledger, handler, authorize=lambda: None):
    return AccountBrowserNetwork(
        "https://example.org",
        authorize=authorize,
        writes=ledger,
        transport_factory=lambda **kwargs: httpx.MockTransport(handler),
    )


URL = "https://example.org/private?private-query-sentinel"
BODY = b"password=credential-sentinel"
HEADERS = {"Origin": "https://example.org", "Content-Type": "application/x-www-form-urlencoded"}


@pytest.mark.parametrize("failure", ["timeout", "cancel", "revoked", "bad_redirect", "response"])
async def test_effect_then_interruption_blocks_replay_after_restart(tmp_path, failure, caplog):
    ledger = make_ledger(tmp_path)
    action = uid()
    effects = []
    active = True

    def authorize():
        if not active:
            raise AccountBrowserNetworkError("revoked")

    async def remote(req):
        nonlocal active
        # Receipt must already be committed on an independently opened connection.
        assert reopen(ledger).pending()[0]["status"] == "uncertain"
        effects.append("remote effect")
        if failure == "timeout":
            raise httpx.ReadTimeout("private-error-sentinel")
        if failure == "cancel":
            raise asyncio.CancelledError
        if failure == "revoked":
            active = False
        if failure == "bad_redirect":
            return httpx.Response(307, headers={"Location": "/repeat"})
        return httpx.Response(204)

    net = browser(ledger, remote, authorize)
    net.approve_form(URL, BODY, action_id=action)
    if failure == "response":
        assert (await net.fetch(URL, "POST", HEADERS, BODY)).status == 204
    else:
        with pytest.raises((AccountBrowserNetworkError, asyncio.CancelledError)):
            await net.fetch(URL, "POST", HEADERS, BODY)
    restored = reopen(ledger)
    assert restored.pending()[0]["status"] == (
        "response_received" if failure == "response" else "uncertain"
    )
    retry = browser(restored, remote)
    for identifier in (action, uid()):
        retry.approve_form(URL, BODY, action_id=identifier)
        with pytest.raises(AccountBrowserNetworkError, match="review_required"):
            await retry.fetch(URL, "POST", HEADERS, BODY)
    assert effects == ["remote effect"]
    for file in tmp_path.glob("*.db*"):
        for sentinel in (
            b"private-query-sentinel",
            b"credential-sentinel",
            b"private-error-sentinel",
        ):
            assert sentinel not in file.read_bytes()
            assert sentinel.decode() not in caplog.text


@pytest.mark.parametrize("applied", [True, False])
def test_verification_never_rearms_old_action(tmp_path, applied):
    ledger = make_ledger(tmp_path)
    action = uid()
    ledger.begin(action, origin="https://example.org")
    ledger = reopen(ledger)
    ledger.verify(action, applied=applied)
    assert ledger.pending() == []
    with pytest.raises(AccountBrowserWriteError, match="already_used"):
        ledger.begin(action, origin="https://example.org")
    with pytest.raises(AccountBrowserWriteError, match="state_conflict"):
        ledger.verify(action, applied=not applied)
    ledger.begin(
        uid(), origin="https://example.org"
    )  # Separately approved operation, never an automatic retry.


def test_concurrent_dispatches_have_only_one_winner(tmp_path):
    ledger = make_ledger(tmp_path)

    def begin(_):
        try:
            ledger.begin(uid(), origin="https://example.org")
            return True
        except AccountBrowserWriteError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(begin, range(2))) == 1
    assert len(reopen(ledger).pending()) == 1


def test_receipt_scope_revocation_and_bound(tmp_path):
    ledger = make_ledger(tmp_path)
    action = uid()
    ledger.begin(action, origin="https://example.org")
    other = AccountBrowserWrites(ledger.store, ledger.session_id, uid())
    with pytest.raises(AccountBrowserWriteError, match="scope_denied"):
        other.verify(action, applied=True)
    ledger.verify(action, applied=False)
    for _ in range(127):
        action = uid()
        ledger.begin(action, origin="https://example.org")
        ledger.verify(action, applied=True)
    with pytest.raises(AccountBrowserWriteError, match="write_limit"):
        ledger.begin(uid(), origin="https://example.org")
    with ledger.store.transaction() as db:
        db.execute("DELETE FROM account_sessions WHERE id=?", (ledger.session_id,))
    with pytest.raises(AccountBrowserWriteError, match="scope_denied"):
        ledger.pending()
    assert ledger.store.all("SELECT * FROM account_browser_writes") == []


async def test_failed_tracking_cannot_dispatch(tmp_path, monkeypatch):
    ledger = make_ledger(tmp_path)

    def broken(_, **kwargs):
        raise OSError("private-storage-sentinel")

    monkeypatch.setattr(ledger, "begin", broken)
    net = browser(ledger, lambda _: pytest.fail("Request escaped without durable receipt"))
    net.approve_form(URL, BODY, action_id=uid())
    with pytest.raises(AccountBrowserNetworkError, match="tracking_failed") as error:
        await net.fetch(URL, "POST", HEADERS, BODY)
    assert "private-storage" not in str(error.value)
    with pytest.raises(AccountBrowserNetworkError, match="tracking_required"):
        browser(None, lambda _: None).approve_form(URL, BODY, action_id=uid())


async def test_wrong_origin_and_lost_response_receipt_fail_closed(tmp_path, monkeypatch):
    ledger = make_ledger(tmp_path)
    with pytest.raises(AccountBrowserWriteError, match="scope_denied"):
        ledger.begin(uid(), origin="https://other.example.org")
    assert ledger.pending() == []

    def broken(_):
        raise OSError("private-storage-error")

    monkeypatch.setattr(ledger, "response_received", broken)
    net = browser(ledger, lambda _: httpx.Response(204))
    net.approve_form(URL, BODY, action_id=uid())
    with pytest.raises(AccountBrowserNetworkError, match="tracking_failed"):
        await net.fetch(URL, "POST", HEADERS, BODY)
    assert reopen(ledger).pending()[0]["status"] == "uncertain"


def test_revoked_owner_cannot_verify_or_dispatch(tmp_path):
    ledger = make_ledger(tmp_path)
    action = uid()
    ledger.begin(action, origin="https://example.org")
    with ledger.store.transaction() as db:
        db.execute("UPDATE devices SET revoked=1 WHERE id=?", (ledger.owner_id,))
    with pytest.raises(AccountBrowserWriteError, match="scope_denied"):
        ledger.verify(action, applied=True)
    with pytest.raises(AccountBrowserWriteError, match="scope_denied"):
        ledger.begin(uid(), origin="https://example.org")


def test_v27_upgrade_preserves_session_bytes(tmp_path):
    ledger = make_ledger(tmp_path)
    before = ledger.store.all("SELECT * FROM account_sessions")
    with sqlite3.connect(ledger.store.path) as db:
        db.execute("ALTER TABLE account_grants DROP COLUMN profile_revision")
        db.execute("DROP TABLE account_browser_profiles")
        db.execute("DROP TABLE account_browser_writes")
        db.execute("PRAGMA user_version=27")
    store = Store(tmp_path)
    assert store.all("SELECT * FROM account_sessions") == before
    assert store.all("SELECT * FROM account_browser_writes") == []
    assert len(list(tmp_path.glob(f"before-v27-to-v{SCHEMA_VERSION}-*.db"))) == 1


def test_abrupt_process_exit_leaves_action_blocked(tmp_path):
    ledger = make_ledger(tmp_path)
    action = uid()
    script = """
import os, sys
from dsgpt.storage import Store
from dsgpt.account_browser_writes import AccountBrowserWrites
ledger = AccountBrowserWrites(Store(sys.argv[1]), sys.argv[2], sys.argv[3])
ledger.begin(sys.argv[4], origin='https://example.org')
os._exit(0)
"""
    subprocess.run(
        [sys.executable, "-c", script, str(tmp_path), ledger.session_id, ledger.owner_id, action],
        check=True,
        timeout=10,
        capture_output=True,
    )
    restored = reopen(ledger)
    assert restored.pending()[0]["status"] == "uncertain"
    with pytest.raises(AccountBrowserWriteError, match="already_used"):
        restored.begin(action, origin="https://example.org")
