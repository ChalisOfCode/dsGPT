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


def test_form_review_is_single_use_and_recovery_requires_fresh_observation(app):
    import time

    from dsgpt.storage import uid

    effects = []

    class FormBridge(BridgeFixture):
        def __init__(self, sandbox, vault, network, authorize):
            super().__init__(sandbox, vault, network, authorize)
            self.network = network

        async def submit(self, command, review):
            self.authorize()
            action = await review("/sign-in")
            if action:
                self.network._writes.begin(action, origin=self.network.origin)
                effects.append(command)
                self.network._writes.response_received(action)
            assert await review("/second-form") is None

    app.state.account_browsers.bridge_factory = FormBridge
    headers = owner_headers(app)
    paired = app.state.auth.redeem(app.state.auth.create_pairing(["work"])["code"], "Fixture")
    paired_headers = {"Authorization": "Bearer " + paired["token"]}
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        def post(path, body=None):
            return client.post(path, json=body, headers=headers)

        def status():
            return client.get(submissions, headers=headers).json()

        def until(condition):
            for _ in range(100):
                value = status()
                if condition(value):
                    return value
                time.sleep(0.01)
            pytest.fail("Submission did not reach expected fixture state")

        created = post(PATH + "/browser", ENROLL)
        app.state.builds.sandbox = object()
        app.state.builds.ready = True
        base = PATH + "/" + created.json()["id"] + "/browser"
        handoff = base + "/" + post(base).json()["handoff_id"]
        submissions = handoff + "/submissions"
        frame = post(handoff + "/frame")
        observation = frame.headers["x-dsgpt-observation"]
        click = {"op": "click", "x": 50, "y": 60}
        assert post(submissions + "?observation_id=" + uid(), click).status_code == 409
        started = post(submissions + "?observation_id=" + observation, click)
        assert started.status_code == 202
        pending = until(lambda value: value["review"])
        assert pending["review"]["path"] == "/sign-in"
        assert effects == []
        assert post(handoff + "/frame").status_code == 409
        assert post(handoff + "/save").status_code == 409
        decision = submissions + "/" + started.json()["submission_id"] + "/decision"
        body = {"review_id": pending["review"]["review_id"], "approve": True}
        assert client.post(decision, json=body, headers=paired_headers).status_code == 403
        assert post(decision, {**body, "review_id": uid()}).status_code == 409
        assert post(decision, body).status_code == 204
        assert post(decision, body).status_code == 409
        done = until(lambda value: value["state"] == "finished")
        assert effects == [click]
        assert done["review"] is None
        receipt, = done["unverified"]
        assert receipt["status"] == "response_received"
        verify = {"observation_id": observation, "action_id": receipt["id"], "applied": True}
        assert post(handoff + "/verification", verify).status_code == 409
        observation = post(handoff + "/frame").headers["x-dsgpt-observation"]
        assert post(submissions + "?observation_id=" + observation, click).status_code == 409
        assert post(handoff + "/verification", {
            **verify, "observation_id": observation,
        }).status_code == 204
        assert status()["unverified"] == []
        assert post(submissions + "?observation_id=" + observation, click).status_code == 409
        observation = post(handoff + "/frame").headers["x-dsgpt-observation"]
        started = post(submissions + "?observation_id=" + observation, click)
        pending = until(lambda value: value["review"])
        decision = submissions + "/" + started.json()["submission_id"] + "/decision"
        assert post(decision, {"review_id": pending["review"]["review_id"],
                               "approve": False}).status_code == 204
        assert until(lambda value: value["state"] == "finished")["unverified"] == []
        assert effects == [click]
