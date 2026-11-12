"""Real socket/TLS checks of the controlled site, NOT dsGPT browser acceptance."""

import shutil

import httpx
import pytest
from account_https_site import https_site

pytestmark = pytest.mark.skipif(
    shutil.which("openssl") is None, reason="TLS fixture requires OpenSSL"
)


def login(site, client):
    assert client.get("/private.txt").status_code == 401
    assert client.get("/login").status_code == 200
    response = client.post("/login", data={"csrf": site.csrf, "password": site.password})
    assert response.status_code == 303
    assert client.get("/private.txt").status_code == 401  # password alone is insufficient
    assert client.get("/mfa").status_code == 200
    response = client.post("/mfa", data={"csrf": site.csrf, "code": site.mfa})
    assert response.status_code == 303
    assert "Secure" in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]


def client_for(site, trust):
    return httpx.Client(
        base_url=site.origin,
        verify=trust,
        trust_env=False,
        follow_redirects=False,
        timeout=3,
        headers={"Origin": site.origin},
    )


def test_real_https_login_mfa_cookie_and_independent_effect_counter():
    with https_site() as (site, trust), client_for(site, trust) as client:
        login(site, client)
        assert client.get("/private.txt").text == "Controlled account. Updates: 0"
        assert "indexedDB.open" in client.get("/app").text  # script presence, not execution
        restore = client.get("/restore").text
        assert "readonly" in restore and "setItem" not in restore and ".put(" not in restore
        for count in (1, 2):
            assert (
                client.post("/update", data={"csrf": site.csrf, "value": "change"}).status_code
                == 200
            )
            assert site.effects == count  # duplicate requests are intentionally detectable
        assert client.get("/redirect").status_code == 302
        site.expire()
        assert client.get("/private.txt").status_code == 401


def test_configured_entry_changes_from_login_to_plain_text_and_expires():
    with https_site() as (site, trust), client_for(site, trust) as client:
        response = client.get("/entry")
        assert response.headers["content-type"].startswith("text/html")
        assert 'action="/login"' in response.text
        login(site, client)
        response = client.get("/entry")
        assert response.headers["content-type"].startswith("text/plain")
        assert response.text == "Controlled account. Updates: 0"
        site.expire()
        assert client.get("/entry").headers["content-type"].startswith("text/html")


def test_csrf_origin_and_unauthenticated_writes_cannot_change_server_state():
    with https_site() as (site, trust), client_for(site, trust) as client:
        assert (
            client.post("/update", data={"csrf": site.csrf, "value": "change"}).status_code == 403
        )
        login(site, client)
        for headers, csrf in [({}, "wrong"), ({"Origin": "https://example.invalid"}, site.csrf)]:
            assert (
                client.post(
                    "/update", headers=headers, data={"csrf": csrf, "value": "change"}
                ).status_code
                == 403
            )
        assert site.effects == 0


def test_lost_response_has_one_observable_effect_and_tls_rejects_untrusted_cert():
    with https_site() as (site, trust), client_for(site, trust) as client:
        with httpx.Client(trust_env=False, timeout=3) as untrusted:
            with pytest.raises(httpx.ConnectError):
                untrusted.get(site.origin + "/login")
        login(site, client)
        with pytest.raises(httpx.RemoteProtocolError):
            client.post("/interrupt", data={"csrf": site.csrf, "value": "change"})
        assert site.effects == 1
        assert client.get("/private.txt").text == "Controlled account. Updates: 1"
