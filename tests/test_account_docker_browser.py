"""Opt-in unchanged DockerSandbox/guest checks using the exact production image.

The login scenario still uses a controlled TLS endpoint mapping and test vault.
The second case joins the real Docker guest to the unchanged public DNS/TLS path.
Neither case claims native Windows DPAPI or universal website compatibility.
"""

import hashlib
import json
import os

import pytest
from test_account_browser_profiles import vault
from test_account_browser_writes import make_ledger
from test_account_https_browser import run_browser_tls_scenario

from dsgpt.account_browser_bridge import AccountBrowserBridge
from dsgpt.account_browser_network import AccountBrowserNetwork
from dsgpt.sandbox import DockerSandbox
from dsgpt.tool_setup import recipe_digest

pytestmark = pytest.mark.skipif(
    not os.environ.get("DSGPT_ACCOUNT_DOCKER_IMAGE"), reason="explicit production Docker check",
)


@pytest.fixture
async def docker_factory(tmp_path):
    image = os.environ["DSGPT_ACCOUNT_DOCKER_IMAGE"]
    owner = os.urandom(16).hex()

    def factory(root):
        sandbox = DockerSandbox(root, image, owner)
        return sandbox

    preflight = factory(tmp_path)
    metadata = json.loads(await preflight.checked(["image", "inspect", image]))[0]
    assert metadata["Id"] == image
    assert metadata["Config"]["Labels"]["org.dsgpt.recipe"] == recipe_digest()
    assert metadata["Config"]["Labels"]["org.dsgpt.purpose"] == "offline-isolated-build"
    assert not metadata["Config"].get("Volumes")
    yield factory
    # Abort/close must leave no containers behind, including on scenario failure.
    remaining = await preflight.checked([
        "container", "ls", "--all", "--filter", "label=org.dsgpt.owner=" + owner,
        "--format", "{{.Names}}",
    ])
    assert not remaining.strip(), "owned account containers remained after cleanup"


async def test_production_docker_login_restore_and_interrupted_write(tmp_path, caplog,
                                                                   docker_factory):
    await run_browser_tls_scenario(tmp_path, caplog, docker_factory)


async def test_production_docker_guest_public_https_and_revocation(tmp_path, docker_factory):
    origin = "https://raw.githubusercontent.com"
    path = "/ChalisOfCode/dsGPT/4b87ed1557484e9d92e33442f4378fb78fdbd928/REQUIREMENTS.md"
    expected = "e9663679a315c30d2d00b3a56e9d59e0d6200026877e25fc0c9deee8fc00fe1e"
    ledger = make_ledger(tmp_path / "store")
    with ledger.store.transaction() as db:
        db.execute("UPDATE account_sessions SET origin=? WHERE id=?", (origin, ledger.session_id))
    active = True
    seen = []

    def authorize():
        if not active:
            raise RuntimeError("revoked")

    class ObservedNetwork(AccountBrowserNetwork):
        async def fetch(self, url, method, headers, body=b""):
            response = await super().fetch(url, method, headers, body)
            # Fixed facts only, never retain the body, headers or screenshot.
            seen.append((response.status, hashlib.sha256(response.body).hexdigest()))
            return response

    network = ObservedNetwork(origin, authorize=authorize)
    browser = AccountBrowserBridge(docker_factory(tmp_path), vault(ledger), network, authorize)
    try:
        await browser.start()
        info = await browser.sandbox.inspect(browser.sandbox.name(browser.identifier))
        browser.sandbox.validate_container(info, browser.identifier)
        assert info["HostConfig"]["LogConfig"]["Type"] == "none"
        await browser.navigate(origin + path)
        assert (200, expected) in seen
        assert (await browser.frame()).startswith(b"\x89PNG")
        before = network._requests
        active = False
        with pytest.raises(Exception, match="account_browser_operation_failed"):
            await browser.frame()
        assert network._requests == before
        assert browser.stopped and browser.process is None
    finally:
        await browser.abort()
