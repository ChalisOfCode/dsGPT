import httpx
import pytest
from test_web_retrieval import Bytes

from dsgpt.account_browser_network import (
    MAX_RESOURCE,
    AccountBrowserNetwork,
    AccountBrowserNetworkError,
)

ORIGIN = "https://example.org"
FORM = ORIGIN + "/sign-in"
HEADERS = {"Origin": ORIGIN, "Content-Type": "application/x-www-form-urlencoded"}
BODY = b"challenge=fixture-only"


def network(handler, *, authorize=lambda: None, clock=lambda: 0):
    def factory(validator):
        async def request(req):
            validator(req.url)
            return await handler(req)

        return httpx.MockTransport(request)

    return AccountBrowserNetwork(
        ORIGIN, authorize=authorize, transport_factory=factory, clock=clock
    )


async def test_only_approved_exact_form_reaches_transport_and_cannot_replay():
    seen = []
    now = [0]

    async def respond(req):
        seen.append((str(req.url), req.method))
        assert await req.aread() == BODY
        assert req.headers["origin"] == ORIGIN
        return httpx.Response(303, headers={"Location": "/welcome"})

    browser = network(respond, clock=lambda: now[0])
    with pytest.raises(AccountBrowserNetworkError, match="not_approved"):
        await browser.fetch(FORM, "POST", HEADERS, BODY)
    browser.approve_form(FORM, BODY)
    with pytest.raises(AccountBrowserNetworkError, match="not_approved"):
        await browser.fetch(FORM, "POST", HEADERS, BODY + b"x")
    browser.approve_form(FORM, BODY)
    now[0] = 30
    with pytest.raises(AccountBrowserNetworkError, match="not_approved"):
        await browser.fetch(FORM, "POST", HEADERS, BODY)
    browser.approve_form(FORM, BODY)
    result = await browser.fetch(FORM, "POST", HEADERS, BODY)
    assert result.status == 303
    assert result.headers == (("location", ORIGIN + "/welcome"),)
    with pytest.raises(AccountBrowserNetworkError, match="not_approved"):
        await browser.fetch(FORM, "POST", HEADERS, BODY)
    assert seen == [(FORM, "POST")]


async def test_same_origin_cookie_is_forwarded_and_duplicate_set_cookie_is_preserved():
    async def respond(req):
        assert req.headers["cookie"] == "fixture_session=one"
        assert "authorization" not in req.headers
        assert "proxy-authorization" not in req.headers
        return httpx.Response(
            200,
            headers=[
                ("Set-Cookie", "fixture_a=one; Secure; HttpOnly"),
                ("Set-Cookie", "fixture_b=two; Secure"),
                ("Content-Security-Policy", "default-src 'self'"),
                ("Alt-Svc", 'h3=":443"'),
            ],
            stream=Bytes(b"synthetic page"),
        )

    result = await network(respond).fetch(
        ORIGIN + "/welcome",
        "GET",
        {
            "Cookie": "fixture_session=one",
            "Authorization": "fixture",
            "Proxy-Authorization": "fixture",
        },
    )
    assert result.body == b"synthetic page"
    assert result.headers == (
        ("set-cookie", "fixture_a=one; Secure; HttpOnly"),
        ("set-cookie", "fixture_b=two; Secure"),
        ("content-security-policy", "default-src 'self'"),
    )
    assert "fixture" not in repr(result)


@pytest.mark.parametrize(
    "target", ["https://example.org.evil.org/", "https://127.0.0.1/", "http://example.org/"]
)
async def test_out_of_scope_requests_never_reach_transport(target):
    async def denied(req):
        pytest.fail("Invalid destination reached network")

    with pytest.raises(AccountBrowserNetworkError, match="origin_denied"):
        await network(denied).fetch(target, "GET", {"Cookie": "fixture_session=one"})


@pytest.mark.parametrize(
    "status,location,method",
    [
        (302, "//other.example.org/sink", "GET"),
        (307, "/sign-in-replay", "POST"),
    ],
)
async def test_redirect_does_not_send_secrets_to_a_second_request(status, location, method):
    seen = []

    async def respond(req):
        seen.append(str(req.url))
        return httpx.Response(status, headers={"Location": location})

    browser = network(respond)
    if method == "POST":
        browser.approve_form(FORM, BODY)
    with pytest.raises(AccountBrowserNetworkError, match="denied"):
        await browser.fetch(FORM, method, HEADERS, BODY if method == "POST" else b"")
    assert seen == [FORM]


async def test_revocation_discards_response_and_oversized_response_fails_closed():
    active = True

    def authorize():
        if not active:
            raise AccountBrowserNetworkError("account_browser_revoked")

    async def revoked(req):
        nonlocal active
        active = False
        return httpx.Response(200, stream=Bytes(b"private content"))

    with pytest.raises(AccountBrowserNetworkError, match="revoked"):
        await network(revoked, authorize=authorize).fetch(FORM, "GET", {})

    async def oversized(req):
        return httpx.Response(200, stream=Bytes(b"x" * (MAX_RESOURCE + 1)))

    with pytest.raises(AccountBrowserNetworkError, match="request_failed"):
        await network(oversized).fetch(FORM, "GET", {})
