"""Private submission receipts; no request, response, credential or page data.

Only a trusted owner controller may resolve a receipt after checking remote state.
An HTTP response is not proof that the intended external change happened. Neither
restart nor verification permits replay of an action ID. This internal component
has no API/model endpoint; browser handoff integration is still required.
"""

from uuid import UUID

from .storage import utcnow


class AccountBrowserWriteError(Exception):
    """Fixed codes only, safe even when storage or authorization fails."""


class AccountBrowserWrites:
    def __init__(self, store, session_id, owner_id):
        self.store = store
        self.session_id = str(UUID(session_id))
        self.owner_id = str(UUID(owner_id))

    def _authorize(self, db):
        row = db.execute(
            "SELECT s.origin FROM account_sessions s JOIN devices d ON d.id=s.owner "
            "WHERE s.id=? AND s.owner=? AND d.role='owner' AND d.revoked=0",
            (self.session_id, self.owner_id),
        ).fetchone()
        if not row:
            raise AccountBrowserWriteError("account_browser_write_scope_denied")
        return row[0]

    def begin(self, action_id, *, origin):
        """Commit uncertainty BEFORE dispatch. A crash at any later point blocks retry."""
        action_id = str(UUID(action_id))
        with self.store.transaction() as db:
            if self._authorize(db) != origin:
                raise AccountBrowserWriteError("account_browser_write_scope_denied")
            if db.execute(
                "SELECT 1 FROM account_browser_writes WHERE id=?", (action_id,)
            ).fetchone():
                raise AccountBrowserWriteError("account_browser_write_already_used")
            if db.execute(
                "SELECT 1 FROM account_browser_writes WHERE session_id=? "
                "AND status IN ('uncertain','response_received')",
                (self.session_id,),
            ).fetchone():
                raise AccountBrowserWriteError("account_browser_write_needs_verification")
            if (
                db.execute(
                    "SELECT COUNT(*) FROM account_browser_writes WHERE session_id=?",
                    (self.session_id,),
                ).fetchone()[0]
                >= 128
            ):
                raise AccountBrowserWriteError("account_browser_write_limit")
            now = utcnow()
            db.execute(
                "INSERT INTO account_browser_writes VALUES(?,?,?,?,?)",
                (action_id, self.session_id, "uncertain", now, now),
            )

    def response_received(self, action_id):
        self._transition(action_id, ("uncertain",), "response_received")

    def verify(self, action_id, *, applied):
        """Owner-confirmed remote inspection, never inferred from a status code.

        A new operation still needs a fresh page observation and owner approval.
        This method cannot make an old operation dispatchable again.
        """
        if type(applied) is not bool:
            raise AccountBrowserWriteError("account_browser_write_verification_invalid")
        self._transition(
            action_id,
            ("uncertain", "response_received"),
            "verified_applied" if applied else "verified_not_applied",
        )

    def _transition(self, action_id, expected, status):
        action_id = str(UUID(action_id))
        with self.store.transaction() as db:
            self._authorize(db)
            row = db.execute(
                "SELECT status FROM account_browser_writes WHERE id=? AND session_id=?",
                (action_id, self.session_id),
            ).fetchone()
            if not row or row[0] not in expected:
                raise AccountBrowserWriteError("account_browser_write_state_conflict")
            db.execute(
                "UPDATE account_browser_writes SET status=?,updated_at=? WHERE id=?",
                (status, utcnow(), action_id),
            )

    def pending(self):
        with self.store.connect() as db:
            self._authorize(db)
            return [
                dict(row)
                for row in db.execute(
                    "SELECT id,status,created_at,updated_at FROM account_browser_writes "
                    "WHERE session_id=? AND status IN ('uncertain','response_received')",
                    (self.session_id,),
                )
            ]
