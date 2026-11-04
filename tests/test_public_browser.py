
import httpx
import pytest
from test_web_retrieval import Bytes

from dsgpt.public_browser import PublicBrowser
from dsgpt.web_retrieval import PublicReader, ResearchError


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/a",
        "http://example.org",
        "https://169.254.169.254/",
        "file:///etc/passwd",
        "https://user:password@example.org",
    ],
)
async def test_broker_rejects_private_or_credentialed_addresses_before_transport(url):
    def denied(request):
        raise AssertionError("Untrusted URL reached transport")

    browser = PublicBrowser(None, None, lambda: httpx.MockTransport(denied))
    with pytest.raises(ResearchError):
        await browser.resource(url)


async def test_resource_cookies_methods_redirects_and_size():
    seen = []

    def respond(request):
        seen.append(request)
        assert (
            request.method == "GET"
            and not request.headers.get("cookie")
            and not request.headers.get("authorization")
        )
        if request.url.path == "/redirect":
            return httpx.Response(
                302, headers={"Location": "/app/index.html", "Set-Cookie": "private=1"}
            )
        if request.url.path == "/private":
            return httpx.Response(302, headers={"Location": "https://10.0.0.1/"})
        return httpx.Response(
            200,
            headers={"Content-Type": "application/javascript", "Set-Cookie": "private=1"},
            stream=Bytes(b"public code"),
        )

    browser = PublicBrowser(None, None, lambda: httpx.MockTransport(respond))
    body, headers, url, status = await browser.resource("https://example.org/redirect")
    assert status == 302 and headers == [
        {"name": "Location", "value": "https://example.org/app/index.html"}
    ]
    body, headers, url, status = await browser.resource("https://example.org/code.js")
    assert body == b"public code" and status == 200
    assert headers == [{"name": "Content-Type", "value": "application/javascript"}]
    with pytest.raises(ResearchError):
        await browser.resource("https://example.org/private")
    assert len(seen) == 3
    browser.transport_factory = lambda: httpx.MockTransport(
        lambda request: httpx.Response(200, stream=Bytes(b"x" * (2 * 1024**2 + 1)))
    )
    with pytest.raises(ResearchError, match="too_large"):
        await browser.resource("https://example.org/large")


async def test_dynamic_fallback_uses_renderer_only_for_script_shell():
    class Render:
        calls = []

        async def render(self, url):
            self.calls.append(url)
            return {"text": "Rendered evidence", "url": url}

    reader = PublicReader(
        lambda: httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"Content-Type": "text/html"},
                stream=Bytes(b'<body>Loading<script src="app.js"></script></body>'),
            )
        )
    )
    reader.browser = Render()
    result = await reader.read("https://example.org/app")
    assert result["text"] == "Rendered evidence"
    assert reader.browser.calls == ["https://example.org/app"]
