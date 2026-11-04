"""Verify the actual APK signature and production package before release packaging."""

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path


def validate_output(signature, badging, policy):
    fingerprints = re.findall(
        r"^Signer #\d+ certificate SHA-256 digest: ([0-9a-fA-F]{64})$",
        signature,
        re.MULTILINE,
    )
    expected = policy["certificate_sha256"].lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("Invalid pinned signing certificate")
    if [value.lower() for value in fingerprints] != [expected]:
        raise ValueError("APK signing certificate does not match the existing application")
    match = re.search(r"^package: name='([^']+)' versionCode='(\d+)'", badging, re.MULTILINE)
    if not match or match.group(1) != policy["application_id"]:
        raise ValueError("APK is not the production application")
    if int(match.group(2)) < 23:
        raise ValueError("APK would downgrade the previously delivered application")
    return {
        "application_id": match.group(1),
        "version_code": int(match.group(2)),
        "certificate_sha256": expected,
    }


def verify(apk, build_tools, policy):
    signature = subprocess.run(
        [
            "java",
            "-jar",
            str(build_tools / "lib/apksigner.jar"),
            "verify",
            "--verbose",
            "--print-certs",
            str(apk),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    ).stdout
    aapt = build_tools / ("aapt.exe" if (build_tools / "aapt.exe").is_file() else "aapt")
    badging = subprocess.run(
        [str(aapt), "dump", "badging", str(apk)],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    ).stdout
    with apk.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {
        "schema": 1,
        "signature_verified": True,
        "apk_sha256": digest,
        **validate_output(signature, badging, policy),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--build-tools", type=Path, required=True)
    parser.add_argument("--policy", type=Path, default=Path("config/android-signing.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.apk, args.build_tools, json.loads(args.policy.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("APK signature and production identity verified against the previous release.")


if __name__ == "__main__":
    main()
