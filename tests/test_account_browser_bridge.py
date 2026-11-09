"""Real guest pipe/Chromium/broker fixture; Docker and TLS are NOT exercised here."""

import asyncio
import io
import os
import signal
import struct
import sys
import tarfile

import httpx
import pytest
from test_account_browser_network import network
from test_account_browser_profiles import vault
from test_account_browser_writes import make_ledger
from test_web_retrieval import Bytes

from dsgpt.account_browser_bridge import BOOT, AccountBrowserBridge, AccountBrowserBridgeError
from dsgpt.account_browser_wire import MAX_FRAME, BrowserWireError, pack, receive


@pytest.mark.parametrize("data", [b"", b"\x00\x00", struct.pack("!I", MAX_FRAME + 1),
                                  struct.pack("!I", 0), struct.pack("!I", 5) + b"{}"])
def test_wire_rejects_truncated_and_oversized_input(data):
    with pytest.raises(BrowserWireError):
        receive(io.BytesIO(data))


def test_wire_handles_short_reads_without_unbounded_reads():
    class Short(io.BytesIO):
        def read(self, count=-1):
            assert count > 0
            return super().read(min(count, 3))

    assert receive(Short(pack({"sample": "value"}))) == {"sample": "value"}


class FixtureSandbox:
    """Use real pipes and Chromium, explicitly replace container isolation."""

    def __init__(self, root):
        self.root = root
        self.cleaned = 0
        self.sources = None
        self.spawned = False
        self.process = None

    async def create(self, identifier):
        self.identifier = identifier
        return "fixture-private-container"

    async def checked(self, args, *, data):
        assert args == ["container", "exec", "-i", "--", "fixture-private-container",
                        "tar", "-xf", "-", "-C", "/work"]
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            self.sources = {m.name: archive.extractfile(m).read() for m in archive}
        assert all(n.startswith("account-driver/dsgpt/") for n in self.sources)
        assert all(b"cookie-sentinel" not in source for source in self.sources.values())
        for name, data in self.sources.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

    async def inspect(self, name):
        assert name == "fixture-private-container"
        return {"HostConfig": {"LogConfig": {"Type": "none"}}}

    def validate_container(self, value, identifier):
        assert identifier == self.identifier

    async def _spawn(self, args, *, input_pipe, private):
        assert input_pipe and private
        assert args == ["container", "exec", "-i", "--", "fixture-private-container",
                        "python3", "-I", "-c", BOOT]
        self.spawned = True
        # -S demonstrates the shipped guest modules require no host packages.
        source = self.root / "account-driver"
        code = f"""
import sys
sys.path.insert(0, {str(source)!r})
from dsgpt import account_browser_worker as w
w._container_only = lambda: None
from dsgpt import account_browser_guest as g
g.PrivateChromium = lambda root, files: w.PrivateChromium(
    {str(self.root / 'profile')!r}, files, binary={os.environ['DSGPT_PROFILE_TEST_CHROMIUM']!r})
g.main()
"""
        self.process = await asyncio.create_subprocess_exec(
            sys.executable, "-I", "-S", "-c", code,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
        return self.process

    async def cleanup(self, identifier):
        assert identifier == getattr(self, "identifier", identifier)
        self.cleaned += 1
        if self.process is not None:
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


needs_browser = pytest.mark.skipif(
    sys.platform != "linux" or not os.environ.get("DSGPT_PROFILE_TEST_CHROMIUM"),
    reason="needs Linux Chromium fixture",
)


@needs_browser
async def test_real_private_pipe_brokers_cookie_restart_and_denies_unapproved_write(
    tmp_path, caplog,
):
    ledger = make_ledger(tmp_path / "store")
    profile = vault(ledger)
    seen = []
    html = b"""<!doctype html><title>Private bridge fixture</title>
<p>Signed-in fixture</p><script>
(async () => {
 const d = await new Promise(resolve => {
  const r=indexedDB.open('fixture',1);
  r.onupgradeneeded=()=>r.result.createObjectStore('state');
  r.onsuccess=()=>resolve(r.result);
 });
 if(location.pathname==='/login') {
  localStorage.setItem('fixture','local-sentinel');
  await new Promise(resolve=>{
   const t=d.transaction('state','readwrite');
   t.objectStore('state').put('indexed-sentinel','proof'); t.oncomplete=resolve;
  });
 }
 const value=await new Promise(resolve=>{
  const r=d.transaction('state').objectStore('state').get('proof');
  r.onsuccess=()=>resolve(r.result);
 });
 await fetch('/proof?local='+localStorage.getItem('fixture')+'&db='+value+
             '&hidden='+(document.cookie.indexOf('cookie-sentinel')===-1));
 await fetch('https://denied.test/exfil').catch(()=>fetch('/cross-origin-denied'));
 await fetch('/write',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},
                body:'value=unapproved'}).catch(()=>fetch('/write-denied'));
})();</script>"""

    async def respond(request):
        seen.append((request.url.path, dict(request.headers), str(request.url)))
        assert request.method == "GET"
        if request.url.path in {"/cross-origin-denied", "/write-denied"}:
            return httpx.Response(200, stream=Bytes(b"denial confirmed"))
        if request.url.path == "/proof":
            assert request.headers["cookie"] == "fixture=cookie-sentinel"
            assert dict(request.url.params) == {"local": "local-sentinel", "db": "indexed-sentinel",
                                          "hidden": "true"}
            return httpx.Response(200, stream=Bytes(b"checked"))
        assert request.url.path in {"/login", "/restore", "/favicon.ico"}
        headers = [("content-type", "text/html")]
        if request.url.path == "/login":
            headers.append(("set-cookie", "fixture=cookie-sentinel; Max-Age=600; Secure; HttpOnly"))
        return httpx.Response(200, headers=headers, stream=Bytes(html))

    for number, path in enumerate(("/login", "/restore")):
        root = tmp_path / str(number)
        root.mkdir()
        box = FixtureSandbox(root)
        bridge = AccountBrowserBridge(box, profile, network(respond), lambda: None)
        try:
            await bridge.start()
            await bridge.navigate("https://example.org" + path)
            async with asyncio.timeout(8):
                while sum(p == "/write-denied" for p, _, _ in seen) < number + 1:
                    assert (await bridge.frame()).startswith(b"\x89PNG")
                    await asyncio.sleep(0.05)
            assert await bridge.close() == number + 1
        finally:
            await bridge.abort()
        assert box.cleaned > 0
    assert {p for p, _, _ in seen} <= {
        "/login", "/restore", "/proof", "/favicon.ico", "/cross-origin-denied", "/write-denied",
    }
    assert sum(p == "/cross-origin-denied" for p, _, _ in seen) == 2
    assert sum(p == "/proof" for p, _, _ in seen) == 2
    assert all(sentinel not in caplog.text for sentinel in (
        "cookie-sentinel", "local-sentinel", "indexed-sentinel",
    ))
    for path in (tmp_path / "store").glob("*.db*"):
        assert b"cookie-sentinel" not in path.read_bytes()


@needs_browser
async def test_revocation_and_invalid_command_abort_without_saving(tmp_path):
    profile = vault(make_ledger(tmp_path / "store"))
    allowed = [True]

    def authorize():
        if not allowed[0]:
            raise ValueError("credential-sentinel")

    async def respond(request):
        return httpx.Response(200, stream=Bytes(b"safe"))

    for op in ("revoked", "raw_cdp"):
        root = tmp_path / op
        root.mkdir()
        box = FixtureSandbox(root)
        bridge = AccountBrowserBridge(box, profile, network(respond), authorize)
        await bridge.start()
        if op == "revoked":
            allowed[0] = False
        try:
            with pytest.raises(AccountBrowserBridgeError) as error:
                await bridge._exchange({"op": "Runtime.evaluate", "expression": "document.cookie"})
            assert "credential-sentinel" not in str(error.value)
            assert bridge.process is None
            assert profile.restore() == (0, None)
        finally:
            allowed[0] = True
            await bridge.abort()


async def test_logging_enabled_container_is_rejected_before_profile_transmission(tmp_path):
    profile = vault(make_ledger(tmp_path / "store"))
    box = FixtureSandbox(tmp_path)

    async def inspect(_):
        return {"HostConfig": {"LogConfig": {"Type": "json-file"}}}

    box.inspect = inspect
    bridge = AccountBrowserBridge(box, profile, network(None), lambda: None)
    with pytest.raises(AccountBrowserBridgeError, match="start_failed"):
        await bridge.start()
    assert not box.spawned and box.cleaned > 0


async def test_profile_from_different_origin_never_reaches_guest(tmp_path):
    profile = vault(make_ledger(tmp_path / "store"))
    broker = network(None)
    broker.origin = "https://other.example.org"
    box = FixtureSandbox(tmp_path)
    bridge = AccountBrowserBridge(box, profile, broker, lambda: None)
    with pytest.raises(AccountBrowserBridgeError, match="start_failed"):
        await bridge.start()
    assert not box.spawned and box.sources is None


@needs_browser
@pytest.mark.parametrize("failure", ["cancel", "revoke", "guest_exit"])
async def test_inflight_failure_discards_response_and_preserves_vault(tmp_path, failure):
    profile = vault(make_ledger(tmp_path / "store"))
    allowed = [True]
    started = asyncio.Event()
    release = asyncio.Event()

    def authorize():
        if not allowed[0]:
            raise ValueError("private authority detail")

    async def respond(request):
        started.set()
        await release.wait()
        return httpx.Response(200, stream=Bytes(b"private response sentinel"))

    box = FixtureSandbox(tmp_path)
    bridge = AccountBrowserBridge(box, profile, network(respond), authorize)
    task = None
    try:
        await bridge.start()
        task = asyncio.create_task(bridge.navigate("https://example.org/private"))
        async with asyncio.timeout(5):
            await started.wait()
        with pytest.raises(AccountBrowserBridgeError, match="busy"):
            await bridge.frame()
        if failure == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            if failure == "revoke":
                allowed[0] = False
            else:
                bridge.process.kill()
                await bridge.process.wait()
            release.set()
            with pytest.raises(AccountBrowserBridgeError) as error:
                await task
            assert "private" not in str(error.value)
        assert bridge.process is None and box.cleaned > 0
        assert profile.restore() == (0, None)
    finally:
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await bridge.abort()
