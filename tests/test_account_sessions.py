import base64
import os

import httpx
import pytest
from fastapi.testclient import TestClient

from dsgpt.account_sessions import WindowsSessionProtection
from dsgpt.api import create_app
from dsgpt.config import Settings

SECRET = "fixture-session-secret"
REQUEST = {
    "label": "Test site",
    "origin": "https://example.org",
    "read_path": "/account",
    "session_cookie": f"sid={SECRET}",
}


class FixtureProtection:
    """A test double for the OS protection service, not production encryption."""

    available = True

    def seal(self, data, binding):
        return binding + base64.b64encode(data)

    def open(self, data, binding):
        if not data.startswith(binding):
            raise OSError("Wrong binding")
        return base64.b64decode(data[len(binding) :])


class Body(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b"<p>Signed-in fixture: " + SECRET.encode() + b"</p><script>hidden()</script>"


def test_owner_approved_session_survives_restart_and_revokes(tmp_path):
    seen = []

    def transport_factory(*, validator):
        def respond(request):
            validator(request.url)
            seen.append((str(request.url), request.headers["cookie"]))
            return httpx.Response(200, headers={"Content-Type": "text/html"}, stream=Body())

        return httpx.MockTransport(respond)

    def app():
        app = create_app(Settings(tmp_path, allowed_hosts=("testserver",)))
        app.state.account_sessions.protection = FixtureProtection()
        app.state.account_sessions.transport_factory = transport_factory
        return app

    first = app()
    auth = first.state.auth
    headers = {"Authorization": "Bearer " + auth.initialize_owner()["token"]}
    client = auth.redeem(auth.create_pairing(["work"])["code"], "Paired fixture")
    path = "/v1/account-sessions"

    with TestClient(first, client=("127.0.0.1", 12345)) as api:
        assert (
            api.get(path, headers={"Authorization": "Bearer " + client["token"]}).status_code == 403
        )
        created = api.post(path, json=REQUEST, headers=headers)
        assert created.status_code == 201, created.text
        session = created.json()["id"]
        assert SECRET not in created.text and "cookie" not in created.text
        row = first.state.store.one(
            "SELECT sealed_cookie FROM account_sessions WHERE id=?", (session,)
        )
        assert SECRET.encode() not in row["sealed_cookie"]
        assert seen == []  # Enrollment itself never contacts the website.
    second = app()
    with TestClient(second, client=("127.0.0.1", 12345)) as api:
        assert api.get(path, headers=headers).json()["sessions"][0]["id"] == session
        read = api.post(f"{path}/{session}/read", headers=headers)
        assert read.status_code == 200
        assert "Signed-in fixture: [redacted]" in read.json()["text"]
        assert SECRET not in read.text and "hidden()" not in read.text
        assert seen == [("https://example.org/account", f"sid={SECRET}")]
        assert api.delete(f"{path}/{session}", headers=headers).status_code == 204
        assert api.post(f"{path}/{session}/read", headers=headers).status_code == 404
        assert len(seen) == 1
        assert (
            second.state.store.one("SELECT id FROM account_sessions WHERE id=?", (session,)) is None
        )


def test_account_routes_reject_remote_owner_unsafe_scope_and_redirect(tmp_path):
    app = create_app(Settings(tmp_path, allowed_hosts=("testserver",)))
    headers = {"Authorization": "Bearer " + app.state.auth.initialize_owner()["token"]}
    app.state.account_sessions.protection = FixtureProtection()
    seen = []

    def transport_factory(*, validator):
        def respond(request):
            validator(request.url)
            seen.append(str(request.url))
            return httpx.Response(302, headers={"Location": "https://other.example.org/"})

        return httpx.MockTransport(respond)

    app.state.account_sessions.transport_factory = transport_factory
    path = "/v1/account-sessions"
    remote = TestClient(app, client=("192.0.2.8", 12345))
    assert remote.post(path, json=REQUEST, headers=headers).status_code == 403
    with TestClient(app, client=("127.0.0.1", 12345)) as api:
        for patch in (
            {"origin": "https://127.0.0.1"},
            {"origin": "https://user:secret@example.org"},
            {"read_path": "//other.example.org"},
            {"read_path": "/account/../other"},
            {"read_path": "/account?token=secret"},
            {"session_cookie": f"sid={SECRET}\r\nX-Forged: yes"},
        ):
            denied = api.post(path, json={**REQUEST, **patch}, headers=headers)
            assert denied.status_code == 422 and SECRET not in denied.text
        assert not seen
        session = api.post(path, json=REQUEST, headers=headers).json()["id"]
        blocked = api.post(f"{path}/{session}/read", headers=headers)
        assert blocked.status_code == 409
        assert seen == ["https://example.org/account"]
        assert "other.example.org" not in blocked.text


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI integration")
def test_windows_session_protection_uses_bound_encrypted_bytes():
    protector = WindowsSessionProtection()
    secret = SECRET.encode()
    protected = protector.seal(secret, b"bound session")
    assert secret not in protected
    assert protector.open(protected, b"bound session") == secret
    with pytest.raises(OSError):
        protector.open(protected, b"different session")
