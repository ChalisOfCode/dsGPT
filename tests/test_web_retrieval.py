import gzip
import json
import socket

import httpx
import pytest

from dsgpt.downloads import PublicHTTPS
from dsgpt.web_retrieval import (
    LocalSearch,
    PageText,
    PublicReader,
    ResearchError,
    limited_body,
    local_search_origin,
    public_url,
    validate_public_request,
)


class Bytes(httpx.AsyncByteStream):
    def __init__(self, content):
        self.content = content

    async def __aiter__(self):
        yield self.content


@pytest.mark.parametrize(
    "url",
    [
        "http://example.org/",
        "file:///etc/passwd",
        "ftp://example.org/",
        "https://127.0.0.1/",
        "https://[::1]/",
        "https://169.254.169.254/",
        "https://10.0.0.1/",
        "https://localhost/",
        "https://device.local/",
        "https://example.org:8443/",
        "https://user:secret@example.org/",
        "https://example.org/\nsecret",
        "https://example.org\\x",
    ],
)
def test_private_non_https_or_credentialed_urls_are_rejected(url):
    with pytest.raises(ResearchError):
        public_url(url)


async def test_public_page_extraction_metadata_links_redirects_and_no_cookies():
    calls = []

    def handle(request):
        calls.append(request)
        assert "authorization" not in request.headers and "cookie" not in request.headers
        if len(calls) == 1:
            return httpx.Response(302, headers={"Location": "/document", "Set-Cookie": "secret=x"})
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            stream=Bytes(b"""
            <html><head><title>Official source</title>
            <meta property="article:published_time" content="2026-10-18"></head>
            <body><script>secret-script</script><div hidden>secret-hidden</div>
            <p>The public answer is COBALT.</p><a href="/next">Next page</a>
            <a href="http://127.0.0.1/admin">Denied local link</a></body></html>"""),
        )

    result = await PublicReader(lambda: httpx.MockTransport(handle)).read(
        "https://example.org/start"
    )
    assert result["title"] == "Official source" and result["published_at"] == "2026-10-18"
    assert "COBALT" in result["text"] and "secret" not in result["text"]
    assert result["links"] == ["https://example.org/next"]
    assert result["final_url"] == "https://example.org/document"
    assert len(result["content_sha256"]) == 64 and len(calls) == 2


def test_main_article_preserves_inline_sentences_and_highlighted_configuration():
    page = PageText("https://example.org/docs")
    page.feed("""<nav>Irrelevant search menu</nav><div>Sidebar boilerplate</div>
    <article role="main"><h1>Configuration</h1><p>Enable <code>json</code> in
    <code>search.formats</code>.</p><pre><span>search</span><span>:</span>
      <span>formats</span>:
        - <span>json</span></pre><p>Last paragraph.</p></article>""")
    assert "Sidebar" not in page.text and "menu" not in page.text
    assert "Enable json in search.formats." in page.text
    assert "search:\n      formats:\n        - json" in page.text
    assert "Last paragraph." in page.text


def test_excessively_nested_html_is_rejected_before_expensive_parsing():
    page = PageText("https://example.org/docs")
    with pytest.raises(ResearchError, match="research_page_too_complex"):
        page.feed("<div>" * 300)


async def test_redirect_cannot_contact_private_service_even_with_injected_transport():
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(302, headers={"Location": "https://169.254.169.254/secret"})

    with pytest.raises(ResearchError, match="research_url_not_allowed"):
        await PublicReader(lambda: httpx.MockTransport(handle)).read("https://example.org/")
    assert len(calls) == 1


@pytest.mark.parametrize("addresses", [["127.0.0.1"], ["8.8.8.8", "10.0.0.1"], ["::1"]])
async def test_research_transport_rejects_private_or_mixed_dns(monkeypatch, addresses):
    import asyncio

    async def resolve(*args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443)) for address in addresses
        ]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    reader = PublicReader(lambda: PublicHTTPS(validator=validate_public_request))
    with pytest.raises(ResearchError, match="research_address_not_public"):
        await reader.read("https://example.org/")


@pytest.mark.parametrize(
    "content_type,status,code",
    [
        ("text/html", 403, "research_source_inaccessible"),
        ("application/pdf", 200, "research_content_unsupported"),
        ("image/png", 200, "research_content_unsupported"),
    ],
)
async def test_unsupported_or_inaccessible_pages_fail_honestly(content_type, status, code):
    with pytest.raises(ResearchError, match=code):
        await PublicReader(
            lambda: httpx.MockTransport(
                lambda _: httpx.Response(
                    status, headers={"Content-Type": content_type}, stream=Bytes(b"content")
                )
            )
        ).read("https://example.org/")


async def test_gzip_is_bounded_before_decompression_can_expand_a_bomb():
    response = httpx.Response(
        200, headers={"Content-Encoding": "gzip"}, stream=Bytes(gzip.compress(b"x" * 100000))
    )
    with pytest.raises(ResearchError, match="research_response_too_large"):
        await limited_body(response, 1024)
    response = httpx.Response(
        200, headers={"Content-Encoding": "gzip"}, stream=Bytes(gzip.compress(b"normal"))
    )
    assert await limited_body(response, 1024) == b"normal"


@pytest.mark.parametrize(
    "origin",
    [
        "https://search.example.org",
        "http://localhost:8000",
        "http://127.0.0.1:8000/private",
        "http://user:secret@127.0.0.1:8000",
        "http://10.0.0.1:80",
    ],
)
def test_searxng_uses_only_an_explicit_loopback_origin(origin):
    with pytest.raises(ValueError):
        local_search_origin(origin)


async def test_searxng_form_protocol_filters_private_results_and_reports_engine_failures():
    def handle(request):
        assert request.url == "http://127.0.0.1:8888/search"
        assert request.method == "POST" and b"format=json" in request.content
        assert "authorization" not in request.headers
        return httpx.Response(
            200,
            stream=Bytes(
                json.dumps(
                    {
                        "results": [
                            {
                                "url": "https://example.org/docs",
                                "title": "Docs",
                                "content": "Snippet",
                            },
                            {"url": "http://127.0.0.1/"},
                            {"url": "https://example.org/docs"},
                        ],
                        "unresponsive_engines": [["an-engine", "timeout"]],
                    }
                ).encode()
            ),
        )

    result = await LocalSearch("http://127.0.0.1:8888", lambda: httpx.MockTransport(handle)).search(
        "docs"
    )
    assert len(result["results"]) == 1 and result["engine_failures"] == 1
    with pytest.raises(ResearchError, match="research_search_not_configured"):
        await LocalSearch().search("docs")
