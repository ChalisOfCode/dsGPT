"""Actual Chromium profile persistence using a synthetic intercepted origin."""

import base64
import os
import sys

import pytest
from test_account_browser_profiles import vault
from test_account_browser_writes import make_ledger

from dsgpt import account_browser_worker as worker

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux Chromium guest worker")


def test_reject_link_and_out_of_scope_profile_files(tmp_path):
    with pytest.raises(worker.AccountBrowserWorkerError, match="file_denied"):
        worker._restore(tmp_path / "denied", {"Default/History": b"not selected"})
    root = tmp_path / "profile"
    root.mkdir()
    (root / "Default").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(worker.AccountBrowserWorkerError, match="file_denied"):
        worker._snapshot(root)


@pytest.mark.skipif(not os.environ.get("DSGPT_PROFILE_TEST_CHROMIUM"), reason="needs Chromium")
def test_browser_cookie_local_storage_and_indexeddb_after_vault_restart(tmp_path, monkeypatch):
    binary = os.environ["DSGPT_PROFILE_TEST_CHROMIUM"]
    # Production requires an owned networkless container. This fixture runs on
    # the test host with the same DNS denial and serves responses through CDP.
    monkeypatch.setattr(worker, "_container_only", lambda: None)
    base = "https://fixture.test"

    db = """const d = await new Promise((resolve, reject) => {
      const request = indexedDB.open('fixture', 1);
      request.onupgradeneeded = () => request.result.createObjectStore('state');
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });"""

    def navigate(browser, url):
        target = browser._call("Target.createTarget", {"url": "about:blank"})["targetId"]
        session = browser._call("Target.attachToTarget", {"targetId": target, "flatten": True})[
            "sessionId"
        ]
        browser._call("Fetch.enable", {"patterns": [{"urlPattern": "*"}]}, session=session)

        def respond(event):
            if event["method"] != "Fetch.requestPaused":
                return
            req = event["params"]
            if req["request"]["url"] != url:
                browser._call(
                    "Fetch.failRequest",
                    {
                        "requestId": req["requestId"],
                        "errorReason": "BlockedByClient",
                    },
                    session=session,
                    events=respond,
                )
                return
            headers = [{"name": "Content-Type", "value": "text/html"}]
            if url.endswith("/login"):
                headers.append(
                    {
                        "name": "Set-Cookie",
                        "value": "fixture=profile-sentinel; Max-Age=600; Secure; HttpOnly",
                    }
                )
            browser._call(
                "Fetch.fulfillRequest",
                {
                    "requestId": req["requestId"],
                    "responseCode": 200,
                    "responseHeaders": headers,
                    "body": base64.b64encode(
                        b"<!doctype html><title>Profile fixture</title>"
                    ).decode(),
                },
                session=session,
                events=respond,
            )

        response = browser._call("Page.navigate", {"url": url}, session=session, events=respond)
        assert "errorText" not in response
        browser._call("Fetch.disable", session=session, events=respond)
        return session

    def run(browser, session, expr):
        result = browser._call(
            "Runtime.evaluate",
            {
                "expression": "(async () => {" + db + expr + "})()",
                "awaitPromise": True,
                "returnByValue": True,
            },
            session=session,
        )
        assert "exceptionDetails" not in result
        return result["result"].get("value")

    ledger = make_ledger(tmp_path / "store")
    first = worker.PrivateChromium(tmp_path / "first", binary=binary)
    try:
        session = navigate(first, base + "/login")
        assert (
            run(
                first,
                session,
                """
          localStorage.setItem('owner', 'local-sentinel');
          await new Promise((resolve, reject) => {
            const tx = d.transaction('state', 'readwrite');
            tx.objectStore('state').put('indexed-sentinel', 'owner');
            tx.oncomplete = resolve;
            tx.onerror = reject;
          });
          d.close(); return true;
        """,
            )
            is True
        )
        vault(ledger).save(first.close_and_snapshot(), expected_revision=0)
    finally:
        first.abort()
    revision, files = vault(ledger).restore()
    assert revision == 1
    second = worker.PrivateChromium(tmp_path / "second", files, binary=binary)
    try:
        session = navigate(second, base + "/check")
        assert run(
            second,
            session,
            """
          const value = await new Promise((resolve, reject) => {
            const req = d.transaction('state').objectStore('state').get('owner');
            req.onsuccess = () => resolve(req.result);
            req.onerror = () => reject(req.error);
          });
          d.close(); return [localStorage.getItem('owner'), value, document.cookie];
        """,
        ) == ["local-sentinel", "indexed-sentinel", ""]
        cookies = second._call("Network.getCookies", {"urls": [base]}, session=session)["cookies"]
        assert [(c["name"], c["value"], c["httpOnly"]) for c in cookies] == [
            ("fixture", "profile-sentinel", True)
        ]
        second.process.kill()
        second.process.wait(timeout=5)
        with pytest.raises(worker.AccountBrowserWorkerError, match="pipe_failed"):
            second.close_and_snapshot()
        assert vault(ledger).restore()[0] == 1
    finally:
        second.abort()
