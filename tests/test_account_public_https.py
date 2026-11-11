"""Opt-in live production transport check; public bytes only, no account secrets."""

import hashlib
import os

import pytest

from dsgpt.account_browser_network import AccountBrowserNetwork


@pytest.mark.skipif(os.environ.get("DSGPT_PUBLIC_HTTPS_CHECK") != "1",
                    reason="explicit live public transport check")
async def test_account_broker_real_public_dns_tls_and_pinned_bytes():
    origin = "https://raw.githubusercontent.com"
    path = "/ChalisOfCode/dsGPT/4b87ed1557484e9d92e33442f4378fb78fdbd928/REQUIREMENTS.md"
    checks = []
    net = AccountBrowserNetwork(origin, authorize=lambda: checks.append(True))
    # Use the production default PublicHTTPS transport: no resolver, TLS trust,
    # endpoint, network or response substitution and no inherited proxy client.
    response = await net.fetch(origin + path, "GET", {})
    assert response.status == 200
    assert hashlib.sha256(response.body).hexdigest() == (
        "e9663679a315c30d2d00b3a56e9d59e0d6200026877e25fc0c9deee8fc00fe1e"
    )
    assert any(k == "content-type" and v.startswith("text/plain")
               for k, v in response.headers)
    assert len(checks) >= 3  # entry, dispatch validation, release
    assert net._requests == 1 and net._total == len(response.body)
