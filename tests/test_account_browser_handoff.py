import pytest
from fastapi.testclient import TestClient
from test_account_sessions import FixtureProtection

from dsgpt.api import create_app
from dsgpt.config import Settings

PATH = "/v1/account-sessions"
FRAME = b"fixture-image"
TYPED = "credential-input-fixture-only"
ENROLL = {"label": "Fixture", "origin": "https://example.org", "read_path": "/sign-in"}


class BridgeFixture:
    def __init__(self, sandbox, vault, network, authorize):
        self.authorize = authorize
        self.events = []

    async def start(self):
        self.authorize()
        self.events.append("start")

    async def navigate(self, url):
        self.authorize()
        assert url == "https://example.org/sign-in"

    async def frame(self):
        self.authorize()
        return FRAME

    async def type_text(self, text):
        self.authorize()
        assert text == TYPED
        self.events.append("input")

    async def close(self):
        self.authorize()
        self.events.append("save")

    async def abort(self):
        self.events.append("abort")


@pytest.fixture
def app(tmp_path):
    app = create_app(Settings(tmp_path, allowed_hosts=("testserver",)))
    app.state.account_sessions.protection = FixtureProtection()
    controller = app.state.account_browsers
    controller.bridge_factory = BridgeFixture
    return app


def owner_headers(app):
    return {"Authorization": "Bearer " + app.state.auth.initialize_owner()["token"]}


def test_owner_handoff_revocation_and_fresh_generation(app):
    headers = owner_headers(app)
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        created = client.post(PATH + "/browser", json=ENROLL, headers=headers)
        assert created.status_code == 201
        assert client.get(PATH, headers=headers).json()["sessions"][0]["browser_profile"] == 1
        session = PATH + "/" + created.json()["id"]
        assert client.post(session + "/read", headers=headers).status_code == 409
        browser = session + "/browser"
        assert client.post(browser, headers=headers).status_code == 503
        app.state.builds.sandbox = object()
        app.state.builds.ready = True
        opened = client.post(browser, headers=headers)
        assert opened.status_code == 200
        handoff = browser + "/" + opened.json()["handoff_id"]
        bridge = app.state.account_browsers.active.bridge
        assert client.post(browser, headers=headers).status_code == 409
        frame = client.post(handoff + "/frame", headers=headers)
        assert frame.content == FRAME
        assert frame.headers["content-type"] == "image/png"
        assert frame.headers["cache-control"] == "no-store"
        sent = client.post(handoff + "/input", json={"op": "text", "text": TYPED}, headers=headers)
        assert sent.status_code == 204 and not sent.content
        invalid = client.post(
            handoff + "/input", json={"op": "text", "text": TYPED, "method": "eval"},
            headers=headers,
        )
        assert invalid.status_code == 422 and TYPED not in invalid.text
        assert client.post(handoff + "/save", headers=headers).status_code == 204
        assert bridge.events == ["start", "input", "save"]
        assert client.post(handoff + "/frame", headers=headers).status_code == 404
        opened = client.post(browser, headers=headers)
        assert opened.status_code == 200
        replacement = browser + "/" + opened.json()["handoff_id"]
        assert replacement != handoff
        bridge = app.state.account_browsers.active.bridge
        assert client.delete(handoff, headers=headers).status_code == 204
        assert bridge.events == ["start"]
        assert client.post(replacement + "/frame", headers=headers).status_code == 200
        assert client.delete(session, headers=headers).status_code == 204
        assert bridge.events == ["start", "abort"]
        assert client.post(replacement + "/frame", headers=headers).status_code == 404
        assert client.delete(replacement, headers=headers).status_code == 204
        assert not app.state.store.all("SELECT * FROM account_sessions")
        for file in app.state.store.directory.glob("*.db*"):
            assert TYPED.encode() not in file.read_bytes()


def test_handoff_requires_local_owner(app):
    headers = owner_headers(app)
    paired = app.state.auth.redeem(app.state.auth.create_pairing(["work"])["code"], "Fixture")
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        denied = client.post(
            PATH + "/browser", json=ENROLL,
            headers={"Authorization": "Bearer " + paired["token"]},
        )
        assert denied.status_code == 403
    client = TestClient(app, client=("192.0.2.1", 12345))
    assert client.post(PATH + "/browser", json=ENROLL, headers=headers).status_code == 403
    assert not app.state.store.all("SELECT * FROM account_sessions")
