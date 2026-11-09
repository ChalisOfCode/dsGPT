"""Owner-only signed-in reads. Never use this broker for model or public browsing."""

import asyncio
import ctypes
import hashlib
import os
import re
from ctypes import wintypes

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from .downloads import DownloadError, PublicHTTPS
from .storage import uid, utcnow
from .web_retrieval import PageText, ResearchError, limited_body, public_url

COOKIE = re.compile(
    r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,80}=[\x21\x23-\x2B\x2D-\x3A\x3C-\x5B\x5D-\x7E]{1,1536}"
)
PATH = re.compile(r"/[A-Za-z0-9_./~-]{0,1000}")


class AccountSessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1, max_length=80)
    origin: str = Field(max_length=512)
    read_path: str = Field(max_length=1001)
    session_cookie: SecretStr = Field(min_length=3, max_length=1617)


class WindowsSessionProtection:
    """DPAPI current-user encryption; no plaintext or machine-wide fallback."""

    @property
    def available(self):
        return os.name == "nt"

    def seal(self, data, binding):
        return self._transform(data, binding, True)

    def open(self, data, binding):
        return self._transform(data, binding, False)

    def _transform(self, data, binding, protect):
        if not self.available:
            raise OSError("Session protection unavailable")

        class Blob(ctypes.Structure):
            _fields_ = [("size", wintypes.DWORD), ("data", ctypes.c_void_p)]

        source = ctypes.create_string_buffer(data)
        entropy = ctypes.create_string_buffer(binding)
        out = Blob()
        crypto = ctypes.WinDLL("Crypt32.dll", use_last_error=True)
        kernel = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        transform = crypto.CryptProtectData if protect else crypto.CryptUnprotectData
        transform.argtypes = [
            ctypes.POINTER(Blob),
            ctypes.c_void_p,
            ctypes.POINTER(Blob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(Blob),
        ]
        transform.restype = wintypes.BOOL
        try:
            if not transform(
                ctypes.byref(Blob(len(data), ctypes.addressof(source))),
                None,
                ctypes.byref(Blob(len(binding), ctypes.addressof(entropy))),
                None,
                None,
                1,
                ctypes.byref(out),  # CRYPTPROTECT_UI_FORBIDDEN
            ):
                raise OSError("Session protection failed")
            return ctypes.string_at(out.data, out.size)
        finally:
            ctypes.memset(source, 0, len(data))
            if out.data:
                ctypes.memset(out.data, 0, out.size)
                kernel.LocalFree(out.data)


def session_origin(raw):
    try:
        normalized = httpx.URL(public_url(raw))
    except ResearchError:
        raise HTTPException(422, "Use an exact public HTTPS origin") from None
    if normalized.path != "/" or normalized.query or "?" in raw or "#" in raw:
        raise HTTPException(422, "Use an exact public HTTPS origin")
    return str(normalized).removesuffix("/")


def session_path(raw):
    if (
        not PATH.fullmatch(raw)
        or "//" in raw
        or any(segment in {".", ".."} for segment in raw.split("/"))
    ):
        raise HTTPException(422, "Use a literal page path without a query or fragment")
    return raw


def binding(row):
    return hashlib.sha256(
        (
            "dsGPT account session v1\0"
            + "\0".join(row[k] for k in ("id", "owner", "origin", "read_path"))
        ).encode()
    ).digest()


class AccountSessions:
    def __init__(self, store, protection=None, transport_factory=None):
        self.store = store
        self.protection = protection if protection is not None else WindowsSessionProtection()
        self.transport_factory = transport_factory or PublicHTTPS
        self.lock = asyncio.Lock()

    def _available(self):
        if not self.protection.available:
            raise HTTPException(503, "Protected account storage is unavailable on this host")

    def list(self, owner):
        return {
            "available": self.protection.available,
            "sessions": self.store.all(
                "SELECT id,label,origin,read_path,created_at FROM account_sessions "
                "WHERE owner=? ORDER BY created_at,id",
                (owner,),
            ),
        }

    async def create(self, owner, body):
        self._available()
        origin, path = session_origin(body.origin), session_path(body.read_path)
        label, cookie = body.label.strip(), body.session_cookie.get_secret_value()
        if not label or any(ord(c) < 32 for c in label) or not COOKIE.fullmatch(cookie):
            raise HTTPException(422, "Invalid session label or session cookie")
        row = {
            "id": uid(),
            "owner": owner,
            "label": label,
            "origin": origin,
            "read_path": path,
            "created_at": utcnow(),
        }
        async with self.lock:
            with self.store.transaction() as db:
                if (
                    db.execute(
                        "SELECT count(*) FROM account_sessions WHERE owner=?",
                        (owner,),
                    ).fetchone()[0]
                    >= 16
                ):
                    raise HTTPException(409, "Revoke an existing account session first")
                try:
                    sealed = self.protection.seal(cookie.encode("ascii"), binding(row))
                except OSError:
                    raise HTTPException(503, "Could not protect the account session") from None
                db.execute(
                    "INSERT INTO account_sessions(id,owner,label,origin,read_path,created_at,"
                    "sealed_cookie) VALUES(?,?,?,?,?,?,?)",
                    (*row.values(), sealed),
                )
        return {k: v for k, v in row.items() if k != "owner"}

    async def revoke(self, owner, identifier):
        async with self.lock:
            with self.store.transaction() as db:
                count = db.execute(
                    "DELETE FROM account_sessions WHERE id=? AND owner=?", (identifier, owner)
                ).rowcount
        if not count:
            raise HTTPException(404, "Account session not found")

    async def read(self, owner, identifier):
        self._available()
        async with self.lock:
            row = self.store.one(
                "SELECT * FROM account_sessions WHERE id=? AND owner=?", (identifier, owner)
            )
            if not row:
                raise HTTPException(404, "Account session not found")
            url = session_origin(row["origin"]) + session_path(row["read_path"])
            try:
                cookie = self.protection.open(row["sealed_cookie"], binding(row)).decode("ascii")
                if not COOKIE.fullmatch(cookie):
                    raise ValueError("Invalid protected cookie")
            except (OSError, ValueError):
                raise HTTPException(409, "Reconnect the protected account session") from None

            def validate(target):
                if str(target) != url:
                    raise DownloadError("account_destination_mismatch")
                public_url(str(target))

            try:
                async with (
                    asyncio.timeout(12),
                    httpx.AsyncClient(
                        transport=self.transport_factory(validator=validate),
                        follow_redirects=False,
                        trust_env=False,
                        timeout=8,
                    ) as client,
                ):
                    async with client.stream(
                        "GET",
                        url,
                        headers={
                            "Cookie": cookie,
                            "Accept-Encoding": "identity",
                            "Accept": "text/plain, text/html",
                        },
                    ) as response:
                        if response.status_code in {301, 302, 303, 307, 308, 401, 403}:
                            raise HTTPException(
                                409, "Account access blocked; check sign-in or scope"
                            )
                        if response.status_code != 200:
                            raise HTTPException(502, "Approved account page was unavailable")
                        content_type = response.headers.get("content-type", "").split(";")[0]
                        if content_type not in {"text/html", "text/plain"}:
                            raise HTTPException(502, "Account page is not readable text")
                        raw = (await limited_body(response, 256 * 1024)).decode("utf-8", "replace")
                        if content_type == "text/html":
                            page = PageText(url)
                            page.feed(raw)
                            page.close()
                            raw = " ".join(page.parts)
            except (httpx.HTTPError, DownloadError, ResearchError, TimeoutError, OSError):
                raise HTTPException(502, "Approved account page could not be read") from None
            # Only the authenticated owner sees the returned text. No Work/model,
            # diagnostic or disk persistence of the page or its headers.
            raw = raw.replace(cookie, "[redacted]").replace(cookie.split("=", 1)[1], "[redacted]")
            return {"session_id": identifier, "text": raw[:12000], "truncated": len(raw) > 12000}
