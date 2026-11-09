"""Private transport for a future isolated, owner-controlled account browser.

The internal private browser bridge uses this; no API route or model tool does.
The caller must check the live owner handoff before issuing one-time form approval.
Bodies, cookies and response headers are private bridge data, never receipts.
"""

import asyncio
import hashlib
import time
from contextlib import aclosing
from dataclasses import dataclass
from urllib.parse import urljoin
from uuid import UUID

import httpx

from .account_browser_writes import AccountBrowserWriteError
from .account_sessions import session_origin
from .downloads import DownloadError, PublicHTTPS
from .web_retrieval import ResearchError, limited_body, public_url

MAX_BODY = 64 * 1024
MAX_RESOURCE = 2 * 1024**2
MAX_TOTAL = 8 * 1024**2
MAX_REQUESTS = 64
MAX_HEADERS = 32 * 1024
REDIRECTS = {301, 302, 303, 307, 308}
REQUEST_HEADERS = {
    "accept",
    "accept-language",
    "content-type",
    "cookie",
    "origin",
    "referer",
    "sec-fetch-dest",
    "sec-fetch-mode",
    "sec-fetch-site",
    "sec-fetch-user",
    "user-agent",
}
# Keep security policy and duplicate Set-Cookie fields. Hop-by-hop metadata,
# compression, Alt-Svc and redirect targets are handled independently.
RESPONSE_HEADERS = {
    "cache-control",
    "content-disposition",
    "content-language",
    "content-security-policy",
    "content-security-policy-report-only",
    "content-type",
    "cross-origin-embedder-policy",
    "cross-origin-opener-policy",
    "cross-origin-resource-policy",
    "expires",
    "permissions-policy",
    "referrer-policy",
    "set-cookie",
    "vary",
    "x-content-type-options",
    "x-frame-options",
}


class AccountBrowserNetworkError(Exception):
    """Fixed error codes only; no sensitive URL, headers or response in errors."""


@dataclass(frozen=True, repr=False)
class BrowserResponse:
    status: int
    headers: tuple[tuple[str, str], ...]
    body: bytes


