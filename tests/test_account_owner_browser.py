"""Controller plus real guest/TLS scenario, with explicit container/vault fixtures.

Production Docker and native DPAPI are separately validated boundaries. This test
does not replace them; it closes the controller/real-browser integration gap.
"""

import asyncio
from types import SimpleNamespace

import pytest
from account_https_site import https_site
from fastapi import HTTPException
from test_account_browser_bridge import FixtureSandbox, needs_browser
from test_account_grants import setup
from test_account_https_broker import ORIGIN, LoopbackTLS
from test_account_sessions import FixtureProtection

from dsgpt.account_browser_bridge import AccountBrowserBridge
from dsgpt.account_browser_handoff import (
    AccountBrowserHandoffs,
    BrowserClick,
    BrowserDecision,
    BrowserText,
    BrowserVerification,
)
from dsgpt.account_sessions import AccountGrantCreate, AccountSessions, BrowserSessionCreate
from dsgpt.storage import Store, uid


@needs_browser
async def test_owner_review_save_restart_delegated_read_expiry_and_revoke(tmp_path, caplog):
    with https_site() as (site, trust):
        endpoint, site.origin = site.origin, ORIGIN
        store = Store(tmp_path / "store")
        owner, device, other, task, other_task = setup(store)
        owner_id = owner["device_id"]
        protection = FixtureProtection()
        sequence = 0

        def transport(validator):
            return LoopbackTLS(validator, endpoint, trust)

        def bridge_factory(sandbox, vault, network, authorize):
            nonlocal sequence
            sequence += 1
            root = tmp_path / str(sequence)
            root.mkdir()
            network._transport = transport  # Explicit test endpoint/CA mapping only.
            return AccountBrowserBridge(FixtureSandbox(root), vault, network, authorize)

        def services():
            sessions = AccountSessions(Store(tmp_path / "store"), protection, transport)
            controller = AccountBrowserHandoffs(
                sessions, SimpleNamespace(sandbox=object(), ready=True), bridge_factory,
            )
            return sessions, controller

        sessions, controller = services()
        session = await sessions.create_browser(owner_id, BrowserSessionCreate(
            label="Controlled site", origin=ORIGIN, read_path="/entry",
        ))
        session_id = session["id"]
        generation = (await controller.start(owner_id, session_id))["handoff_id"]
        scope = (owner_id, session_id, generation)

        async def frame():
            png, observation = await controller.operate(*scope, "frame")
            assert png.startswith(b"\x89PNG")
            return observation

        async def submit(value, expected_path):
            await controller.operate(*scope, "input", BrowserClick(op="click", x=40, y=40))
            await controller.operate(*scope, "input", BrowserText(op="text", text=value))
            observation = await frame()
            command = BrowserClick(op="click", x=40, y=100)
            submission = controller.submit(*scope, observation, command)["submission_id"]
            async with asyncio.timeout(8):
                while True:
                    status = controller.submission_status(*scope)
                    if status["review"]:
                        break
                    await asyncio.sleep(0.02)
                review = status["review"]
                assert review["path"] == expected_path
                decision = BrowserDecision(review_id=review["review_id"], approve=True)
                controller.decide(*scope, submission, decision)
                with pytest.raises(HTTPException):
                    controller.decide(*scope, submission, decision)
                while controller.submission_status(*scope)["state"] == "running":
                    await asyncio.sleep(0.02)
            status = controller.submission_status(*scope)
            assert status["state"] == "finished"
            receipt, = status["unverified"]
            with pytest.raises(HTTPException):
                controller.submit(*scope, observation, command)
            with pytest.raises(HTTPException):
                controller.verify(*scope, BrowserVerification(
                    observation_id=uid(), action_id=receipt["id"], applied=True,
                ))
            return receipt["id"]

        try:
            action = await submit(site.password, "/login")
            assert not site.authenticated
            observation = await frame()  # Fresh MFA document, after dispatch quiescence.
            controller.verify(*scope, BrowserVerification(
                observation_id=observation, action_id=action, applied=True,
            ))
            action = await submit(site.mfa, "/mfa")
            assert site.authenticated
            async with asyncio.timeout(5):
                while not site.storage_ready:
                    await frame()
                    await asyncio.sleep(0.02)
            observation = await frame()
            controller.verify(*scope, BrowserVerification(
                observation_id=observation, action_id=action, applied=True,
            ))
            await controller.operate(*scope, "save")
            assert controller.active is None
            with pytest.raises(HTTPException):
                await controller.operate(*scope, "frame")
        finally:
            await controller.stop()

        # Fresh service/controller uses only persisted authority and saved profile.
        sessions, controller = services()
        grant = await sessions.grant(owner_id, session_id, AccountGrantCreate(
            task_id=task, task_revision=1, device_id=device["device_id"], profile_revision=1,
        ))

        async def read(actor=device["device_id"], target=task):
            return await sessions.read_grant(actor, target, grant["id"],
                                             browser_reader=controller.read_grant)

        try:
            assert (await read())["text"] == "Controlled account. Updates: 0"
            assert controller.delegated is None
            for actor, target in [(other["device_id"], task), (device["device_id"], other_task)]:
                with pytest.raises(HTTPException) as denied:
                    await read(actor, target)
                assert denied.value.status_code == 403
            site.expire()
            with pytest.raises(HTTPException):
                await read()  # Login HTML must never become delegated private text.
            assert controller.delegated is None
            await sessions.revoke_grant(owner_id, session_id, grant["id"])
            with pytest.raises(HTTPException) as denied:
                await read()
            assert denied.value.status_code == 403
            await sessions.revoke(owner_id, session_id)
            assert not store.all("SELECT * FROM account_browser_profiles")
            assert not store.all("SELECT * FROM account_browser_writes")
        finally:
            await controller.stop()
        for secret in (site.password, site.mfa, site.session, site.challenge, site.csrf):
            assert secret not in caplog.text
            for file in (tmp_path / "store").glob("*.db*"):
                assert secret.encode() not in file.read_bytes()
