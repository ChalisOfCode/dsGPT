"""Real TLS plus production broker/ledger; explicit test-only endpoint mapping.

This does not validate PublicHTTPS DNS pinning, Docker, Chromium, owner UI or
Windows protection. Mapping is confined to this injected test transport.
"""

import shutil
from http.cookies import SimpleCookie
from urllib.parse import urlencode

import httpx
import pytest
from account_https_site import https_site
from test_account_browser_writes import make_ledger, reopen

from dsgpt.account_browser_network import AccountBrowserNetwork, AccountBrowserNetworkError
from dsgpt.storage import uid

pytestmark = pytest.mark.skipif(
    shutil.which("openssl") is None, reason="TLS fixture requires OpenSSL"
)
ORIGIN = "https://example.org"


class LoopbackTLS(httpx.AsyncBaseTransport):
    def __init__(self, validator, endpoint, trust):
        self.validator, self.endpoint = validator, httpx.URL(endpoint)
        self.transport = httpx.AsyncHTTPTransport(verify=trust, retries=0, trust_env=False)

    async def handle_async_request(self, request):
        self.validator(request.url)
        # Only this fixture substitutes destination and TLS hostname; trust
        # remains enforced against its ephemeral certificate, never verify=False.
        assert request.url.host == "example.org"
        url = self.endpoint.copy_with(path=request.url.path, query=request.url.query or None)
        forwarded = httpx.Request(request.method, url, headers=request.headers,
                                  content=await request.aread())
        return await self.transport.handle_async_request(forwarded)

    async def aclose(self):
        await self.transport.aclose()


def broker(site, trust, endpoint, ledger):
    return AccountBrowserNetwork(
        ORIGIN, authorize=lambda: None, writes=ledger,
        transport_factory=lambda validator: LoopbackTLS(validator, endpoint, trust),
    )


def cookie(response):
    values = SimpleCookie()
    for name, value in response.headers:
        if name == "set-cookie":
            values.load(value)
    return "; ".join(f"{key}={value.value}" for key, value in values.items())


async def post(net, site, path, field, value, cookies="", action=None):
    body = urlencode({"csrf": site.csrf, field: value}).encode()
    identifier = action or uid()
    net.approve_form(ORIGIN + path, body, action_id=identifier)
    response = await net.fetch(ORIGIN + path, "POST", {
        "Origin": ORIGIN, "Content-Type": "application/x-www-form-urlencoded",
        "Cookie": cookies,
    }, body)
    return identifier, response


@pytest.mark.parametrize("path,expected", [("/update", "response_received"),
                                           ("/interrupt", "uncertain")])
async def test_actual_tls_effect_remains_blocked_across_ledger_restart(
    tmp_path, caplog, path, expected,
):
    with https_site() as (site, trust):
        endpoint, site.origin = site.origin, ORIGIN
        ledger = make_ledger(tmp_path)
        net = broker(site, trust, endpoint, ledger)
        action, response = await post(net, site, "/login", "password", site.password)
        assert response.status == 303
        challenge = cookie(response)
        # A fresh read verifies each synthetic login stage before the test's
        # trusted controller confirms it. HTTP submission success alone is not used.
        assert (await net.fetch(ORIGIN + "/mfa", "GET", {"Cookie": challenge})).status == 200
        ledger.verify(action, applied=True)
        action, response = await post(net, site, "/mfa", "code", site.mfa, challenge)
        session = cookie(response)
        response = await net.fetch(ORIGIN + "/private.txt", "GET", {"Cookie": session})
        assert response.body == b"Controlled account. Updates: 0"
        ledger.verify(action, applied=True)
        action = uid()
        if path == "/interrupt":
            with pytest.raises(AccountBrowserNetworkError, match="request_failed"):
                await post(net, site, path, "value", "change", session, action)
        else:
            await post(net, site, path, "value", "change", session, action)
        assert site.effects == 1
        restored = reopen(ledger)
        assert restored.pending()[0]["status"] == expected
        net = broker(site, trust, endpoint, restored)
        for identifier in (action, uid()):
            with pytest.raises(AccountBrowserNetworkError, match="review_required"):
                await post(net, site, path, "value", "change", session, identifier)
        assert site.effects == 1
        response = await net.fetch(ORIGIN + "/private.txt", "GET", {"Cookie": session})
        assert response.body == b"Controlled account. Updates: 1"
        restored.verify(action, applied=True)
        with pytest.raises(AccountBrowserNetworkError, match="review_required"):
            await post(net, site, path, "value", "change", session, action)
        assert site.effects == 1
        for secret in (site.password, site.mfa, site.csrf, site.session, site.challenge):
            assert secret not in caplog.text
            for file in tmp_path.glob("*.db*"):
                assert secret.encode() not in file.read_bytes()
