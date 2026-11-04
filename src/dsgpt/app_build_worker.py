"""Reviewed build/check/sign recipes. Executed inside the isolated guest only."""

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def run(argv, **kwargs):
    print("Running: " + " ".join(str(a) for a in argv), flush=True)
    subprocess.run([str(a) for a in argv], check=True, **kwargs)


def tools():
    return Path(os.environ.get("DSGPT_ANDROID_SDK", "/opt/android")) / "build-tools/35.0.0"


def android_build():
    root = Path("android").resolve()
    if not (root / "app/build.gradle").is_file() and not (root / "app/build.gradle.kts").is_file():
        raise ValueError(
            "Android project missing; scaffold_app(android) supplies the supported layout"
        )
    env = os.environ.copy()
    env["ANDROID_HOME"] = str(tools().parents[1])
    env["ANDROID_USER_HOME"] = str(Path(".android").resolve())
    env["GRADLE_USER_HOME"] = str(Path(".gradle-user").resolve())
    cache = Path(os.environ.get("DSGPT_GRADLE_CACHE", "/opt/dsgpt/gradle-home"))
    if cache.resolve() == Path(env["GRADLE_USER_HOME"]):
        # A prepared host fixture may reuse the writable cache through a symlink.
        # Gradle cannot open the same modules-2 tree with both lock modes.
        env.pop("GRADLE_RO_DEP_CACHE", None)
    else:
        env["GRADLE_RO_DEP_CACHE"] = str(cache / "caches")
    if not Path(env["GRADLE_USER_HOME"]).exists():
        shutil.copytree(
            cache,
            env["GRADLE_USER_HOME"],
            ignore=shutil.ignore_patterns("*.lock", "daemon", "workers", "modules-2"),
        )
    gradle = os.environ.get("DSGPT_GRADLE", "/opt/gradle/gradle-8.13/bin/gradle")
    run(
        [
            gradle,
            "--offline",
            "--no-daemon",
            "--max-workers=2",
            "--console=plain",
            "assembleDebug",
            "testDebugUnitTest",
            "lintDebug",
        ],
        cwd=root,
        env=env,
    )
    reports = sorted((root / "app/build/test-results/testDebugUnitTest").glob("TEST-*.xml"))
    tests = failures = 0
    for report in reports:
        suite = ET.parse(report).getroot()
        tests += int(suite.attrib.get("tests", 0)) - int(suite.attrib.get("skipped", 0))
        failures += int(suite.attrib.get("failures", 0)) + int(suite.attrib.get("errors", 0))
    if failures:
        raise ValueError("Android unit tests failed")
    if tests == 0:
        raise ValueError(
            "Add meaningful app behavior tests under android/app/src/test/java; no tests ran"
        )
    apk = root / "app/build/outputs/apk/debug/app-debug.apk"
    run([tools() / "apksigner", "verify", "--verbose", str(apk)])
    run([tools() / "zipalign", "-c", "4", str(apk)])
    shutil.copy2(apk, "dist/app.apk")
    return {
        "android": {
            "unit_tests": tests,
            "lint_passed": True,
            "signature_verified": True,
            "native_runtime_verified": False,
        }
    }


def windows_build():
    root = Path("windows")
    sources = sorted(
        p for p in root.rglob("*.cpp") if p.name != "tests.cpp" and "tests" not in p.parts
    )
    if not sources or not (root / "main.cpp").is_file():
        raise ValueError(
            "Windows source missing; scaffold_app(windows) supplies the supported layout"
        )
    test = root / "tests.cpp"
    if not test.is_file():
        raise ValueError(
            "Add windows/tests.cpp with runnable portable feature tests before building"
        )
    native = os.environ.get("DSGPT_NATIVE_CXX", "g++")
    run(
        [
            native,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Iwindows",
            str(test),
            "-o",
            "dist/feature-tests",
        ]
    )
    run([str(Path("dist/feature-tests").resolve())])
    compiler = os.environ.get("DSGPT_WINDOWS_CXX", "x86_64-w64-mingw32-g++")
    run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-municode",
            "-mwindows",
            "-static",
            "-Iwindows",
            *sources,
            "-o",
            "dist/app.exe",
            "-lcomctl32",
            "-luser32",
            "-lgdi32",
            "-lshell32",
            "-lole32",
            "-lwinhttp",
            "-lws2_32",
        ]
    )
    content = Path("dist/app.exe").read_bytes()
    offset = int.from_bytes(content[60:64], "little")
    if content[:2] != b"MZ" or content[offset : offset + 4] != b"PE\0\0":
        raise ValueError("Compiler output is not a Windows PE executable")
    return {
        "windows": {
            "portable_test_program_passed": True,
            "pe_verified": True,
            "native_runtime_verified": False,
            "authenticode_signed": False,
        }
    }


def sign_android():
    # This mode runs in a NEW guest with no generated source or Gradle scripts.
    raw = base64.b64decode(Path("input-apk.b64").read_text(), validate=True)
    Path("input.apk").write_bytes(raw)
    key = Path("signing.p12")
    previous = Path("input-key.b64")
    if previous.exists():
        key.write_bytes(base64.b64decode(previous.read_text(), validate=True))
    else:
        run(
            [
                "keytool",
                "-genkeypair",
                "-keystore",
                key,
                "-storetype",
                "PKCS12",
                "-storepass",
                "android",
                "-keypass",
                "android",
                "-alias",
                "dsgpt",
                "-dname",
                "CN=dsGPT Local Development",
                "-keyalg",
                "RSA",
                "-keysize",
                "2048",
                "-validity",
                "10000",
                "-noprompt",
            ]
        )
    run(
        [
            tools() / "apksigner",
            "sign",
            "--ks",
            key,
            "--ks-type",
            "PKCS12",
            "--ks-pass",
            "pass:android",
            "--key-pass",
            "pass:android",
            "--ks-key-alias",
            "dsgpt",
            "--out",
            "signed.apk",
            "input.apk",
        ]
    )
    result = subprocess.run(
        [str(tools() / "apksigner"), "verify", "--verbose", "--print-certs", "signed.apk"],
        check=True,
        capture_output=True,
        text=True,
    )
    match = re.search(r"certificate SHA-256 digest:\s*([a-fA-F0-9]{64})", result.stdout)
    if not match:
        raise ValueError("APK certificate verification did not return a digest")
    Path("signing-report.json").write_text(
        json.dumps(
            {
                "signature_verified": True,
                "certificate_sha256": match[1].lower(),
                "signing_identity": "project_persistent_development",
                "native_runtime_verified": False,
            }
        )
    )


def main():
    target = sys.argv[1]
    if target == "sign-android":
        sign_android()
        return
    if target not in {"apk", "exe", "apps"}:
        raise ValueError("Unsupported app build target")
    Path("dist").mkdir(exist_ok=True)
    checks = {}
    if target in {"apk", "apps"}:
        checks.update(android_build())
    if target in {"exe", "apps"}:
        checks.update(windows_build())
    report = {"format": "dsgpt-app-build-v1", "checks": checks, "artifacts": {}}
    for name in ("app.apk", "app.exe"):
        path = Path("dist") / name
        if path.is_file():
            report["artifacts"][name] = hashlib.sha256(path.read_bytes()).hexdigest()
    Path("dist/build-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
