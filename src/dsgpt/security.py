import hashlib
import json
import secrets
import time

from fastapi import HTTPException

from .storage import canonical, uid, utcnow

CLIENT_SCOPES = {"chat", "work", "diagnostics", "models"}


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Auth:
    def __init__(self, store):
        self.store = store

    def initialize_owner(self):
        with self.store.transaction() as db:
            if db.execute("SELECT 1 FROM devices WHERE role='owner'").fetchone():
                raise ValueError("Owner already initialized; existing credentials were preserved")
            token = secrets.token_urlsafe(32)
            device_id = uid()
            db.execute(
                "INSERT INTO devices(id,name,role,token_hash,scopes,created_at) "
                "VALUES(?,?,?,?,?,?)",
                (
                    device_id,
                    "Desktop owner",
                    "owner",
                    digest(token),
                    canonical(sorted(CLIENT_SCOPES | {"admin"})),
                    utcnow(),
                ),
            )
        return {"device_id": device_id, "token": token}

    def authenticate(self, authorization):
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "Authentication required")
        token = authorization[7:]
        if len(token) > 200:
            raise HTTPException(401, "Invalid device credential")
        device = self.store.one(
            "SELECT * FROM devices WHERE token_hash=? AND revoked=0", (digest(token),)
        )
        if not device:
            raise HTTPException(401, "Invalid or revoked device credential")
        device.pop("token_hash")
        device["scopes"] = json.loads(device["scopes"])
        return device

    def create_pairing(self, scopes):
        if not set(scopes) <= CLIENT_SCOPES or not scopes:
            raise HTTPException(422, "Pairing scopes are invalid")
        code = secrets.token_urlsafe(32)
        expires = time.time() + 300
        with self.store.transaction() as db:
            db.execute("DELETE FROM pairings WHERE expires<?", (time.time(),))
            db.execute(
                "INSERT INTO pairings VALUES(?,?,?)",
                (digest(code), expires, canonical(sorted(set(scopes)))),
            )
        return {"code": code, "expires_at_unix": expires, "one_use": True}

    def redeem(self, code, name):
        with self.store.transaction() as db:
            pair = db.execute(
                "SELECT * FROM pairings WHERE code_hash=? AND expires>?",
                (digest(code), time.time()),
            ).fetchone()
            if not pair:
                raise HTTPException(401, "Pairing code is invalid, used, or expired")
            device_id, token = uid(), secrets.token_urlsafe(32)
            db.execute("DELETE FROM pairings WHERE code_hash=?", (digest(code),))
            db.execute(
                "INSERT INTO devices(id,name,role,token_hash,scopes,created_at) "
                "VALUES(?,?,?,?,?,?)",
                (device_id, name, "client", digest(token), pair["scopes"], utcnow()),
            )
        self.store.log("device_paired", device_id)
        return {"device_id": device_id, "token": token, "scopes": json.loads(pair["scopes"])}

    def revoke(self, device_id):
        with self.store.transaction() as db:
            row = db.execute("SELECT role FROM devices WHERE id=?", (device_id,)).fetchone()
            if not row:
                raise HTTPException(404, "Device not found")
            if row["role"] == "owner":
                raise HTTPException(409, "Owner credential rotation requires local recovery")
            db.execute("UPDATE devices SET revoked=1 WHERE id=?", (device_id,))
        self.store.log("device_revoked", device_id)
