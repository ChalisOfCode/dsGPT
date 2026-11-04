"""Read-only, public HTTPS retrieval. No cookies, scripts, private-network or proxy fallback."""

import asyncio
import base64
import hashlib
import ipaddress
import re
import zlib
from html.parser import HTMLParser
from urllib.parse import urljoin

import httpx
from fastapi import HTTPException

from .downloads import DownloadError, PublicHTTPS
from .storage import utcnow

MAX_RESPONSE = 4 * 1024**2
MAX_TEXT = 80000


class ResearchError(Exception):
    pass


def public_url(raw):
    if not isinstance(raw, str) or len(raw) > 4096 or any(ord(c) < 32 for c in raw):
        raise ResearchError("research_url_not_allowed")
    try:
        url = httpx.URL(raw)
        if (
            url.scheme != "https"
            or url.port not in (None, 443)
            or url.userinfo
            or not url.host
            or "\\" in raw
            or url.host.endswith(".")
        ):
            raise ValueError()
        host = url.host.lower()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if "." not in host or host.endswith((".localhost", ".local", ".internal", ".invalid")):
                raise ValueError() from None
        else:
            if not address.is_global or address.is_multicast:
                raise ValueError()
        return str(url.copy_with(fragment=None))
    except (ValueError, httpx.InvalidURL) as exc:
        raise ResearchError("research_url_not_allowed") from exc


def validate_public_request(url):
    public_url(str(url))


class PageText(HTMLParser):
    """Extract readable text/links/date metadata without rendering or running page content."""

    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base, self.stack = base, []
        self.parts, self.main_parts, self.titles, self.links, self.dates = [], [], [], [], []
        self.count, self.main_count = 0, 0
        self.nodes = 0
        self.in_title = False

    def handle_starttag(self, tag, attrs):
        self.nodes += 1
        if self.nodes > 50000 or len(self.stack) > 256:
            raise ResearchError("research_page_too_complex")
        attrs = dict(attrs)
        hidden = (
            tag
            in {
                "script",
                "style",
                "noscript",
                "iframe",
                "svg",
                "canvas",
                "template",
                "nav",
                "footer",
            }
            or "hidden" in attrs
            or attrs.get("aria-hidden") == "true"
            or bool(
                re.search(
                    r"display\s*:\s*none|visibility\s*:\s*hidden", attrs.get("style") or "", re.I
                )
            )
        )
        if tag not in {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }:
            main = tag in {"main", "article"} or attrs.get("role") == "main"
            self.stack.append(
                (
                    tag,
                    hidden or bool(self.stack and self.stack[-1][1]),
                    main or bool(self.stack and self.stack[-1][2]),
                )
            )
        if self.stack and self.stack[-1][1]:
            return
        if tag in self.block_tags:
            self.append_text("\n")
        if tag == "title":
            self.in_title = True
        if tag == "meta" and (attrs.get("property") or attrs.get("name") or "").lower() in {
            "article:published_time",
            "datepublished",
            "date",
            "pubdate",
            "dc.date.issued",
        }:
            value = attrs.get("content") or ""
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[T ][0-9:.+Z-]+)?", value):
                self.dates.append(value[:60])
        if tag == "a" and attrs.get("href") and len(self.links) < 60:
            try:
                link = public_url(urljoin(self.base, attrs["href"]))
            except ResearchError:
                return
            if link not in self.links:
                self.links.append(link)

    def handle_endtag(self, tag):
        if tag in self.block_tags and not (self.stack and self.stack[-1][1]):
            self.append_text("\n")
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.stack and self.stack[-1][1]:
            return
        # Inline markup must not split sentences or syntax-highlighted code tokens.
        text = data if any(t[0] == "pre" for t in self.stack) else re.sub(r"\s+", " ", data)
        if self.in_title:
            self.titles.append(text[:300])
        elif text:
            self.append_text(text)

    block_tags = {
        "p",
        "div",
        "section",
        "article",
        "main",
        "pre",
        "blockquote",
        "li",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "dt",
        "dd",
        "tr",
        "br",
        "hr",
    }

    def append_text(self, text):
        if self.count < MAX_TEXT:
            piece = text[: MAX_TEXT - self.count]
            self.parts.append(piece)
            self.count += len(piece)
        if self.stack and self.stack[-1][2] and self.main_count < MAX_TEXT:
            piece = text[: MAX_TEXT - self.main_count]
            self.main_parts.append(piece)
            self.main_count += len(piece)

    @property
    def text(self):
        selected = self.main_parts if "".join(self.main_parts).strip() else self.parts
        return re.sub(r"\n[ \t]*\n+", "\n\n", "".join(selected)).strip()


