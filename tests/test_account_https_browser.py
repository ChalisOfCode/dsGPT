"""Real Chromium and TLS integration, NOT production Docker/DNS/DPAPI acceptance.

The container, endpoint mapping and vault protector are explicit test fixtures.
Only fixed input commands reach Chromium; no test reads cookies or executes CDP.
"""

import asyncio
import shutil

import pytest
from account_https_site import https_site
from test_account_browser_bridge import FixtureSandbox, needs_browser
from test_account_browser_profiles import vault
from test_account_browser_writes import make_ledger, reopen
from test_account_https_broker import ORIGIN, LoopbackTLS

from dsgpt.account_browser_bridge import AccountBrowserBridge
from dsgpt.account_browser_network import AccountBrowserNetwork
from dsgpt.storage import uid


@needs_browser
@pytest.mark.skipif(shutil.which("openssl") is None, reason="TLS fixture requires OpenSSL")
async def test_browser_tls_login_restart_and_lost_write(tmp_path, caplog):
    await run_browser_tls_scenario(tmp_path, caplog, FixtureSandbox)


async def run_browser_tls_scenario(tmp_path, caplog, sandbox_factory):
    """Share the same server assertions with the opt-in production Docker check."""
    with https_site() as (site, trust):
        endpoint, site.origin = site.origin, ORIGIN
        ledger = make_ledger(tmp_path / "store")
        seen = []
        form_events = []

        class ObservedBridge(AccountBrowserBridge):
            async def _resource(self, row, *, review=None):
                if row.get("method") == "POST":
                    headers = {k.lower(): v for k, v in row.get("headers", {}).items()}
                    # Fixed booleans only: never log a body, URL or header value.
                    form_events.append((row.get("document_form") is True,
                                        headers.get("origin") == ORIGIN,
                                        headers.get("content-type") ==
                                        "application/x-www-form-urlencoded"))
                await super()._resource(row, review=review)

        class ObservedTLS(LoopbackTLS):
            async def handle_async_request(self, request):
                response = await super().handle_async_request(request)
                # Observations contain no body, query, cookie or credential.
                seen.append((request.method, request.url.path, response.status_code))
                return response

        def bridge(root, receipts):
            root.mkdir()
            net = AccountBrowserNetwork(
                ORIGIN, authorize=lambda: None, writes=receipts,
                transport_factory=lambda validator: ObservedTLS(validator, endpoint, trust),
            )
            return ObservedBridge(sandbox_factory(root), vault(receipts), net, lambda: None)

        async def page(browser, path):
            await browser.navigate(ORIGIN + path)
            await browser.frame()
            assert ("GET", path, 200) in seen

        async def submit(browser, path, value):
            await browser.click(40, 40)
            await browser.type_text(value)
            await browser.frame()  # observe the current document before submission
            action = uid()
            reviewed = []

            async def review(actual):
                assert actual == path
                reviewed.append(actual)
                return action

            await browser.submit({"op": "click", "x": 40, "y": 100}, review)
            assert reviewed == [path], ("review_missing", form_events)
            return action

        async def until(browser, observed):
            async with asyncio.timeout(5):
                while not observed():
                    await browser.frame()
                    await asyncio.sleep(0.05)

        first = bridge(tmp_path / "first", ledger)
        try:
            await first.start()
            await page(first, "/login")
            action = await submit(first, "/login", site.password)
            await page(first, "/mfa")  # actual Chromium-selected challenge cookie
            assert not site.authenticated
            ledger.verify(action, applied=True)
            action = await submit(first, "/mfa", site.mfa)
            await page(first, "/app")
            await until(first, lambda: site.storage_ready > 0)
            assert site.authenticated and site.effects == 0
            ledger.verify(action, applied=True)
            assert await first.close() == 1
        finally:
            await first.abort()

        ledger = reopen(ledger)
        second = bridge(tmp_path / "second", ledger)
        try:
            await second.start()
            await page(second, "/restore")
            # This page only reads storage; it never recreates either marker.
            # Its proof request also requires the restored HttpOnly cookie.
            await until(second, lambda: site.storage_restored == 1)
            await page(second, "/interrupt-form")
            action = await submit(second, "/interrupt", "change")
            assert site.effects == 1
            assert ledger.pending()[0]["status"] == "uncertain"
            assert ledger.pending()[0]["id"] == action
        finally:
            await second.abort()

        ledger = reopen(ledger)
        third = bridge(tmp_path / "third", ledger)
        try:
            await third.start()
            await page(third, "/interrupt-form")
            await submit(third, "/interrupt", "change")
            assert site.effects == 1  # fresh approval cannot bypass durable uncertainty
            assert ledger.pending()[0]["id"] == action
        finally:
            await third.abort()
        for secret in (site.password, site.mfa, site.csrf, site.session, site.challenge):
            assert secret not in caplog.text
            for file in (tmp_path / "store").glob("*.db*"):
                assert secret.encode() not in file.read_bytes()
