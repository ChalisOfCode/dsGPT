"""One local owner browser handoff, independent of Work and model context."""

import asyncio
import time
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from .account_browser_bridge import AccountBrowserBridge
from .account_browser_network import AccountBrowserNetwork
from .account_browser_profiles import AccountBrowserProfiles
from .account_browser_read import AccountBrowserReadNetwork
from .account_browser_writes import AccountBrowserWriteError, AccountBrowserWrites
from .storage import uid

HANDOFF_SECONDS = 300
OBSERVATION_SECONDS = 30
REVIEW_SECONDS = 30


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


class BrowserDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    review_id: UUID
    approve: bool = Field(strict=True)


class BrowserVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observation_id: UUID
    action_id: UUID
    applied: bool = Field(strict=True)


@dataclass(repr=False)
class Submission:
    identifier: str
    task: asyncio.Task | None = None
    review_id: str | None = None
    path: str | None = None
    decision: asyncio.Future | None = None
    offered: bool = False
    result: str = "running"


@dataclass(repr=False)
class Handoff:
    owner: str
    session: str
    generation: str
    expires: float
    bridge: AccountBrowserBridge
    writes: AccountBrowserWrites
    timer: asyncio.TimerHandle | None = None
    ready: bool = False
    stopping: bool = False
    operating: bool = False
    observation: str | None = None
    observation_expires: float = 0
    submission: Submission | None = None


