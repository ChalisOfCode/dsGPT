"""Local owner bootstrap for the managed Windows backend.

No HTTP enrollment route, command-line token or plaintext credential file is used.
The installer/native launcher still needs to wire this into its first-run flow.
"""

import ctypes
import hashlib
import json
import os
import secrets
from uuid import UUID

from .security import CLIENT_SCOPES, digest
from .storage import InstanceLock, Store, canonical, uid, utcnow


def credential_target(directory):
    identity = os.path.normcase(str(directory.resolve())).encode("utf-8")
    return "dsGPT/backend-owner/" + hashlib.sha256(identity).hexdigest()[:32]


class WindowsVault:
    """Current-user Windows generic credential; no portable plaintext fallback."""

    def __init__(self, directory, *, target=None, encoding="utf-8"):
        if os.name != "nt":
            raise RuntimeError("Managed owner bootstrap requires Windows Credential Manager")
        from ctypes import wintypes

        class Credential(ctypes.Structure):
            _fields_ = [
                ("Flags", wintypes.DWORD),
                ("Type", wintypes.DWORD),
                ("TargetName", wintypes.LPWSTR),
                ("Comment", wintypes.LPWSTR),
                ("LastWritten", wintypes.FILETIME),
                ("CredentialBlobSize", wintypes.DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                ("Persist", wintypes.DWORD),
                ("AttributeCount", wintypes.DWORD),
                ("Attributes", ctypes.c_void_p),
                ("TargetAlias", wintypes.LPWSTR),
                ("UserName", wintypes.LPWSTR),
            ]

        self.credential = Credential
        self.target = target or credential_target(directory)
        self.encoding = encoding
        self.api = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        self.api.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(Credential)),
        ]
        self.api.CredReadW.restype = wintypes.BOOL
        self.api.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
        self.api.CredWriteW.restype = wintypes.BOOL
        self.api.CredFree.argtypes = [ctypes.c_void_p]
        self.api.CredFree.restype = None

    def read(self):
        pointer = ctypes.POINTER(self.credential)()
        if not self.api.CredReadW(self.target, 1, 0, ctypes.byref(pointer)):
            if ctypes.get_last_error() == 1168:  # ERROR_NOT_FOUND
                return None
            raise RuntimeError("Windows credential read failed")
        try:
            size = pointer.contents.CredentialBlobSize
            if not 1 <= size <= 2048:
                raise RuntimeError("Invalid managed credential")
            return json.loads(
                ctypes.string_at(pointer.contents.CredentialBlob, size).decode(self.encoding)
            )
        finally:
            self.api.CredFree(pointer)

    def write(self, value):
        encoded = canonical(value).encode(self.encoding)
        if len(encoded) > 2048:
            raise ValueError("Invalid managed credential size")
        buffer = (ctypes.c_ubyte * len(encoded)).from_buffer_copy(encoded)
        credential = self.credential()
        credential.Type, credential.Persist = 1, 2  # GENERIC, LOCAL_MACHINE (current user)
        credential.TargetName, credential.UserName = self.target, "dsGPT desktop owner"
        credential.CredentialBlobSize, credential.CredentialBlob = len(encoded), buffer
        try:
            if not self.api.CredWriteW(ctypes.byref(credential), 0):
                raise RuntimeError("Windows credential save failed")
        finally:
            ctypes.memset(buffer, 0, len(encoded))


def ensure_owner(store, vault):
    """Vault first, DB second: a crash can leave a recoverable staged credential.

    Existing owners must match the vault. Never rotate or replace an existing owner
    merely because credentials are absent or belong to another database.
    """
    lock = InstanceLock(store.directory, "owner-bootstrap.lock")
    lock.acquire()
    try:
        saved = vault.read()
        if saved is not None:
            try:
                if (
                    set(saved) != {"device_id", "token"}
                    or str(UUID(saved["device_id"])) != saved["device_id"]
                    or not isinstance(saved["token"], str)
                    or not 32 <= len(saved["token"]) <= 200
                ):
                    raise ValueError("Invalid credential")
            except (TypeError, ValueError, KeyError, AttributeError) as exc:
                raise ValueError("Invalid managed credential; manual recovery required") from exc
        with store.transaction() as db:
            owner = db.execute("SELECT * FROM devices WHERE role='owner'").fetchone()
            if owner:
                if (
                    not saved
                    or owner["revoked"]
                    or owner["id"] != saved["device_id"]
                    or not secrets.compare_digest(owner["token_hash"], digest(saved["token"]))
                ):
                    raise ValueError(
                        "Existing owner preserved; reconnect with the original credential"
                    )
                return {"device_id": owner["id"], "created": False}
            if saved is None:
                saved = {"device_id": uid(), "token": secrets.token_urlsafe(32)}
                vault.write(saved)
                if vault.read() != saved:
                    raise RuntimeError("Credential verification failed; owner was not created")
            db.execute(
                "INSERT INTO devices(id,name,role,token_hash,scopes,created_at) "
                "VALUES(?,?,?,?,?,?)",
                (
                    saved["device_id"],
                    "Desktop owner",
                    "owner",
                    digest(saved["token"]),
                    canonical(sorted(CLIENT_SCOPES | {"admin"})),
                    utcnow(),
                ),
            )
        return {"device_id": saved["device_id"], "created": True}
    finally:
        lock.release()


def recover_owner(directory, vault, *, confirm_revoke_devices=False):
    """Explicit, offline, current-OS-user recovery; never exposed over HTTP.

    Save and verify the replacement in the OS vault before changing the database.
    If the final DB commit fails, the old database credential remains unchanged;
    rerun this explicit recovery while offline to reconcile the vault. Startup
    never guesses that a mismatched credential authorizes rotation.
    """
    if not confirm_revoke_devices:
        raise ValueError("Recovery requires explicit confirmation to revoke all paired devices")
    if not (directory / "dsgpt.db").is_file():
        raise ValueError("Recovery requires an existing dsGPT database")
    locks = []
    try:
        for name in (
            "managed-supervisor.lock",
            "managed-service.lock",
            "backend.lock",
            "owner-bootstrap.lock",
        ):
            lock = InstanceLock(directory, name)
            lock.acquire()
            locks.append(lock)
        store = Store(directory)
        with store.transaction() as db:
            owners = db.execute("SELECT * FROM devices WHERE role='owner'").fetchall()
            if len(owners) != 1:
                raise ValueError("Recovery requires exactly one existing owner")
            owner = owners[0]
            saved = {"device_id": owner["id"], "token": secrets.token_urlsafe(32)}
            vault.write(saved)
            if vault.read() != saved:
                raise RuntimeError("Credential verification failed; database was not changed")
            revoked = db.execute(
                "SELECT count(*) FROM devices WHERE role='client' AND revoked=0"
            ).fetchone()[0]
            db.execute("UPDATE devices SET revoked=1 WHERE role='client'")
            db.execute("DELETE FROM pairings")
            db.execute(
                "UPDATE devices SET token_hash=?,revoked=0,scopes=? WHERE id=?",
                (digest(saved["token"]), canonical(sorted(CLIENT_SCOPES | {"admin"})), owner["id"]),
            )
        return {"device_id": owner["id"], "recovered": True, "revoked_devices": revoked}
    finally:
        for lock in reversed(locks):
            lock.release()
