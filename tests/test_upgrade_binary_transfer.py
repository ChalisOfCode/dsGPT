"""Small synthetic envelopes; no production binaries or signing keys."""
import hashlib
import importlib.util
import time
from pathlib import Path

import pytest

pytest.importorskip("cryptography")
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

spec = importlib.util.spec_from_file_location(
    "transfer", Path(__file__).resolve().parents[1] / "scripts/upgrade_binary_transfer.py")
transfer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transfer)


@pytest.fixture
def envelope(monkeypatch):
    files = {"baseline.apk": b"old synthetic binary", "candidate.apk": b"new synthetic binary"}
    monkeypatch.setattr(transfer, "FILES", {
        name: (len(data), hashlib.sha256(data).hexdigest()) for name, data in files.items()})
    private = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    challenge = {"format": 1, "run": "42", "source": "a" * 40,
                 "expires": int(time.time()) + 100,
                 "public_key": private.public_key().public_bytes(
                     serialization.Encoding.PEM,
                     serialization.PublicFormat.SubjectPublicKeyInfo).decode()}
    sealed = transfer.seal(challenge, files, "42", "a" * 40)
    return private, challenge, files, sealed


def test_exact_pair_only_and_no_plaintext(envelope):
    private, challenge, files, sealed = envelope
    assert all(value not in sealed for value in files.values())
    assert transfer.unseal(sealed, challenge, private, "42", "a" * 40) == files
    for other in ({**files, "private-key": b"forbidden"}, {**files, "candidate.apk": b"changed"}):
        with pytest.raises(ValueError):
            transfer.seal(challenge, other, "42", "a" * 40)


def test_authentication_and_exact_run_source_binding(envelope):
    private, challenge, _, sealed = envelope
    with pytest.raises(InvalidTag):
        transfer.unseal(sealed[:-1] + bytes([sealed[-1] ^ 1]), challenge, private, "42", "a" * 40)
    for run, source in (("43", "a" * 40), ("42", "b" * 40)):
        with pytest.raises(ValueError):
            transfer.unseal(sealed, challenge, private, run, source)
    with pytest.raises(ValueError):
        transfer.unseal(sealed, {**challenge, "expires": 1}, private, "42", "a" * 40)
    other = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    with pytest.raises(ValueError):
        transfer.unseal(sealed, challenge, other, "42", "a" * 40)


def test_bounds_and_receiver_path(envelope, monkeypatch, tmp_path):
    private, challenge, _, _ = envelope
    for malformed in (b"short", b"\xff" * 100, b"x" * (transfer.MAX_ENVELOPE + 1)):
        with pytest.raises(ValueError):
            transfer.unseal(malformed, challenge, private, "42", "a" * 40)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    with pytest.raises(RuntimeError):
        transfer.runner_directory(tmp_path)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REPOSITORY", "ChalisOfCode/dsGPT")
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    with pytest.raises(ValueError):
        transfer.runner_directory(tmp_path)
    with pytest.raises(ValueError):
        transfer.runner_directory(tmp_path.parent)
    transfer.runner_directory(tmp_path / "private")


def test_partitioned_transfer_is_bounded_and_hash_checked(monkeypatch):
    import io
    import json
    data = b"ciphertext" * 50000
    manifest = {"format": 1, "bytes": len(data), "parts": 2,
                "sha256": hashlib.sha256(data).hexdigest()}
    replies = {"manifest.json": json.dumps(manifest).encode(),
               "part-000.bin": data[:393216], "part-001.bin": data[393216:]}
    monkeypatch.setattr(transfer.urllib.request, "urlopen",
                        lambda url, timeout: io.BytesIO(replies[url.rsplit("/", 1)[1]]))
    assert transfer.fetch_envelope("https://example.test/fixed") == data
    replies["part-001.bin"] = b"wrong"
    with pytest.raises(ValueError, match="Incomplete"):
        transfer.fetch_envelope("https://example.test/fixed")
    replies["manifest.json"] = json.dumps({**manifest, "parts": 10000}).encode()
    with pytest.raises(ValueError, match="Invalid transfer manifest"):
        transfer.fetch_envelope("https://example.test/fixed")
