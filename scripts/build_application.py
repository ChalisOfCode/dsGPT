"""Build the persistent app payload from the same verified runtime/client as the kit."""

import argparse
import json
import re
import shutil
import zipfile
from pathlib import Path

from build_windows_bundle import digest, extract


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    base = parser.add_mutually_exclusive_group(required=True)
    base.add_argument("--kit", type=Path)
    base.add_argument(
        "--application", type=Path, help="Previously verified application payload to update"
    )
    parser.add_argument("--android", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--backend-wheel", type=Path)
    parser.add_argument("--dependency-lock", type=Path)
    parser.add_argument("--source-commit")
    parser.add_argument("--client", type=Path)
    parser.add_argument("--client-source-commit")
    parser.add_argument("--setup-source-commit")
    parser.add_argument("--android-source-commit")
    parser.add_argument(
        "--android-signature",
        type=Path,
        help="Successful verify_android_release.py receipt for this exact APK",
    )
    parser.add_argument(
        "--ci-acceptance",
        action="store_true",
        help="Disposable CI installer only; embeds the separate acceptance APK",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.ci_acceptance:
        # Keep this mode explicit and impossible to mistake for a release manifest.
        android_identity = "com.dsgpt.mobile.acceptance"
        signature = None
    else:
        if not args.android_signature:
            raise ValueError("Production packaging requires verified Android signing continuity")
        signature = json.loads(args.android_signature.read_text())
        policy = json.loads((root / "config/android-signing.json").read_text())
        if (
            signature.get("signature_verified") is not True
            or signature.get("apk_sha256") != digest(args.android)
            or signature.get("certificate_sha256") != policy["certificate_sha256"]
            or signature.get("application_id") != policy["application_id"]
        ):
            raise ValueError("Missing, stale or mismatched Android signing verification")
        android_identity = policy["application_id"]
    base_path = args.application or args.kit
    base_manifest = base_path / (
        "application-manifest.json" if args.application else "kit-manifest.json"
    )
    source = json.loads(base_manifest.read_text())
    if args.application and source.get("kind") != "persistent_application":
        raise ValueError("Expected a persistent application payload")
    for commit in (args.setup_source_commit, args.android_source_commit):
        if commit and not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise ValueError("Invalid setup or Android source commit")
    if bool(args.backend_wheel) != bool(args.source_commit):
        raise ValueError("A replacement backend requires its exact source commit")
    if args.source_commit and not re.fullmatch(r"[0-9a-f]{40}", args.source_commit):
        raise ValueError("Invalid backend source commit")
    if bool(args.client) != bool(args.client_source_commit):
        raise ValueError("A replacement client requires its exact source commit")
    if args.client_source_commit and not re.fullmatch(r"[0-9a-f]{40}", args.client_source_commit):
        raise ValueError("Invalid client source commit")
    if args.client and not (args.client / "dsGPT.exe").is_file():
        raise ValueError("Replacement client must contain dsGPT.exe")
    for name, record in source["files"].items():
        path = base_path / name
        if (
            not path.resolve().is_relative_to(base_path.resolve())
            or not path.is_file()
            or path.stat().st_size != record["bytes"]
            or digest(path) != record["sha256"]
        ):
            raise ValueError("Base payload changed: " + name)
    out = args.output
    out.mkdir(parents=True, exist_ok=False)
    for name in ("python", "client", "platform-tools"):
        source_dir = args.client if name == "client" and args.client else base_path / name
        shutil.copytree(source_dir, out / name, ignore=shutil.ignore_patterns("__pycache__"))
    helper = out / "python/Lib/site-packages/dsgpt_application"
    if helper.exists():
        shutil.rmtree(helper)
    shutil.copytree(
        root / "scripts/application",
        out / "python/Lib/site-packages/dsgpt_application",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    (out / "android").mkdir()
    shutil.copy2(args.android, out / "android/dsGPT-Mobile.apk")
    shutil.copy2(root / "APP_START_HERE.md", out / "START-HERE.txt")
    for filename, action in (("Repair dsGPT.cmd", "setup"), ("Connect Pixel.cmd", "pair-phone")):
        (out / filename).write_bytes(
            (
                '@echo off\r\nsetlocal\r\n"%~dp0python\\python.exe" -B -I -m dsgpt_application '
                + action
                + "\r\n"
                'set "DSGPT_RESULT=%ERRORLEVEL%"\r\n'
                'if not "%DSGPT_RESULT%"=="0" pause\r\nexit /b %DSGPT_RESULT%\r\n'
            ).encode("ascii")
        )
    site = out / "python/Lib/site-packages"
    if args.backend_wheel:
        with zipfile.ZipFile(args.backend_wheel) as wheel:
            for path in (root / "src/dsgpt").glob("*.py"):
                if wheel.read("dsgpt/" + path.name) != path.read_bytes():
                    raise ValueError("Stale replacement backend wheel")
        shutil.rmtree(site / "dsgpt")
        for path in site.glob("dsgpt_backend-*.dist-info"):
            shutil.rmtree(path)
        extract(args.backend_wheel, site, wheel=True)
    if args.dependency_lock:
        lock = json.loads(args.dependency_lock.read_text())
        for item in lock["wheels"]:
            path = args.dependency_lock.parent / item["file"]
            if (
                not path.resolve().is_relative_to(args.dependency_lock.parent.resolve())
                or path.stat().st_size != item["bytes"]
                or digest(path) != item["sha256"]
                or not path.name.endswith(("none-any.whl", "win_amd64.whl"))
            ):
                raise ValueError("Invalid extra dependency wheel")
            # Keep the existing dependency version when identical, reject conflicting imports.
            with zipfile.ZipFile(path) as package:
                for name in package.namelist():
                    old = site / name
                    if old.is_file() and old.read_bytes() != package.read(name):
                        raise ValueError("Extra dependency conflicts with base payload: " + name)
            extract(path, site, wheel=True)
    shutil.rmtree(site / "dsgpt_acceptance")
    shutil.copytree(
        root / "scripts/acceptance",
        site / "dsgpt_acceptance",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    if (root / "docs/speech-licenses").is_dir():
        shutil.copytree(root / "docs/speech-licenses", out / "licenses/speech", dirs_exist_ok=True)
    for name in ("recover-owner", "startup-settings"):
        shutil.copy2(
            root / "scripts" / (name + ".cmd"),
            out / ("Recover Owner.cmd" if name == "recover-owner" else "Startup Settings.cmd"),
        )
    manifest = {
        "format": 1,
        "kind": "persistent_application",
        "source_commit": args.source_commit or source["source_commit"],
        "native_client_source_commit": args.client_source_commit
        or source.get("native_client_source_commit", source["source_commit"]),
        "backend_wheel_sha256": digest(args.backend_wheel)
        if args.backend_wheel
        else source.get("backend_wheel_sha256"),
        "setup_source_commit": args.setup_source_commit,
        "android_source_commit": args.android_source_commit,
        "base_application_manifest_sha256": digest(base_manifest) if args.application else None,
        "acceptance_manifest_sha256": source.get("acceptance_manifest_sha256")
        if args.application
        else digest(base_manifest),
        "android_application_id": android_identity,
        "ci_acceptance_only": args.ci_acceptance,
        "android_signature": signature,
        "files": {
            p.relative_to(out).as_posix(): {"bytes": p.stat().st_size, "sha256": digest(p)}
            for p in sorted(out.rglob("*"))
            if p.is_file()
        },
    }
    (out / "application-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"source_commit": manifest["source_commit"], "files": len(manifest["files"])}))


if __name__ == "__main__":
    main()
