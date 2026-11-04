"""Prepare a minimal non-Windows kit to exercise the exact bundled harness in CI."""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--phone", action="store_true")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    package = Path(sysconfig.get_path("purelib")) / "dsgpt_acceptance"
    shutil.copytree(
        repo / "scripts/acceptance",
        package,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    kit = args.root / "kit"
    kit.mkdir(parents=True)
    if args.phone:
        (kit / "android").mkdir()
        output = repo / "clients/android/app/build/outputs/apk"
        shutil.copy2(output / "debug/app-debug.apk", kit / "android")
        shutil.copy2(output / "androidTest/debug/app-debug-androidTest.apk", kit / "android")
    files = {
        str(p.relative_to(kit)): {
            "bytes": p.stat().st_size,
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        }
        for p in kit.rglob("*")
        if p.is_file()
    }
    (kit / "kit-manifest.json").write_text(
        json.dumps({"source_commit": "CI-fixture", "files": files})
    )
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-I",
            "-m",
            "dsgpt_acceptance",
            "--ci",
            "--kit",
            str(kit),
            "--output",
            str(args.root / "results"),
            *([] if args.phone else ["--no-phone"]),
        ]
    )
    report = json.loads((args.root / "results/report/report.json").read_text())
    required = [
        "Kit file integrity",
        "Start isolated backend",
        "Chat, restart, cancellation, pairing and diagnostics",
    ]
    if args.phone:
        required += [
            "Connect Pixel and install separate test app",
            "Pixel offline diagnostics and frame/memory metrics",
            "Pixel pairing, background reply and app update",
        ]
    outcomes = {c["name"]: c["status"] for c in report["checks"]}
    assert result.returncode == 0 and all(outcomes.get(n) == "PASS" for n in required), outcomes


if __name__ == "__main__":
    main()
