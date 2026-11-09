"""One local owner browser handoff, independent of Work and model context."""

import asyncio
import time
from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from .account_browser_bridge import AccountBrowserBridge
from .account_browser_network import AccountBrowserNetwork
from .account_browser_profiles import AccountBrowserProfiles
from .storage import uid

HANDOFF_SECONDS = 300


class BrowserClick(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["click"]
    x: int = Field(strict=True, ge=0, lt=1024)
    y: int = Field(strict=True, ge=0, lt=768)


class BrowserText(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["text"]
    text: SecretStr = Field(min_length=1, max_length=2048)


class BrowserKey(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["key"]
    key: Literal["Tab", "Enter", "Backspace", "Escape", "ArrowUp", "ArrowDown"]


@dataclass(repr=False)
class Handoff:
    owner: str
    session: str
    generation: str
    expires: float
    bridge: AccountBrowserBridge
    timer: asyncio.TimerHandle | None = None
    ready: bool = False
    stopping: bool = False


class AccountBrowserHandoffs:
    def __init__(self, sessions, builds, bridge_factory=AccountBrowserBridge):
        self.sessions, self.builds, self.bridge_factory = sessions, builds, bridge_factory
        self.active = None
        self.expiration = None

    def _owner(self, owner):
        if not self.sessions.store.one(
            "SELECT id FROM devices WHERE id=? AND role='owner' AND revoked=0", (owner,)
        ):
            raise HTTPException(403, "Account browser requires the active owner")

    async def start(self, owner, session):
        self._owner(owner)
        self.sessions._available()
        row = self.sessions._session(owner, session)
        if self.active:
            raise HTTPException(409, "Close or discard the existing account browser first")
        sandbox = self.builds.sandbox
        if sandbox is None or not self.builds.ready:
            raise HTTPException(503, "Set up the isolated browser tools first")
        origin = row["origin"]
        del row  # The legacy cookie envelope never enters the browser broker.
        expires = time.monotonic() + HANDOFF_SECONDS

        def authorize():
            if (
                self.active is not handoff or handoff.stopping or time.monotonic() >= expires
            ):
                raise HTTPException(409, "Account browser handoff has ended")
            self._owner(owner)
            self.sessions._session(owner, session)

        vault = AccountBrowserProfiles(
            self.sessions.store, session, owner, self.sessions.protection
        )
        bridge = self.bridge_factory(
            sandbox, vault, AccountBrowserNetwork(origin, authorize=authorize), authorize
        )
        handoff = self.active = Handoff(owner, session, uid(), expires, bridge)
        handoff.timer = asyncio.get_running_loop().call_later(
            HANDOFF_SECONDS, self._schedule_expiration, handoff
        )
        try:
            await bridge.start()
            # Navigate only to the stored origin and literal owner-selected path.
            await bridge.navigate(origin + self.sessions._session(owner, session)["read_path"])
            authorize()
            handoff.ready = True
            return {"handoff_id": handoff.generation, "lifetime_seconds": HANDOFF_SECONDS}
        except asyncio.CancelledError:
            if not handoff.stopping:
                await self._discard(handoff)
            raise
        except Exception:
            if not handoff.stopping:
                await self._discard(handoff)
            raise HTTPException(409, "Account browser could not start") from None

    def _schedule_expiration(self, handoff):
        self.expiration = asyncio.create_task(self._expire(handoff))

    async def _expire(self, handoff):
        try:
            await self._discard(handoff)
        except HTTPException:
            # Keep the handle reserved so explicit discard can retry cleanup.
            pass

    def _find(self, owner, session, generation):
        self._owner(owner)
        handoff = self.active
        if (
            not handoff or handoff.owner != owner or handoff.session != session
            or handoff.generation != generation
        ):
            raise HTTPException(404, "Account browser handoff not found")
        return handoff

    async def operate(self, owner, session, generation, operation, body=None):
        handoff = self._find(owner, session, generation)
        if not handoff.ready or handoff.stopping or time.monotonic() >= handoff.expires:
            raise HTTPException(409, "Account browser handoff is unavailable")
        self.sessions._session(owner, session)
        bridge = handoff.bridge
        try:
            if operation == "frame":
                return await bridge.frame()
            if operation == "save":
                await bridge.close()
                self._clear(handoff)
            elif isinstance(body, BrowserClick):
                await bridge.click(body.x, body.y)
            elif isinstance(body, BrowserText):
                await bridge.type_text(body.text.get_secret_value())
            elif isinstance(body, BrowserKey):
                await bridge.key(body.key)
            else:
                raise ValueError
        except Exception:
            raise HTTPException(409, "Account browser operation unavailable") from None

    def _clear(self, handoff):
        if handoff.timer:
            handoff.timer.cancel()
        if self.active is handoff:
            self.active = None

    async def _discard(self, handoff):
        if self.active is not handoff:
            return
        if handoff.stopping:
            raise HTTPException(409, "Account browser cleanup is in progress")
        handoff.stopping, handoff.ready = True, False
        try:
            await handoff.bridge.abort()
        except Exception:
            raise HTTPException(503, "Account browser cleanup needs retry") from None
        else:
            self._clear(handoff)
        finally:
            handoff.stopping = False

    async def discard(self, owner, session, generation):
        try:
            handoff = self._find(owner, session, generation)
        except HTTPException as exc:
            # A lost discard/save response or timer expiry must not trap the
            # owner in a stale view. Never touch a newer handoff generation.
            if exc.status_code == 404:
                return
            raise
        await self._discard(handoff)

    async def revoke(self, owner, session):
        handoff = self.active
        if handoff and (handoff.owner, handoff.session) == (owner, session):
            await self._discard(handoff)

    async def stop(self):
        if self.expiration:
            await self.expiration
        if self.active:
            await self._discard(self.active)
