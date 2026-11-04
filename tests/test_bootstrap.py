import json

import pytest

from dsgpt.bootstrap import credential_target, ensure_owner
from dsgpt.security import Auth
from dsgpt.storage import Store


class Vault:
    def __init__(self):
        self.value = None
        self.fail = False

    def read(self):
        return self.value

    def write(self, value):
        if self.fail:
            raise OSError("synthetic vault unavailable")
        self.value = dict(value)


def test_bootstrap_is_repeatable_and_never_exposes_plaintext_token(tmp_path):
    store, vault = Store(tmp_path), Vault()
    first = ensure_owner(store, vault)
    second = ensure_owner(store, vault)
    assert first["created"] and not second["created"]
    assert first["device_id"] == second["device_id"]
    assert vault.value["token"] not in json.dumps(first)
    assert vault.value["token"] not in json.dumps(store.all("SELECT * FROM devices"))
    assert Auth(store).authenticate("Bearer " + vault.value["token"])["role"] == "owner"


def test_failed_vault_save_leaves_owner_uninitialized(tmp_path):
    store, vault = Store(tmp_path), Vault()
    vault.fail = True
    with pytest.raises(OSError):
        ensure_owner(store, vault)
    assert store.all("SELECT * FROM devices") == []


def test_bootstrap_recovers_staged_vault_after_database_transaction_failure(tmp_path):
    store, vault = Store(tmp_path), Vault()
    with store.transaction() as db:
        db.execute(
            "CREATE TRIGGER simulated_failure BEFORE INSERT ON devices BEGIN "
            "SELECT RAISE(ABORT,'synthetic interrupted transaction'); END;"
        )
    with pytest.raises(Exception, match="synthetic interrupted"):
        ensure_owner(store, vault)
    staged = dict(vault.value)
    assert staged and not store.all("SELECT * FROM devices")
    with store.transaction() as db:
        db.execute("DROP TRIGGER simulated_failure")
    assert ensure_owner(store, vault)["created"]
    assert vault.value == staged


def test_existing_owner_is_never_replaced_by_bootstrap(tmp_path):
    store, vault = Store(tmp_path), Vault()
    existing = Auth(store).initialize_owner()
    with pytest.raises(ValueError, match="Existing owner preserved"):
        ensure_owner(store, vault)
    assert vault.value is None
    assert Auth(store).authenticate("Bearer " + existing["token"])["id"] == existing["device_id"]


def test_credential_target_is_scoped_to_data_directory(tmp_path):
    assert credential_target(tmp_path / "a") != credential_target(tmp_path / "b")
    assert credential_target(tmp_path / "a") == credential_target(tmp_path / "a" / ".." / "a")


def test_explicit_offline_recovery_revokes_old_access_without_exposing_replacement(tmp_path):
    from fastapi import HTTPException

    from dsgpt.bootstrap import recover_owner

    store, vault = Store(tmp_path), Vault()
    ensure_owner(store, vault)
    old = dict(vault.value)
    auth = Auth(store)
    pair = auth.create_pairing(["chat"])
    phone = auth.redeem(pair["code"], "Phone")
    unused = auth.create_pairing(["chat"])
    with pytest.raises(ValueError, match="explicit confirmation"):
        recover_owner(tmp_path, vault)
    assert vault.value == old
    result = recover_owner(tmp_path, vault, confirm_revoke_devices=True)
    assert result == {"device_id": old["device_id"], "recovered": True, "revoked_devices": 1}
    assert vault.value["token"] not in json.dumps(result)
    for token in (old["token"], phone["token"]):
        with pytest.raises(HTTPException):
            auth.authenticate("Bearer " + token)
    with pytest.raises(HTTPException):
        auth.redeem(unused["code"], "Another phone")
    assert auth.authenticate("Bearer " + vault.value["token"])["role"] == "owner"
    assert not ensure_owner(store, vault)["created"]


@pytest.mark.parametrize(
    "name",
    ["backend.lock", "managed-service.lock", "owner-bootstrap.lock", "managed-supervisor.lock"],
)
def test_recovery_refuses_active_instance_before_touching_vault(tmp_path, name):
    from dsgpt.bootstrap import recover_owner
    from dsgpt.storage import InstanceLock

    store, vault = Store(tmp_path), Vault()
    ensure_owner(store, vault)
    old = dict(vault.value)
    lock = InstanceLock(tmp_path, name)
    lock.acquire()
    try:
        with pytest.raises(RuntimeError, match="owns this data directory"):
            recover_owner(tmp_path, vault, confirm_revoke_devices=True)
    finally:
        lock.release()
    assert vault.value == old
    assert Auth(store).authenticate("Bearer " + old["token"])["role"] == "owner"


def test_recovery_vault_failure_preserves_database_and_can_retry(tmp_path):
    from dsgpt.bootstrap import recover_owner

    store, vault = Store(tmp_path), Vault()
    ensure_owner(store, vault)
    old = dict(vault.value)
    vault.fail = True
    with pytest.raises(OSError):
        recover_owner(tmp_path, vault, confirm_revoke_devices=True)
    assert Auth(store).authenticate("Bearer " + old["token"])["role"] == "owner"
    vault.fail = False
    assert recover_owner(tmp_path, vault, confirm_revoke_devices=True)["recovered"]


def test_recovery_database_commit_failure_stays_explicitly_recoverable(tmp_path, monkeypatch):
    from contextlib import contextmanager

    from dsgpt.bootstrap import recover_owner

    store, vault = Store(tmp_path), Vault()
    ensure_owner(store, vault)
    old = dict(vault.value)
    transaction = Store.transaction

    @contextmanager
    def fail_commit(self):
        with transaction(self) as db:
            yield db
            raise RuntimeError("synthetic commit failure")

    with monkeypatch.context() as patch:
        patch.setattr(Store, "transaction", fail_commit)
        with pytest.raises(RuntimeError, match="synthetic commit"):
            recover_owner(tmp_path, vault, confirm_revoke_devices=True)
    assert Auth(store).authenticate("Bearer " + old["token"])["role"] == "owner"
    with pytest.raises(ValueError, match="Existing owner preserved"):
        ensure_owner(store, vault)
    assert recover_owner(tmp_path, vault, confirm_revoke_devices=True)["recovered"]
    assert not ensure_owner(store, vault)["created"]
