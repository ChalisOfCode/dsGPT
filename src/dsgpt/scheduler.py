"""One inference grant across Chat and Work, with bounded category starvation.

Durable requests remain in runs/work_tasks. Waiting tickets are rebuilt by their workers
after restart. A grant covers one complete model turn; generation is not preempted.
"""

import asyncio
from collections import deque
from contextlib import asynccontextmanager


class InferenceScheduler:
    def __init__(self, store):
        self.store = store
        self.queues = {"chat": deque(), "work": deque()}
        self.condition = asyncio.Condition()
        self.active = None

    def _next(self):
        chat, work = self.queues["chat"], self.queues["work"]
        streak = self.store.one("SELECT chat_streak FROM scheduler_state WHERE id=1")["chat_streak"]
        if work and (not chat or streak >= 2):
            return "work", work[0]
        if chat:
            return "chat", chat[0]
        return None

    @asynccontextmanager
    async def acquire(self, kind, request_id):
        if kind not in self.queues:
            raise ValueError("Unknown inference category")
        ticket = object()
        acquired = False
        try:
            async with self.condition:
                self.queues[kind].append(ticket)
                await self.condition.wait_for(
                    lambda: self.active is None and self._next() == (kind, ticket)
                )
                self.queues[kind].popleft()
                self.active = {"kind": kind, "request_id": request_id}
                acquired = True
                with self.store.transaction() as db:
                    if kind == "chat":
                        db.execute(
                            "UPDATE scheduler_state SET chat_streak=MIN(chat_streak+1,2),"
                            "chat_grants=chat_grants+1 WHERE id=1"
                        )
                    else:
                        db.execute(
                            "UPDATE scheduler_state SET chat_streak=0,"
                            "work_grants=work_grants+1 WHERE id=1"
                        )
            yield
        finally:
            async with self.condition:
                if acquired:
                    self.active = None
                elif ticket in self.queues[kind]:
                    self.queues[kind].remove(ticket)
                self.condition.notify_all()

    def snapshot(self):
        return {
            "policy": "one_turn_at_a_time_chat_burst_2",
            "preemption": False,
            "active": self.active,
            "waiting": {k: len(v) for k, v in self.queues.items()},
            "grants": self.store.one(
                "SELECT chat_grants,work_grants FROM scheduler_state WHERE id=1"
            ),
            "scope": "dsGPT requests only; other local applications are not controlled",
        }
