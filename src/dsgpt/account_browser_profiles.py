"""Internal protected profile vault; never a model tool or diagnostic export.

The trusted browser controller must supply only regular files from its dedicated
profile AFTER Chromium has stopped cleanly. This module never imports an everyday
profile or writes decrypted files on the host. Worker integration remains required.
"""

import base64
import hashlib
import json
from pathlib import PurePosixPath
from uuid import UUID

from .account_sessions import WindowsSessionProtection

MAX_BYTES = 8 * 1024**2
MAX_ENVELOPE = 12 * 1024**2
MAX_FILES = 512


class AccountProfileError(Exception):
    pass


def validate(files):
    if type(files) is not dict or not 1 <= len(files) <= MAX_FILES:
        raise AccountProfileError("account_profile_invalid")
    total = 0
    for name, data in files.items():
        if (
            type(name) is not str
            or not 1 <= len(name) <= 240
            or any(ord(c) < 32 or ord(c) > 126 for c in name)
            or "\\" in name
            or ":" in name
            or name.startswith("/")
            or str(PurePosixPath(name)) != name
            or any(p in {".", ".."} for p in name.split("/"))
            or name.split("/")[0].startswith("Singleton")
            or type(data) is not bytes
        ):
            raise AccountProfileError("account_profile_invalid")
        total += len(data)
        if total > MAX_BYTES:
            raise AccountProfileError("account_profile_too_large")
    # Reject a file that is also another file's parent.
    if any(str(p) in files for name in files for p in PurePosixPath(name).parents):
        raise AccountProfileError("account_profile_invalid")


class AccountBrowserProfiles:
    def __init__(self, store, session_id, owner_id, protection=None):
        self.store = store
        self.session_id, self.owner_id = str(UUID(session_id)), str(UUID(owner_id))
        self.protection = protection if protection is not None else WindowsSessionProtection()

    def _binding(self, db, revision):
        row = db.execute(
            "SELECT s.origin FROM account_sessions s JOIN devices d ON s.owner=d.id "
            "WHERE s.id=? AND s.owner=? AND d.role='owner' AND d.revoked=0",
            (self.session_id, self.owner_id),
        ).fetchone()
        if not row:
            raise AccountProfileError("account_profile_scope_denied")
        return hashlib.sha256(
            json.dumps(
                [
                    "dsGPT private browser profile v1",
                    self.session_id,
                    self.owner_id,
                    row[0],
                    revision,
                ]
            ).encode()
        ).digest()

    def save(self, files, *, expected_revision):
        validate(files)
        if type(expected_revision) is not int or expected_revision < 0:
            raise AccountProfileError("account_profile_revision_invalid")
        payload = json.dumps(
            [
                [name, base64.b64encode(data).decode("ascii")]
                for name, data in sorted(files.items())
            ],
            separators=(",", ":"),
        ).encode()
        if len(payload) > MAX_ENVELOPE:
            raise AccountProfileError("account_profile_too_large")
        with self.store.transaction() as db:
            revision = expected_revision + 1
            binding = self._binding(db, revision)
            row = db.execute(
                "SELECT revision FROM account_browser_profiles WHERE session_id=?",
                (self.session_id,),
            ).fetchone()
            if (row[0] if row else 0) != expected_revision:
                raise AccountProfileError("account_profile_revision_conflict")
            try:
                sealed = self.protection.seal(payload, binding)
                if type(sealed) is not bytes or not 0 < len(sealed) <= MAX_ENVELOPE + 4096:
                    raise ValueError
            except Exception:
                raise AccountProfileError("account_profile_protection_failed") from None
            db.execute(
                "INSERT INTO account_browser_profiles VALUES(?,?,?) "
                "ON CONFLICT(session_id) DO UPDATE SET revision=excluded.revision, "
                "sealed_profile=excluded.sealed_profile",
                (self.session_id, revision, sealed),
            )
        return revision

    def restore(self):
        with self.store.transaction() as db:
            self._binding(db, 0)
            row = db.execute(
                "SELECT revision,sealed_profile FROM account_browser_profiles WHERE session_id=?",
                (self.session_id,),
            ).fetchone()
            if row is None:
                return 0, None
            binding = self._binding(db, row[0])
            try:
                if len(row[1]) > MAX_ENVELOPE + 4096:
                    raise ValueError
                payload = self.protection.open(row[1], binding)
                if type(payload) is not bytes or len(payload) > MAX_ENVELOPE:
                    raise ValueError
                entries = json.loads(payload)
                if type(entries) is not list or not 1 <= len(entries) <= MAX_FILES:
                    raise ValueError
                files = {}
                for entry in entries:
                    if type(entry) is not list or len(entry) != 2 or entry[0] in files:
                        raise ValueError
                    files[entry[0]] = base64.b64decode(entry[1], validate=True)
                validate(files)
            except Exception:
                raise AccountProfileError("account_profile_restore_failed") from None
            return row[0], files
