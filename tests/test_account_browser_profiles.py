import os
import sqlite3
import subprocess
import sys

import pytest
from test_account_browser_writes import make_ledger
from test_account_sessions import FixtureProtection

from dsgpt.account_browser_profiles import AccountBrowserProfiles, AccountProfileError, validate
from dsgpt.storage import Store, uid

FILES = {
    "Default/Network/Cookies": b"cookie-sentinel",
    "Default/Local Storage/leveldb/000003.log": b"local-storage-sentinel",
    "Default/IndexedDB/https_example.org_0.indexeddb.leveldb/000003.log": b"indexed-db-sentinel",
}


def vault(ledger, protection=None):
    return AccountBrowserProfiles(
        ledger.store,
        ledger.session_id,
        ledger.owner_id,
        protection if protection is not None else FixtureProtection(),
    )


def test_restart_revision_binding_and_revoke(tmp_path):
    ledger = make_ledger(tmp_path)
    profile = vault(ledger)
    assert profile.restore() == (0, None)
    assert profile.save(FILES, expected_revision=0) == 1
    profile.store = Store(tmp_path)
    assert profile.restore() == (1, FILES)
    with pytest.raises(AccountProfileError, match="revision_conflict"):
        profile.save({"Local State": b"stale"}, expected_revision=0)
    assert profile.restore() == (1, FILES)
    other = AccountBrowserProfiles(profile.store, ledger.session_id, uid(), FixtureProtection())
    with pytest.raises(AccountProfileError, match="scope_denied"):
        other.restore()
    with profile.store.transaction() as db:
        db.execute("UPDATE account_browser_profiles SET revision=2")
    with pytest.raises(AccountProfileError, match="restore_failed"):
        profile.restore()
    with profile.store.transaction() as db:
        db.execute("DELETE FROM account_sessions WHERE id=?", (ledger.session_id,))
    assert profile.store.all("SELECT * FROM account_browser_profiles") == []
    with pytest.raises(AccountProfileError, match="scope_denied"):
        profile.save(FILES, expected_revision=0)
    for path in tmp_path.glob("*.db*"):
        for secret in FILES.values():
            assert secret not in path.read_bytes()


@pytest.mark.parametrize(
    "path", ["../escape", "/root", "a/../b", "a//b", "a\\b", "C:/x", "a/", "SingletonLock", "a\n"]
)
def test_invalid_profile_paths_are_rejected(path):
    with pytest.raises(AccountProfileError, match="invalid"):
        validate({path: b"x"})


def test_bounds_and_parent_collision():
    for files in [
        {},
        {"a": b"x", "a/b": b"y"},
        {"a": "not bytes"},
        {str(i): b"" for i in range(513)},
        {"a": bytes(8 * 1024**2 + 1)},
    ]:
        with pytest.raises(AccountProfileError):
            validate(files)


def test_protection_failure_preserves_previous_snapshot(tmp_path, monkeypatch):
    profile = vault(make_ledger(tmp_path))
    profile.save(FILES, expected_revision=0)

    def fail(*args):
        raise OSError("credential-sentinel")

    monkeypatch.setattr(profile.protection, "seal", fail)
    with pytest.raises(AccountProfileError, match="protection_failed") as error:
        profile.save({"Local State": b"replacement"}, expected_revision=1)
    assert "credential-sentinel" not in str(error.value)
    assert profile.restore() == (1, FILES)


def test_v28_migration_preserves_sessions_and_receipts(tmp_path):
    ledger = make_ledger(tmp_path)
    ledger.begin(uid(), origin="https://example.org")
    before = ledger.pending()
    with sqlite3.connect(ledger.store.path) as db:
        db.execute("DROP TABLE account_browser_profiles")
        db.execute("PRAGMA user_version=28")
    ledger.store = Store(tmp_path)
    assert ledger.pending() == before
    assert vault(ledger).restore() == (0, None)
    assert len(list(tmp_path.glob("before-v28-to-v29-*.db"))) == 1


@pytest.mark.skipif(os.name != "nt", reason="Native current-user Windows protection")
def test_native_profile_protection_restart_and_tampering(tmp_path):
    from dsgpt.account_sessions import WindowsSessionProtection

    ledger = make_ledger(tmp_path)
    profile = vault(ledger, WindowsSessionProtection())
    profile.save(FILES, expected_revision=0)
    script = """
import sys
from dsgpt.storage import Store
from dsgpt.account_browser_profiles import AccountBrowserProfiles
p=AccountBrowserProfiles(Store(sys.argv[1]),sys.argv[2],sys.argv[3])
revision,files=p.restore()
assert revision==1 and len(files)==3 and files['Default/Network/Cookies']==b'cookie-sentinel'
"""
    subprocess.run(
        [sys.executable, "-c", script, str(tmp_path), ledger.session_id, ledger.owner_id],
        check=True,
        timeout=15,
        capture_output=True,
    )
    with profile.store.transaction() as db:
        sealed = bytearray(
            db.execute("SELECT sealed_profile FROM account_browser_profiles").fetchone()[0]
        )
        sealed[-1] ^= 1
        db.execute("UPDATE account_browser_profiles SET sealed_profile=?", (bytes(sealed),))
    with pytest.raises(AccountProfileError, match="restore_failed"):
        profile.restore()


@pytest.mark.skipif(os.name == "nt", reason="Unavailable protection on non-Windows")
def test_no_plaintext_fallback_when_windows_protection_unavailable(tmp_path):
    ledger = make_ledger(tmp_path)
    profile = AccountBrowserProfiles(ledger.store, ledger.session_id, ledger.owner_id)
    with pytest.raises(AccountProfileError, match="protection_failed"):
        profile.save(FILES, expected_revision=0)
    assert ledger.store.all("SELECT * FROM account_browser_profiles") == []