class AccountBrowserHandoffs:
    def __init__(self, sessions, builds, bridge_factory=AccountBrowserBridge):
        self.sessions, self.builds, self.bridge_factory = sessions, builds, bridge_factory
        self.active = None
        self.expiration = None
        self.delegated = None

    def _owner(self, owner):
        if not self.sessions.store.one(
            "SELECT id FROM devices WHERE id=? AND role='owner' AND revoked=0", (owner,)
        ):
            raise HTTPException(403, "Account browser requires the active owner")

    async def start(self, owner, session):
        self._owner(owner)
        self.sessions._available()
        row = self.sessions._session(owner, session)
        if self.active or self.delegated:
            raise HTTPException(409, "An account browser is already in use")
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
        writes = AccountBrowserWrites(self.sessions.store, session, owner)
        network = AccountBrowserNetwork(origin, authorize=authorize, writes=writes)
        bridge = self.bridge_factory(sandbox, vault, network, authorize)
        handoff = self.active = Handoff(owner, session, uid(), expires, bridge, writes)
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

    async def read_grant(self, authorize):
        row = authorize()
        session, owner = row["id"], row["owner"]
        revision = row["profile_revision"]
        if type(revision) is not int or revision < 1:
            raise HTTPException(403, "Account grant is not bound to a saved profile")
        if self.active or self.delegated:
            raise HTTPException(409, "An account browser is already in use")
        sandbox = self.builds.sandbox
        if sandbox is None or not self.builds.ready:
            raise HTTPException(503, "Set up the isolated browser tools first")

        def live():
            current = authorize()
            if (current["id"], current["owner"], current["profile_revision"]) != (
                session, owner, revision,
            ):
                raise HTTPException(403, "Account grant is no longer current")

        vault = AccountBrowserProfiles(
            self.sessions.store, session, owner, self.sessions.protection,
        )
        network = AccountBrowserReadNetwork(
            row["origin"], row["read_path"], authorize=live,
            transport_factory=self.sessions.transport_factory,
        )
        bridge = self.bridge_factory(sandbox, vault, network, live)

        async def capture():
            try:
                await bridge.start()
                if bridge.revision != revision:
                    raise HTTPException(403, "Account grant is no longer current")
                await bridge.navigate(network.target)
            finally:
                # A delegated read never saves browser state.
                await bridge.abort()

        self.delegated = asyncio.current_task()
        operation = asyncio.create_task(capture())
        try:
            async with asyncio.timeout(45):
                while not operation.done():
                    await asyncio.wait({operation}, timeout=0.2)
                    live()
                await operation
            live()
            if network.result is None:
                raise HTTPException(409, "Sign in and check the approved plain-text page")
            return {"session_id": session, **network.result}
        except HTTPException:
            raise
        except Exception:
            live()
            raise HTTPException(502, "Approved account page could not be read") from None
        finally:
            if not operation.done():
                operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)
            self.delegated = None

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

    def _live(self, owner, session, generation):
        handoff = self._find(owner, session, generation)
        if not handoff.ready or handoff.stopping or time.monotonic() >= handoff.expires:
            raise HTTPException(409, "Account browser handoff is unavailable")
        self.sessions._session(owner, session)
        return handoff

    @staticmethod
    def _idle(handoff):
        if handoff.operating or (handoff.submission and not handoff.submission.task.done()):
            raise HTTPException(409, "Account browser operation in progress")

    @staticmethod
    def _consume(handoff, observation):
        if handoff.observation != observation or time.monotonic() >= handoff.observation_expires:
            raise HTTPException(409, "Refresh the private page before continuing")
        handoff.observation = None

    async def operate(self, owner, session, generation, operation, body=None):
        handoff = self._live(owner, session, generation)
        self._idle(handoff)
        handoff.observation = None
        handoff.operating = True
        bridge = handoff.bridge
        try:
            if operation == "frame":
                png = await bridge.frame()
                self._live(owner, session, generation)
                handoff.observation = uid()
                handoff.observation_expires = time.monotonic() + OBSERVATION_SECONDS
                return png, handoff.observation
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
        finally:
            handoff.operating = False

    def submit(self, owner, session, generation, observation, body):
        handoff = self._live(owner, session, generation)
        self._idle(handoff)
        if not isinstance(body, BrowserClick) and not (
            isinstance(body, BrowserKey) and body.key == "Enter"
        ):
            raise HTTPException(422, "Use a page click or Enter for form review")
        if handoff.writes.pending():
            raise HTTPException(409, "Inspect and verify the previous form outcome first")
        self._consume(handoff, observation)
        submission = handoff.submission = Submission(uid())
        submission.task = asyncio.create_task(self._submit(handoff, submission, body))
        return {"submission_id": submission.identifier}

    async def _submit(self, handoff, submission, body):
        def live():
            self._live(handoff.owner, handoff.session, handoff.generation)

        async def review(path):
            live()
            if submission.offered:
                return None
            submission.offered = True
            submission.review_id, submission.path = uid(), path
            submission.decision = asyncio.get_running_loop().create_future()
            try:
                async with asyncio.timeout(REVIEW_SECONDS):
                    approved = await submission.decision
                live()
                return submission.review_id if approved else None
            except TimeoutError:
                return None
            finally:
                submission.decision = None
                submission.review_id = submission.path = None

        try:
            await handoff.bridge.submit(body.model_dump(), review)
            submission.result = "finished"
        except asyncio.CancelledError:
            raise
        except Exception:
            submission.result = "interrupted"

    def submission_status(self, owner, session, generation):
        handoff = self._live(owner, session, generation)
        submission = handoff.submission
        review = None
        if submission and submission.decision and not submission.decision.done():
            review = {"review_id": submission.review_id, "path": submission.path}
        return {
            "submission_id": submission.identifier if submission else None,
            "state": submission.result if submission else "idle",
            "review": review,
            "unverified": handoff.writes.pending(),
        }

    def decide(self, owner, session, generation, submission_id, body):
        handoff = self._live(owner, session, generation)
        submission = handoff.submission
        if (
            not submission or submission.identifier != submission_id
            or submission.review_id != str(body.review_id)
            or not submission.decision or submission.decision.done()
        ):
            raise HTTPException(409, "Form review is no longer available")
        submission.decision.set_result(body.approve)

    def verify(self, owner, session, generation, body):
        handoff = self._live(owner, session, generation)
        self._idle(handoff)
        self._consume(handoff, str(body.observation_id))
        try:
            handoff.writes.verify(str(body.action_id), applied=body.applied)
        except AccountBrowserWriteError:
            raise HTTPException(409, "Form outcome is no longer awaiting verification") from None

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
            task = handoff.submission.task if handoff.submission else None
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
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
        if self.delegated:
            self.delegated.cancel()
            await asyncio.gather(self.delegated, return_exceptions=True)
        if self.expiration:
            await self.expiration
        if self.active:
            await self._discard(self.active)