class AccountBrowserNetwork:
    def __init__(
        self,
        origin,
        *,
        authorize,
        writes=None,
        transport_factory=PublicHTTPS,
        clock=time.monotonic,
    ):
        self.origin = session_origin(origin)
        self._authorize = authorize
        self._transport = transport_factory
        self._clock = clock
        self._writes = writes
        self._requests = self._total = 0
        self._approval = None
        self._lock = asyncio.Lock()

    def _url(self, raw):
        try:
            url = httpx.URL(public_url(raw))
            if str(url.copy_with(path="/", query=None)).removesuffix("/") != self.origin:
                raise ValueError
            return str(url)
        except (ValueError, ResearchError):
            raise AccountBrowserNetworkError("account_browser_origin_denied") from None

    def approve_form(self, raw, body, *, action_id):
        """Called only by the trusted owner controller, for one paused request."""
        self._approval = None
        self._authorize()
        if self._writes is None:
            raise AccountBrowserNetworkError("account_browser_write_tracking_required")
        if type(body) is not bytes or not 0 < len(body) <= MAX_BODY:
            raise AccountBrowserNetworkError("account_browser_body_denied")
        try:
            action_id = str(UUID(action_id))
        except (ValueError, TypeError, AttributeError):
            raise AccountBrowserNetworkError("account_browser_action_invalid") from None
        self._approval = (
            self._url(raw),
            hashlib.sha256(body).digest(),
            self._clock() + 30,
            action_id,
        )

    async def fetch(self, raw, method, headers, body=b""):
        if self._lock.locked():
            raise AccountBrowserNetworkError("account_browser_busy")
        async with self._lock:
            self._authorize()
            url = self._url(raw)
            if self._requests >= MAX_REQUESTS or self._total >= MAX_TOTAL:
                raise AccountBrowserNetworkError("account_browser_budget_exhausted")
            if type(body) is not bytes or len(body) > MAX_BODY:
                raise AccountBrowserNetworkError("account_browser_body_denied")
            if method not in {"GET", "HEAD", "POST"} or (method != "POST" and body):
                raise AccountBrowserNetworkError("account_browser_method_denied")
            if not isinstance(headers, dict) or len(headers) > 64:
                raise AccountBrowserNetworkError("account_browser_headers_denied")
            forwarded = {"accept-encoding": "identity"}
            for key, value in headers.items():
                if not isinstance(key, str) or not isinstance(value, str):
                    raise AccountBrowserNetworkError("account_browser_headers_denied")
                name = key.lower()
                if name not in REQUEST_HEADERS:
                    continue
                if name in forwarded or any(not 32 <= ord(c) < 127 for c in value):
                    raise AccountBrowserNetworkError("account_browser_headers_denied")
                if name == "origin" and value != self.origin:
                    raise AccountBrowserNetworkError("account_browser_origin_denied")
                if name == "referer":
                    self._url(value)
                forwarded[name] = value
            if sum(len(k) + len(v) for k, v in forwarded.items()) > MAX_HEADERS:
                raise AccountBrowserNetworkError("account_browser_headers_denied")
            if method == "POST":
                approval, self._approval = self._approval, None
                if (
                    not approval
                    or approval[:2] != (url, hashlib.sha256(body).digest())
                    or approval[2] <= self._clock()
                    or forwarded.get("content-type", "").lower()
                    != "application/x-www-form-urlencoded"
                    or forwarded.get("origin") != self.origin
                ):
                    raise AccountBrowserNetworkError("account_browser_form_not_approved")
                try:
                    self._writes.begin(approval[3], origin=self.origin)
                except AccountBrowserWriteError:
                    raise AccountBrowserNetworkError(
                        "account_browser_write_review_required"
                    ) from None
                except Exception:
                    raise AccountBrowserNetworkError(
                        "account_browser_write_tracking_failed"
                    ) from None
            self._requests += 1

            def validate(target):
                self._authorize()
                if method == "POST" and approval[2] <= self._clock():
                    raise AccountBrowserNetworkError("account_browser_form_not_approved")
                if self._url(str(target)) != url:
                    raise AccountBrowserNetworkError("account_browser_origin_denied")

            try:
                # A single direct transport request avoids AsyncClient's URL
                # access logging, cookie jar and redirect handling.
                request = httpx.Request(method, url, headers=forwarded, content=body)
                async with asyncio.timeout(12), self._transport(validator=validate) as transport:
                    async with aclosing(await transport.handle_async_request(request)) as response:
                        result = await self._response(url, method, response)
            except (httpx.HTTPError, DownloadError, ResearchError, TimeoutError, OSError):
                raise AccountBrowserNetworkError("account_browser_request_failed") from None
            self._authorize()
            if method == "POST":
                try:
                    self._writes.response_received(approval[3])
                except Exception:
                    raise AccountBrowserNetworkError(
                        "account_browser_write_tracking_failed"
                    ) from None
            return result

    async def _response(self, url, method, response):
        status = response.status_code
        if not 200 <= status < 600 or (300 <= status < 400 and status not in REDIRECTS | {304}):
            raise AccountBrowserNetworkError("account_browser_response_denied")
        headers = tuple((k, v) for k, v in response.headers.multi_items() if k in RESPONSE_HEADERS)
        if status in REDIRECTS:
            locations = response.headers.get_list("location")
            if (
                len(locations) != 1
                or not locations[0]
                or (method == "POST" and status in {307, 308})
            ):
                raise AccountBrowserNetworkError("account_browser_redirect_denied")
            target = self._url(urljoin(url, locations[0]))
            headers += (("location", target),)
        if len(headers) > 96 or sum(len(k) + len(v) for k, v in headers) > MAX_HEADERS:
            raise AccountBrowserNetworkError("account_browser_headers_denied")
        if any(any(ord(c) < 32 and c != "\t" or ord(c) == 127 for c in v) for _, v in headers):
            raise AccountBrowserNetworkError("account_browser_headers_denied")
        if method == "HEAD" or status in REDIRECTS or status in {204, 205, 304}:
            body = b""
        else:
            body = await limited_body(response, min(MAX_RESOURCE, MAX_TOTAL - self._total))
        self._total += len(body)
        return BrowserResponse(status, headers, body)
