"""Synthetic signing-format checks, never production signing/upgrade acceptance."""

import hashlib
import importlib.util
import io
import os
import subprocess
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

x509 = pytest.importorskip("cryptography.x509")
hashes = pytest.importorskip("cryptography.hazmat.primitives.hashes")
serialization = pytest.importorskip("cryptography.hazmat.primitives.serialization")
rsa = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.rsa")

spec = importlib.util.spec_from_file_location(
    "apk_v2", Path(__file__).resolve().parents[1] / "scripts/sign_apk_v2.py"
)
v2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v2)


@pytest.fixture(scope="module")
def fixture():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, "Synthetic signing check")])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(1)
            .not_valid_before(datetime(2025, 1, 1, tzinfo=UTC))
            .not_valid_after(datetime(2025, 1, 1, tzinfo=UTC) + timedelta(days=3650))
            .sign(key, hashes.SHA256()).public_bytes(serialization.Encoding.DER))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("AndroidManifest.xml", b"Synthetic; SDK test supplies minSdk explicitly")
        archive.writestr("assets/chunks.bin", b"fixture-data\0" * 170000)
    data = out.getvalue()
    pins = {"input_sha256": hashlib.sha256(data).hexdigest(),
            "certificate_sha256": hashlib.sha256(cert).hexdigest()}
    return data, key, cert, pins


def test_signing_preserves_every_zip_entry_and_is_deterministic(fixture):
    data, key, cert, pins = fixture
    signed = v2.sign(data, key, cert, **pins)
    assert signed == v2.sign(data, key, cert, **pins)
    with zipfile.ZipFile(io.BytesIO(data)) as before, zipfile.ZipFile(io.BytesIO(signed)) as after:
        assert before.namelist() == after.namelist()
        assert all(before.read(n) == after.read(n) for n in before.namelist())
    with pytest.raises(ValueError, match="already has an APK"):
        v2.sign(signed, key, cert, **dict(pins, input_sha256=hashlib.sha256(signed).hexdigest()))


@pytest.mark.parametrize("pin", ["input_sha256", "certificate_sha256"])
def test_pins_fail_before_signing(fixture, pin):
    data, key, cert, pins = fixture
    with pytest.raises(ValueError, match="mismatch"):
        v2.sign(data, key, cert, **dict(pins, **{pin: "0" * 64}))


def test_mismatched_key_and_certificate_are_rejected(fixture):
    data, _, cert, pins = fixture
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(ValueError, match="key differ"):
        v2.sign(data, other, cert, **pins)


def test_existing_jar_signature_is_not_silently_resigned(fixture):
    data, key, cert, pins = fixture
    out = io.BytesIO(data)
    with zipfile.ZipFile(out, "a") as archive:
        archive.writestr("META-INF/OLD.SF", b"existing")
    changed = out.getvalue()
    with pytest.raises(ValueError, match="JAR signatures"):
        v2.sign(changed, key, cert,
                **dict(pins, input_sha256=hashlib.sha256(changed).hexdigest()))


def test_trailing_data_is_rejected(fixture):
    data, key, cert, pins = fixture
    changed = data + b"unexpected"
    with pytest.raises(ValueError, match="ZIP layout"):
        v2.sign(changed, key, cert,
                **dict(pins, input_sha256=hashlib.sha256(changed).hexdigest()))


@pytest.mark.skipif(not os.environ.get("DSGPT_APKSIGNER_JAR"), reason="Android SDK opt-in")
def test_independent_android_sdk_verifies_v2_and_rejects_tampering(fixture, tmp_path):
    data, key, cert, pins = fixture
    signed = v2.sign(data, key, cert, **pins)
    path = tmp_path / "synthetic.apk"
    path.write_bytes(signed)
    command = ["java", "-jar", os.environ["DSGPT_APKSIGNER_JAR"], "verify", "--verbose",
               "--print-certs", "--min-sdk-version", "26", str(path)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, "Independent SDK verifier rejected the signing format"
    assert "Verified using v2 scheme (APK Signature Scheme v2): true" in result.stdout
    assert pins["certificate_sha256"] in result.stdout
    # Mutate actual data before the signing block without rebuilding ZIP metadata.
    altered = bytearray(signed)
    altered[altered.index(b"fixture-data")] ^= 1
    path.write_bytes(altered)
    rejected = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert rejected.returncode != 0, "Independent SDK verifier accepted altered content"
