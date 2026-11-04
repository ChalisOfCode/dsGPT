"""Publication/packaging failures must not produce a wrong-key phone update."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


signing = module("verify_android_release")
storage = module("ci_artifact_guard")


@pytest.mark.parametrize("fingerprints", [[], ["b" * 64], ["a" * 64, "b" * 64]])
def test_missing_replaced_or_extra_signer_is_rejected(fingerprints):
    signature = "\n".join(
        f"Signer #{i + 1} certificate SHA-256 digest: {s}" for i, s in enumerate(fingerprints)
    )
    with pytest.raises(ValueError, match="signing certificate"):
        signing.validate_output(
            signature,
            "package: name='com.dsgpt.mobile' versionCode='24'",
            {"certificate_sha256": "a" * 64, "application_id": "com.dsgpt.mobile"},
        )


def test_test_package_and_downgrade_cannot_be_production_updates():
    signature = "Signer #1 certificate SHA-256 digest: " + "a" * 64
    policy = {"certificate_sha256": "a" * 64, "application_id": "com.dsgpt.mobile"}
    for package, version in [("com.dsgpt.mobile.acceptance", 24), ("com.dsgpt.mobile", 22)]:
        with pytest.raises(ValueError):
            signing.validate_output(
                signature, f"package: name='{package}' versionCode='{version}'", policy
            )
    assert (
        signing.validate_output(
            signature, "package: name='com.dsgpt.mobile' versionCode='24'", policy
        )["version_code"]
        == 24
    )


def test_artifact_inventory_counts_every_page_and_ignores_expired():
    pages = [
        {"artifacts": [{"expired": False, "size_in_bytes": 100 * 1024**2}]},
        {
            "artifacts": [
                {"expired": False, "size_in_bytes": 180 * 1024**2},
                {"expired": True, "size_in_bytes": 999 * 1024**2},
            ]
        },
    ]
    assert storage.check_inventory(pages, 1024) == 280 * 1024**2
    with pytest.raises(ValueError, match="allowance"):
        storage.check_inventory(pages, 21 * 1024**2)


def test_artifact_selection_rejects_signing_material_and_symlinks(tmp_path):
    (tmp_path / "test.txt").write_text("reviewed fixture")
    assert storage.payload_size([tmp_path]) == 16
    (tmp_path / "identity.keystore").write_bytes(b"private test sentinel")
    with pytest.raises(ValueError, match="Private signing"):
        storage.payload_size([tmp_path])
    (tmp_path / "identity.keystore").unlink()
    try:
        (tmp_path / "linked.txt").symlink_to(tmp_path / "test.txt")
    except OSError:
        pytest.skip("This environment cannot create symlinks")
    with pytest.raises(ValueError, match="symlinks"):
        storage.payload_size([tmp_path])


@pytest.mark.parametrize("change", ["content", "extra", "missing", "source"])
def test_consumer_rejects_replaced_or_wrong_source_outputs(tmp_path, change):
    script = ROOT / "scripts/ci_provenance.py"
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"original compiled output")
    commit = "a" * 40
    subprocess.run([sys.executable, str(script), "write", str(tmp_path), commit], check=True)
    subprocess.run([sys.executable, str(script), "verify", str(tmp_path), commit], check=True)
    if change == "content":
        payload.write_bytes(b"different compiled output")
    elif change == "extra":
        (tmp_path / "unreviewed.bin").write_bytes(b"extra")
    elif change == "missing":
        payload.unlink()
    else:
        commit = "b" * 40
    result = subprocess.run(
        [sys.executable, str(script), "verify", str(tmp_path), commit],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0


@pytest.mark.parametrize("receipt", [None, "stale", "different-key"])
def test_release_packaging_rejects_bad_android_receipt_before_creating_payload(tmp_path, receipt):
    apk = tmp_path / "phone.apk"
    apk.write_bytes(b"unverified APK fixture")
    output = tmp_path / "production-output"
    command = [
        sys.executable,
        str(ROOT / "scripts/build_application.py"),
        "--kit",
        str(tmp_path / "not-read-before-signature-check"),
        "--android",
        str(apk),
        "--output",
        str(output),
    ]
    if receipt is not None:
        import hashlib

        policy = json.loads((ROOT / "config/android-signing.json").read_text())
        value = {
            "signature_verified": True,
            "apk_sha256": hashlib.sha256(apk.read_bytes()).hexdigest(),
            "application_id": policy["application_id"],
            "certificate_sha256": policy["certificate_sha256"],
        }
        value["apk_sha256" if receipt == "stale" else "certificate_sha256"] = "b" * 64
        path = tmp_path / "receipt.json"
        path.write_text(json.dumps(value))
        command.extend(["--android-signature", str(path)])
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode != 0
    assert "signing" in result.stderr
    assert not output.exists()
