"""Deterministic startup/close races at the private controller boundary."""

import asyncio

import pytest
from test_account_browser_bridge import FixtureSandbox
from test_account_browser_network import network
from test_account_browser_profiles import vault
from test_account_browser_writes import make_ledger

from dsgpt.account_browser_bridge import AccountBrowserBridge, AccountBrowserBridgeError


@pytest.mark.parametrize("phase", ["create", "install", "spawn"])
async def test_abort_waits_for_pending_start_and_never_restores_after_abort(tmp_path, phase):
    entered = asyncio.Event()
    box = FixtureSandbox(tmp_path)
    original_create = box.create

    async def blocked(*args, **kwargs):
        entered.set()
        await asyncio.Future()

    async def create(identifier):
        name = await original_create(identifier)
        await blocked()
        return name

    if phase == "create":
        box.create = create
    elif phase == "install":
        box.checked = blocked
    else:
        box._spawn = blocked
    profile = vault(make_ledger(tmp_path / "store"))
    bridge = AccountBrowserBridge(box, profile, network(None), lambda: None)
    task = asyncio.create_task(bridge.start())
    try:
        async with asyncio.timeout(2):
            await entered.wait()
            await bridge.abort()
        assert task.cancelled()
        assert bridge.process is None and box.cleaned > 0
        assert profile.restore() == (0, None)
        with pytest.raises(AccountBrowserBridgeError, match="already_started"):
            await bridge.start()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_close_during_active_operation_does_not_abort_that_operation(tmp_path):
    box = FixtureSandbox(tmp_path)
    bridge = AccountBrowserBridge(box, vault(make_ledger(tmp_path / "store")),
                                  network(None), lambda: None)
    async with bridge.lock:
        with pytest.raises(AccountBrowserBridgeError, match="busy"):
            await bridge.close()
    assert not bridge.stopped and not bridge.closing and box.cleaned == 0


async def test_abort_before_start_permanently_closes_instance(tmp_path):
    box = FixtureSandbox(tmp_path)
    bridge = AccountBrowserBridge(box, vault(make_ledger(tmp_path / "store")),
                                  network(None), lambda: None)
    await bridge.abort()
    with pytest.raises(AccountBrowserBridgeError, match="already_started"):
        await bridge.start()
    assert box.sources is None
