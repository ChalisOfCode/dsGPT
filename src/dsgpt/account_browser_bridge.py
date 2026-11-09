"""Internal owner-browser bridge, separate from Work projects and diagnostics.

The local owner controller supplies live authority checks. The bridge never
approves a POST; page/task-bound approval remains unimplemented. Private
frames/input/profile bytes must not enter model tools.
"""

import asyncio
import base64
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from .account_browser_network import AccountBrowserNetworkError
from .account_browser_wire import decode_files, encode_files, pack, size
from .sandbox import source_archive

BOOT = (
    "import sys;sys.path.insert(0,'/work/account-driver');"
    "from dsgpt.account_browser_guest import main;main()"
)
MODULES = (
    "account_browser_guest.py", "account_browser_worker.py",
    "account_browser_wire.py", "account_browser_profile_data.py",
)


class AccountBrowserBridgeError(Exception):
    pass


class AccountBrowserBridge:
    def __init__(self, sandbox, vault, network, authorize):
        self.sandbox, self.vault, self.network = sandbox, vault, network
        self.authorize = authorize
        self.identifier = str(uuid4())  # Never reuse a project container.
        self.process = None
        self.revision = None
        self.lock = asyncio.Lock()
        self.started = False
        self.stopped = False
        self.closing = False
        self._startup_task = self._active_task = None

    def _authorize(self):
        if self.stopped:
            raise AccountBrowserBridgeError("account_browser_closed")
        self.authorize()
        self.vault.require_origin(self.network.origin)

    async def start(self):
        if self.started or self.stopped:
            raise AccountBrowserBridgeError("account_browser_already_started")
        self.started = True
        self._startup_task = asyncio.current_task()
        try:
            self._authorize()
            self.revision, files = self.vault.restore()
            name = await self.sandbox.create(self.identifier)
            sources = {"__init__.py": b""}
            sources.update({n: Path(__file__).with_name(n).read_bytes() for n in MODULES})
            archive = source_archive([
                {"path": "account-driver/dsgpt/" + n, "content": data,
                 "sha256": hashlib.sha256(data).hexdigest()}
                for n, data in sources.items()
            ])
            # Only audited driver source goes through tar stdin. Profiles and
            # credentials travel over stdin/stdout, never host files or argv.
            await self.sandbox.checked([
                "container", "exec", "-i", "--", name, "tar", "-xf", "-", "-C", "/work",
            ], data=archive)
            value = await self.sandbox.inspect(name)
            self.sandbox.validate_container(value, self.identifier)
            if value["HostConfig"].get("LogConfig", {}).get("Type") != "none":
                raise AccountBrowserBridgeError("account_browser_logging_denied")
            self._authorize()
            self.process = await self.sandbox._spawn([
                "container", "exec", "-i", "--", name, "python3", "-I", "-c", BOOT,
            ], input_pipe=True, private=True)
            await self._exchange({"origin": self.network.origin, "files": encode_files(files)},
                                 expected="ready")
        except asyncio.CancelledError:
            await self.abort()
            raise
        except Exception:
            await self.abort()
            raise AccountBrowserBridgeError("account_browser_start_failed") from None
        finally:
            self._startup_task = None

    async def _exchange(self, command, *, expected="result"):
        if self.closing and expected != "closed":
            raise AccountBrowserBridgeError("account_browser_closing")
        if self.lock.locked():
            raise AccountBrowserBridgeError("account_browser_busy")
        async with self.lock:
            if self.process is None:
                raise AccountBrowserBridgeError("account_browser_closed")
            self._active_task = asyncio.current_task()
            try:
                async with asyncio.timeout(25):
                    self._authorize()
                    await self._send(command)
                    for _ in range(65):
                        row = await self._receive()
                        self._authorize()
                        if row.get("kind") == expected:
                            return row
                        if row.get("kind") != "request":
                            raise AccountBrowserBridgeError("account_browser_protocol_failed")
                        await self._resource(row)
                    raise AccountBrowserBridgeError("account_browser_request_limit")
            except asyncio.CancelledError:
                await self.abort()
                raise
            except Exception:
                await self.abort()
                raise AccountBrowserBridgeError("account_browser_operation_failed") from None
            finally:
                self._active_task = None

    async def _send(self, row):
        self.process.stdin.write(pack(row))
        await self.process.stdin.drain()

    async def _receive(self):
        length = size(await self.process.stdout.readexactly(4))
        row = json.loads(await self.process.stdout.readexactly(length))
        if type(row) is not dict:
            raise AccountBrowserBridgeError("account_browser_protocol_failed")
        return row

    async def _resource(self, row):
        # Task/page-bound approval UI is not wired yet. Even an out-of-band
        # approval on the broker must not enable a write through this bridge.
        if row.get("method") not in {"GET", "HEAD"}:
            self._authorize()
            await self._send({"kind": "denied"})
            return
        try:
            response = await self.network.fetch(
                row["url"], row["method"], row["headers"],
                base64.b64decode(row["body"], validate=True),
            )
            self._authorize()
            await self._send({
                "kind": "response", "status": response.status, "headers": response.headers,
                "body": base64.b64encode(response.body).decode("ascii"),
            })
        except AccountBrowserNetworkError:
            self._authorize()
            await self._send({"kind": "denied"})

    async def navigate(self, url):
        # Host validation precedes any guest input, including malformed URLs.
        self.network._url(url)
        await self._exchange({"op": "navigate", "url": url})

    async def frame(self):
        row = await self._exchange({"op": "frame"})
        try:
            png = row["value"]["png"]
            if type(png) is not str or len(png) > 2 * 1024**2:
                raise ValueError
            decoded = base64.b64decode(png, validate=True)
            if not decoded.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError
            return decoded
        except Exception:
            await self.abort()
            raise AccountBrowserBridgeError("account_browser_frame_invalid") from None

    async def click(self, x, y):
        await self._exchange({"op": "click", "x": x, "y": y})

    async def type_text(self, text):
        await self._exchange({"op": "text", "text": text})

    async def key(self, key):
        await self._exchange({"op": "key", "key": key})

    async def close(self):
        # Revoked/failed processes never save. Only clean Chromium shutdown AND
        # successful guest exit allow atomic vault replacement of this revision.
        if self.lock.locked() or self._startup_task is not None or self.closing:
            raise AccountBrowserBridgeError("account_browser_busy")
        self.closing = True
        try:
            row = await self._exchange({"op": "close"}, expected="closed")
            async with asyncio.timeout(5):
                if await self.process.wait() != 0:
                    raise AccountBrowserBridgeError("account_browser_unclean_shutdown")
            self._authorize()
            files = decode_files(row["files"])
            if files is None:
                raise AccountBrowserBridgeError("account_browser_profile_invalid")
            self.revision = self.vault.save(files, expected_revision=self.revision)
            return self.revision
        finally:
            await self.abort()

    async def abort(self):
        self.stopped = True
        current = asyncio.current_task()
        pending = {t for t in (self._startup_task, self._active_task)
                   if t is not None and t is not current and not t.done()}
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        process, self.process = self.process, None
        try:
            if process is not None and process.returncode is None:
                process.kill()
                await process.wait()
        finally:
            if self.started:
                cleanup = asyncio.create_task(self.sandbox.cleanup(self.identifier))
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    await asyncio.gather(cleanup, return_exceptions=True)
                    raise
