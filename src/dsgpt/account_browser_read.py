"""An explicitly delegated text read with no interactive browser authority."""

from urllib.parse import unquote

from .account_browser_network import (
    AccountBrowserNetwork,
    AccountBrowserNetworkError,
    BrowserResponse,
)
from .account_sessions import session_path
from .web_retrieval import limited_body

MAX_READ_BYTES = 256 * 1024
MAX_READ_TEXT = 12000


class AccountBrowserReadNetwork(AccountBrowserNetwork):
    def __init__(self, origin, path, *, authorize, transport_factory):
        super().__init__(origin, authorize=authorize, transport_factory=transport_factory)
        self.target = self.origin + session_path(path)
        self.result = None
        self.attempted = False

    async def fetch(self, raw, method, headers, body=b""):
        self._authorize()
        if (
            self.attempted or method != "GET" or body or raw != self.target
            or self._url(raw) != self.target or type(headers) is not dict
        ):
            raise AccountBrowserNetworkError("account_read_destination_denied")
        self.attempted = True
        cookies = [value for key, value in headers.items() if key.lower() == "cookie"]
        if len(cookies) != 1 or not isinstance(cookies[0], str) or not cookies[0]:
            raise AccountBrowserNetworkError("account_read_needs_signed_in_profile")
        response = await super().fetch(
            raw, method, {"cookie": cookies[0], "accept": "text/plain"},
        )
        text = response.body.decode("utf-8", "replace")
        secrets = {cookies[0]}
        for item in cookies[0].split(";"):
            _, sep, value = item.strip().partition("=")
            if not sep or not value:
                continue
            secrets.update((value, unquote(value)))
        # Never return a known credential reflected in the remote response.
        clean = "".join(c for c in text if c in "\n\t" or c.isprintable())
        if any(secret and (secret in text or secret in clean) for secret in secrets):
            raise AccountBrowserNetworkError("account_read_credential_reflection")
        text = clean
        self.result = {"text": text[:MAX_READ_TEXT], "truncated": len(text) > MAX_READ_TEXT}
        # The guest needs only a successful navigation, not the protected content.
        # No remote header, page markup or scripts are fulfilled in Chromium.
        return BrowserResponse(200, (("content-type", "text/plain"),), b"")

    async def _response(self, url, method, response):
        types = response.headers.get_list("content-type")
        if (
            response.status_code != 200 or len(types) != 1
            or types[0].split(";", 1)[0].strip().lower() != "text/plain"
            or "set-cookie" in response.headers
        ):
            raise AccountBrowserNetworkError("account_read_not_plain_text")
        return BrowserResponse(200, (), await limited_body(response, MAX_READ_BYTES))
