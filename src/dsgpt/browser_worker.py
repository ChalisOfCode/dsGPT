"""Trusted browser driver. Run only in the checked networkless tool container."""

import base64
import json
import os
import subprocess
import threading
import time
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def main():
    import websocket

    request = json.loads(Path(".dsgpt-browser/request.json").read_text())
    server = ThreadingHTTPServer(("127.0.0.1", 8765), partial(QuietHandler, directory="/work"))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    process = subprocess.Popen(
        [
            "/usr/bin/chromium",
            "--headless",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--disable-background-networking",
            "--no-first-run",
            "--disable-extensions",
            "--disable-sync",
            "--no-proxy-server",
            "--remote-debugging-address=127.0.0.1",
            "--remote-debugging-port=9222",
            "--user-data-dir=/tmp/dsgpt-browser",
            "--window-size=1280,900",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**os.environ, "HOME": "/tmp"},
    )
    connection = None
    try:
        for _attempt in range(100):
            try:
                with urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=1) as response:
                    tabs = json.load(response)
                tab = next(t for t in tabs if t["type"] == "page")
                connection = websocket.create_connection(
                    tab["webSocketDebuggerUrl"], timeout=5, suppress_origin=True
                )
                break
            except (OSError, ValueError, StopIteration):
                if process.poll() is not None:
                    raise RuntimeError("Chromium failed to start") from None
                time.sleep(0.1)
        if connection is None:
            raise RuntimeError("Chromium startup timeout")
        sequence, resource_number = 0, 0
        pending = {}
        public = bool(request.get("public_url"))
        bridge = Path(".dsgpt-browser/bridge")
        bridge.mkdir(exist_ok=True)

        def serve_resource(event):
            nonlocal resource_number
            resource_number += 1
            item = event["request"]
            if resource_number > 32 or item["method"] != "GET":
                call(
                    "Fetch.failRequest",
                    {"requestId": event["requestId"], "errorReason": "BlockedByClient"},
                )
                return
            path = bridge / str(resource_number)
            path.with_suffix(".request").write_text(
                json.dumps(
                    {
                        "id": resource_number,
                        "url": item["url"],
                        "method": item["method"],
                    }
                )
            )
            deadline = time.monotonic() + 20
            while not path.with_suffix(".response").exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            if not path.with_suffix(".response").exists():
                raise RuntimeError("Public resource broker timeout")
            response = json.loads(path.with_suffix(".response").read_text())
            if response.get("error"):
                call(
                    "Fetch.failRequest",
                    {"requestId": event["requestId"], "errorReason": "BlockedByClient"},
                )
            else:
                call(
                    "Fetch.fulfillRequest",
                    {
                        "requestId": event["requestId"],
                        "responseCode": response["status"],
                        "body": response["body"],
                        "responseHeaders": response["headers"],
                    },
                )

        def call(method, params=None):
            nonlocal sequence
            sequence += 1
            identifier = sequence
            connection.send(
                json.dumps({"id": identifier, "method": method, "params": params or {}})
            )
            deadline = time.monotonic() + (60 if public else 8)
            while time.monotonic() < deadline:
                value = pending.pop(identifier, None)
                if value is None:
                    value = json.loads(connection.recv())
                if value.get("id") == identifier:
                    if "error" in value:
                        raise RuntimeError("Browser command failed: " + str(value["error"])[:200])
                    return value.get("result", {})
                if value.get("id"):
                    pending[value["id"]] = value
                elif public and value.get("method") == "Fetch.requestPaused":
                    serve_resource(value["params"])
            raise RuntimeError("Browser command timeout")

        def evaluate(expression):
            result = call(
                "Runtime.evaluate",
                {"expression": expression, "returnByValue": True, "timeout": 2000},
            )
            if "exceptionDetails" in result:
                raise RuntimeError("Browser interaction failed")
            return result.get("result", {}).get("value")

        call("Page.enable")
        call("Browser.setDownloadBehavior", {"behavior": "deny"})
        call(
            "Emulation.setDeviceMetricsOverride",
            {"width": 1280, "height": 900, "deviceScaleFactor": 1, "mobile": False},
        )
        if public:
            call("Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]})
        target = request.get("public_url") or "http://127.0.0.1:8765/" + quote(
            request["path"], safe="/"
        )
        call("Page.navigate", {"url": target})
        for _attempt in range(50):
            if evaluate("document.readyState") == "complete" and (
                public or evaluate("location.href") == target
            ):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("Local page did not finish loading")
        results = []
        for step in request["steps"]:
            selector = json.dumps(step["selector"])
            if step["action"] == "click":
                ok = evaluate(
                    f"(()=>{{const e=document.querySelector({selector});"
                    "if(!e)return false; e.click();return true})()"
                )
            else:
                value = json.dumps(step.get("text", ""))
                ok = evaluate(
                    f"(()=>{{const e=document.querySelector({selector});"
                    'if(!e || !["INPUT","TEXTAREA"].includes(e.tagName) || e.type==="file")'
                    f"return false; e.focus();e.value={value};"
                    'e.dispatchEvent(new Event("input",{bubbles:true}));'
                    'e.dispatchEvent(new Event("change",{bubbles:true}));return true})()'
                )
            if not ok:
                raise RuntimeError("Element unavailable: " + step["selector"])
            time.sleep(0.15)
            results.append(
                {"action": step["action"], "selector": step["selector"], "completed": True}
            )
        time.sleep(0.3)
        if public:
            for _settle in range(10):
                evaluate("document.readyState")
                time.sleep(0.1)
        result = evaluate(
            '({title:document.title,text:document.body.innerText.slice(0,12000),controls:[...document.querySelectorAll("button,input,textarea,a,select")].slice(0,80).map(e=>({tag:e.tagName,id:e.id,name:e.getAttribute("name"),text:(e.innerText||e.getAttribute("aria-label")||"").slice(0,160)}))})'
        )
        result["links"] = evaluate(
            '[...document.querySelectorAll("a[href]")].slice(0,60).map(e=>e.href)'
        )
        result["url"] = evaluate("location.href")
        result.update(
            steps=results,
            network="none",
            viewport=[1280, 900],
            public_resource_requests=resource_number,
        )
        screenshot = call(
            "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False}
        )
        Path(".dsgpt-browser/screenshot.png").write_bytes(base64.b64decode(screenshot["data"]))
        Path(".dsgpt-browser/result.json").write_text(json.dumps(result))
        print(json.dumps(result))
    finally:
        if connection:
            connection.close()
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        server.shutdown()


if __name__ == "__main__":
    main()
