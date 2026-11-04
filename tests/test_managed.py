import hashlib
import hmac

import httpx
import pytest
from fastapi.testclient import TestClient

from dsgpt.api import create_app
from dsgpt.config import Settings
from dsgpt.managed import ORIGIN, identity_proof, verify_running, wire_desktop
from dsgpt.windows_security import private_directory


class Vault:
    def __init__(self, value=None, discard=False):
        self.value, self.discard = value, discard
        self.writes = 0

    def read(self):
        return self.value

    def write(self, value):
        self.writes += 1
        if not self.discard:
            self.value = value


def test_owner_wireup_is_idempotent_and_preserves_existing_connection():
    owner, client = Vault({"device_id": "id", "token": "a" * 43}), Vault()
    wire_desktop(owner, client)
    assert client.value == {"origin": ORIGIN, "token": "a" * 43}
    wire_desktop(owner, client)
    assert client.writes == 1
    owner.value["token"] = "b" * 43
    with pytest.raises(RuntimeError, match="preserved"):
        wire_desktop(owner, client)
    assert client.value["token"] == "a" * 43
    with pytest.raises(RuntimeError, match="verification"):
        wire_desktop(owner, Vault(discard=True))


def test_identity_challenge_is_fresh_and_never_sends_token_to_unknown_service():
    token = "private-owner-token"
    challenges = []

    def handler(request):
        assert "authorization" not in request.headers
        assert token not in str(request.url)
        challenge = request.url.params["challenge"]
        challenges.append(challenge)
        return httpx.Response(
            200, json={"version": "test", "proof": identity_proof(token, challenge, "test")}
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert verify_running(token, client) == "test"
        assert verify_running(token, client) == "test"
    assert len(set(challenges)) == 2
    expected = hmac.new(
        token.encode(),
        f"dsGPT managed backend identity v1\n{challenges[0]}\ntest".encode(),
        hashlib.sha256,
    ).hexdigest()
    assert identity_proof(token, challenges[0], "test") == expected


@pytest.mark.parametrize(
    "body",
    [
        {"version": "test", "proof": "wrong"},
        {"version": "test", "proof": None},
        [],
        "untrusted",
        {"version": "test"},
    ],
)
def test_spoofed_backend_does_not_receive_any_credential(body):
    def handler(request):
        assert "authorization" not in request.headers
        return httpx.Response(200, json=body)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert verify_running("secret", client) is None


def test_managed_stop_is_owner_only_and_absent_in_developer_backend(tmp_path):
    stops = []
    app = create_app(
        Settings(tmp_path / "data", allowed_hosts=("testserver",)),
        managed={
            "identity": lambda nonce: {
                "proof": identity_proof("key", nonce, "test"),
                "version": "test",
            },
            "stop": lambda: stops.append(True),
        },
    )
    token = app.state.auth.initialize_owner()["token"]
    with TestClient(app) as client:
        assert client.get("/managed/identity?challenge=bad").status_code == 422
        response = client.get("/managed/identity?challenge=" + "a" * 64)
        assert response.status_code == 200 and "key" not in response.text
        assert client.post("/v1/backend/stop").status_code == 401
        assert (
            client.post(
                "/v1/backend/stop", headers={"Authorization": "Bearer " + token}
            ).status_code
            == 200
        )
        assert stops == [True]
    other = create_app(Settings(tmp_path / "other", allowed_hosts=("testserver",)))
    with TestClient(other) as client:
        assert client.post("/v1/backend/stop").status_code == 404
        assert client.get("/managed/identity?challenge=" + "a" * 64).status_code == 404


def test_windows_acl_has_no_portable_insecure_fallback(tmp_path):
    import os

    if os.name != "nt":
        with pytest.raises(RuntimeError, match="Windows"):
            private_directory(tmp_path / "managed")
        assert not (tmp_path / "managed").exists()


def test_explicit_recovery_rewires_only_the_managed_local_connection():
    owner, client = Vault(), Vault()
    owner.value = {"device_id": "owner", "token": "replacement-token"}
    client.value = {"origin": ORIGIN, "token": "old-token"}
    wire_desktop(owner, client, recover_local=True)
    assert client.value == {"origin": ORIGIN, "token": "replacement-token"}
    remote = {"origin": "https://other.tailnet.ts.net", "token": "other-token"}
    client.value = remote.copy()
    with pytest.raises(RuntimeError, match="Existing desktop connection preserved"):
        wire_desktop(owner, client, recover_local=True)
    assert client.value == remote