async def limited_body(response, limit=MAX_RESPONSE):
    encoding = response.headers.get("content-encoding", "identity").lower()
    if encoding not in {"identity", "gzip"}:
        raise ResearchError("research_encoding_unsupported")
    decoder = zlib.decompressobj(31) if encoding == "gzip" else None
    raw_count, data = 0, bytearray()
    async for chunk in response.aiter_raw(64 * 1024):
        raw_count += len(chunk)
        if raw_count > limit:
            raise ResearchError("research_response_too_large")
        if decoder:
            chunk = decoder.decompress(chunk, limit - len(data) + 1)
            if decoder.unconsumed_tail:
                raise ResearchError("research_response_too_large")
        data.extend(chunk)
        if len(data) > limit:
            raise ResearchError("research_response_too_large")
    if decoder and (not decoder.eof or decoder.unused_data):
        raise ResearchError("research_invalid_encoding")
    return bytes(data)


class PublicReader:
    def __init__(self, transport_factory=None, documents=None):
        self.documents = documents
        self.browser = None
        self.transport_factory = transport_factory or (
            lambda: PublicHTTPS(validator=validate_public_request)
        )

    async def read(self, raw):
        url = public_url(raw)
        try:
            async with asyncio.timeout(180 if self.documents else 35):
                async with httpx.AsyncClient(
                    transport=self.transport_factory(),
                    trust_env=False,
                    follow_redirects=False,
                    timeout=httpx.Timeout(15, connect=10),
                    headers={
                        "Accept-Encoding": "identity",
                        "User-Agent": "dsGPT-research/0.3",
                        "Accept": "text/html,text/plain,application/json;q=0.8",
                    },
                ) as client:
                    for _ in range(6):
                        # Each hop is normalized and public DNS/IP-pinned independently.
                        url = public_url(url)
                        # No cookies survive a redirect or a previous response.
                        client.cookies.clear()
                        async with client.stream("GET", url) as response:
                            if response.status_code in {301, 302, 303, 307, 308}:
                                target = response.headers.get("location")
                                if not target:
                                    raise ResearchError("research_invalid_redirect")
                                url = public_url(urljoin(url, target))
                                continue
                            if response.status_code != 200:
                                raise ResearchError("research_source_inaccessible")
                            content_type = (
                                response.headers.get("content-type", "").split(";")[0].lower()
                            )
                            if content_type not in {
                                "text/html",
                                "application/xhtml+xml",
                                "text/plain",
                                "application/json",
                                *(["application/pdf"] if self.documents else []),
                            }:
                                raise ResearchError("research_content_unsupported")
                            body = await limited_body(
                                response,
                                524288 if content_type == "application/pdf" else MAX_RESPONSE,
                            )
                            extraction = None
                            if content_type == "application/pdf":
                                try:
                                    value = (
                                        await self.documents.prepare(
                                            [
                                                {
                                                    "name": "public-source.pdf",
                                                    "original_base64": base64.b64encode(
                                                        body
                                                    ).decode(),
                                                }
                                            ]
                                        )
                                    )[0]
                                except HTTPException as exc:
                                    raise ResearchError(
                                        "research_pdf_extraction_unavailable"
                                    ) from exc
                                text, extraction = value["text"], value["document"]
                            else:
                                text = body.decode(response.encoding or "utf-8", errors="replace")
                            if content_type in {"text/html", "application/xhtml+xml"}:
                                page = PageText(url)
                                page.feed(text)
                                title = " ".join(page.titles)[:300] or httpx.URL(url).host
                                content, links = page.text, page.links
                                published = page.dates[0] if page.dates else None
                            else:
                                content, title, links, published = (
                                    text[:MAX_TEXT],
                                    httpx.URL(url).host,
                                    [],
                                    None,
                                )
                            if (
                                self.browser
                                and content_type in {"text/html", "application/xhtml+xml"}
                                and "<script" in text.lower()
                                and len(content.strip()) < 120
                            ):
                                return await self.browser.render(url)
                            if not content.strip():
                                raise ResearchError("research_no_readable_content")
                            return {
                                "url": raw,
                                "final_url": url,
                                "title": title,
                                "text": content,
                                "links": links,
                                "published_at": published,
                                "published_at_source": "page_metadata_unverified"
                                if published
                                else None,
                                "retrieved_at": utcnow(),
                                "content_sha256": hashlib.sha256(body).hexdigest(),
                                "text_truncated": len(content) >= MAX_TEXT - 1,
                                "content_type": content_type,
                                **({"extraction": extraction} if extraction else {}),
                            }
                    raise ResearchError("research_too_many_redirects")
        except ResearchError:
            raise
        except DownloadError as exc:
            raise ResearchError("research_address_not_public") from exc
        except (OSError, httpx.HTTPError, TimeoutError, ValueError, zlib.error, LookupError) as exc:
            raise ResearchError("research_fetch_failed") from exc


