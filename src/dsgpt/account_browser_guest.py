"""Trusted guest entry point. Only the private host pipe can control this page.

No HTTP listener, exposed bindings, arbitrary evaluation, or host file access.
The enclosing validated container, not Chromium flags, denies direct networking.
"""

import base64
import sys
from urllib.parse import urlsplit

from .account_browser_wire import decode_files, encode_files, pack, receive
from .account_browser_worker import AccountBrowserWorkerError, PrivateChromium


class AccountBrowserGuest:
    def __init__(self, browser, origin, exchange):
        self.browser, self.origin, self.exchange = browser, origin, exchange
        self.requests = 0
        target = browser._call("Target.createTarget", {"url": "about:blank"})["targetId"]
        self.session = browser._call(
            "Target.attachToTarget", {"targetId": target, "flatten": True}
        )["sessionId"]
        self.call("Page.enable")
        self.call("Network.enable")
        self.call("Network.setBypassServiceWorker", {"bypass": True})
        self.call("Emulation.setDeviceMetricsOverride", {
            "width": 1024, "height": 768, "deviceScaleFactor": 1, "mobile": False,
        })
        # Never disable interception while the browser is running. Unsupported
        # targets (popups/workers/WebSockets) cannot reach any external network.
        self.call("Fetch.enable", {"patterns": [{"urlPattern": "*"}]})

    def call(self, method, params=None):
        return self.browser._call(
            method, params, session=self.session, events=self.event, timeout=20,
        )

    def allowed(self, url):
        parts = urlsplit(url)
        return (
            parts.scheme == "https" and not parts.username and not parts.password
            and f"https://{parts.netloc}" == self.origin
        )

    def event(self, event):
        if event.get("method") != "Fetch.requestPaused":
            return
        params = event["params"]
        request, identifier = params["request"], params["requestId"]
        self.requests += 1
        if self.requests > 64:
            raise AccountBrowserWorkerError("account_browser_request_limit")
        result = None
        if self.allowed(request["url"]) and request["method"] in {"GET", "HEAD", "POST"}:
            body = request.get("postData", "").encode("utf-8")
            # Missing/truncated POST bytes must never authorize a different form.
            if len(body) <= 65536 and (not request.get("hasPostData") or body):
                headers = dict(request.get("headers", {}))
                # Fetch interception does not reliably include Cookie. Chromium
                # selects cookies for this exact same-origin request; HttpOnly
                # values stay in this private channel, never a page JS binding.
                cookies = self.call("Network.getCookies", {"urls": [request["url"]]})[
                    "cookies"
                ]
                headers = {k: v for k, v in headers.items() if k.lower() != "cookie"}
                if cookies:
                    headers["Cookie"] = "; ".join(
                        c["name"] + "=" + c["value"]
                        for c in sorted(cookies, key=lambda c: -len(c["path"]))
                    )
                result = self.exchange({
                    "kind": "request", "url": request["url"],
                    "method": request["method"], "headers": headers,
                    "body": base64.b64encode(body).decode("ascii"),
                })
        if result is None or result.get("kind") != "response":
            self.call("Fetch.failRequest", {
                "requestId": identifier, "errorReason": "BlockedByClient",
            })
        else:
            self.call("Fetch.fulfillRequest", {
                "requestId": identifier, "responseCode": result["status"],
                "responseHeaders": [{"name": k, "value": v} for k, v in result["headers"]],
                "body": result["body"],
            })

    def command(self, value):
        op = value.get("op")
        if op == "navigate" and set(value) == {"op", "url"} and self.allowed(value["url"]):
            result = self.call("Page.navigate", {"url": value["url"]})
            if "errorText" in result:
                raise AccountBrowserWorkerError("account_browser_navigation_failed")
        elif op == "frame" and set(value) == {"op"}:
            png = self.call("Page.captureScreenshot", {
                "format": "png", "captureBeyondViewport": False,
            })["data"]
            if len(png) > 2 * 1024**2:
                raise AccountBrowserWorkerError("account_browser_frame_limit")
            return {"png": png}
        elif op == "click" and set(value) == {"op", "x", "y"} and all(
            type(value[k]) is int and 0 <= value[k] < bound
            for k, bound in (("x", 1024), ("y", 768))
        ):
            for kind in ("mousePressed", "mouseReleased"):
                self.call("Input.dispatchMouseEvent", {
                    "type": kind, "x": value["x"], "y": value["y"],
                    "button": "left", "clickCount": 1,
                })
        elif op == "text" and set(value) == {"op", "text"} and (
            type(value["text"]) is str and len(value["text"]) <= 2048
        ):
            self.call("Input.insertText", {"text": value["text"]})
        elif op == "key" and set(value) == {"op", "key"} and value["key"] in {
            "Tab", "Enter", "Backspace", "Escape", "ArrowUp", "ArrowDown",
        }:
            for kind in ("keyDown", "keyUp"):
                codes = {"Tab": 9, "Enter": 13, "Backspace": 8, "Escape": 27,
                         "ArrowUp": 38, "ArrowDown": 40}
                self.call("Input.dispatchKeyEvent", {
                    "type": kind, "key": value["key"],
                    "windowsVirtualKeyCode": codes[value["key"]],
                })
        else:
            raise AccountBrowserWorkerError("account_browser_operation_denied")
        return {}


def main():
    browser = None

    def send(value):
        sys.stdout.buffer.write(pack(value))
        sys.stdout.buffer.flush()

    def exchange(value):
        send(value)
        return receive(sys.stdin.buffer)

    try:
        initial = receive(sys.stdin.buffer)
        browser = PrivateChromium("/work/account-profile", decode_files(initial["files"]))
        guest = AccountBrowserGuest(browser, initial["origin"], exchange)
        send({"kind": "ready"})
        for _ in range(256):
            command = receive(sys.stdin.buffer)
            if command == {"op": "close"}:
                files = browser.close_and_snapshot()
                send({"kind": "closed", "files": encode_files(files)})
                return
            send({"kind": "result", "value": guest.command(command)})
        raise AccountBrowserWorkerError("account_browser_command_limit")
    except Exception:
        # Neither exception text nor a traceback may cross the private boundary.
        send({"kind": "error"})
    finally:
        if browser is not None:
            browser.abort()


if __name__ == "__main__":
    main()