def local_search_origin(raw):
    if raw is None:
        return None
    try:
        url = httpx.URL(raw)
        if (
            url.scheme != "http"
            or url.host not in {"127.0.0.1", "::1"}
            or not url.port
            or url.userinfo
            or url.query
            or url.fragment
            or url.path not in {"", "/"}
        ):
            raise ValueError()
        return str(url).rstrip("/")
    except (ValueError, httpx.InvalidURL) as exc:
        raise ValueError(
            "Search must use an explicitly configured literal loopback origin"
        ) from exc


class LocalSearch:
    """SearXNG JSON API; no public-instance discovery, credentials or paid provider fallback."""

    def __init__(self, origin=None, transport_factory=None):
        self.origin = local_search_origin(origin)
        self.transport_factory = transport_factory

    async def search(self, query):
        if not self.origin:
            raise ResearchError("research_search_not_configured")
        if not query.strip() or len(query) > 1000:
            raise ResearchError("research_query_invalid")
        try:
            async with asyncio.timeout(30):
                async with httpx.AsyncClient(
                    trust_env=False,
                    follow_redirects=False,
                    timeout=20,
                    transport=self.transport_factory() if self.transport_factory else None,
                    headers={"Accept-Encoding": "identity"},
                ) as client:
                    async with client.stream(
                        "POST", self.origin + "/search", data={"q": query, "format": "json"}
                    ) as response:
                        if response.status_code != 200:
                            raise ResearchError("research_search_unavailable")
                        import json

                        payload = json.loads(await limited_body(response, 1024**2))
            if (
                not isinstance(payload, dict)
                or not isinstance(payload.get("results"), list)
                or not isinstance(payload.get("unresponsive_engines", []), list)
            ):
                raise ResearchError("research_search_invalid_response")
            results = []
            for result in payload.get("results", [])[:20]:
                try:
                    url = public_url(result["url"])
                except (ResearchError, KeyError, TypeError):
                    continue
                if url in {r["url"] for r in results}:
                    continue
                results.append(
                    {
                        "url": url,
                        "title": str(result.get("title", ""))[:300],
                        "snippet": str(result.get("content", ""))[:1500],
                    }
                )
            return {
                "query": query,
                "results": results,
                "engine_failures": len(payload.get("unresponsive_engines", [])),
                "retrieved_at": utcnow(),
            }
        except ResearchError:
            raise
        except (
            OSError,
            httpx.HTTPError,
            ValueError,
            TypeError,
            AttributeError,
            TimeoutError,
            zlib.error,
        ) as exc:
            raise ResearchError("research_search_failed") from exc
