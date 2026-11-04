"""Assemble the portable test kit from pinned Python/wheels and this CI build's clients."""

import argparse
import concurrent.futures
import json
import shutil
import subprocess
import time
import tomllib
import urllib.request
from pathlib import Path

from build_windows_bundle import dependencies, digest, extract

ADB = {
    "file": "platform-tools_r37.0.1-win.zip",
    "url": "https://dl.google.com/android/repository/platform-tools_r37.0.1-win.zip",
    "bytes": 8044989,
    "sha256": "45f4d63113e895ebde0c90f194099a4676b6ac653bd28d54314a9e022bbc1a99",
}
USB_DRIVER = {
    "file": "usb_driver_r13-windows.zip",
    "url": "https://dl.google.com/android/repository/usb_driver_r13-windows.zip",
    "bytes": 8682039,
    "sha256": "360b01d3dfb6c41621a3a64ae570dfac2c9a40cca1b5a1f136ae90d02f5e9e0b",
}


def fetch(record, directory):
    target = directory / record["file"]
    if (
        target.is_file()
        and target.stat().st_size == record["bytes"]
        and digest(target) == record["sha256"]
    ):
        return target
    if "vendored" in record:
        root = Path(__file__).resolve().parents[1]
        source = (root / record["vendored"]).resolve()
        if (
            not source.is_relative_to(root)
            or not source.is_file()
            or source.stat().st_size != record["bytes"]
            or digest(source) != record["sha256"]
        ):
            raise ValueError("Vendored wheel did not match its pinned SHA256")
        shutil.copyfile(source, target)
        return target
    for attempt in range(3):
        try:
            request = urllib.request.Request(
                record["url"], headers={"User-Agent": "dsGPT-acceptance-kit"}
            )
            partial = target.with_suffix(".partial")
            with (
                urllib.request.urlopen(request, timeout=60) as source,
                partial.open("wb") as output,
            ):
                total = 0
                while block := source.read(1024**2):
                    total += len(block)
                    if total > record["bytes"]:
                        raise ValueError("Publisher asset exceeded its pinned size")
                    output.write(block)
            if total != record["bytes"] or digest(partial) != record["sha256"]:
                raise ValueError("Publisher asset did not match its pinned SHA256")
            partial.replace(target)
            return target
        except OSError:
            if attempt == 2:
                raise
            time.sleep(attempt + 1)
    raise RuntimeError("Download failed")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--client", type=Path, required=True)
    parser.add_argument("--android", type=Path, required=True)
    parser.add_argument("--android-test", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    lock = json.loads((root / "requirements-windows.lock.json").read_text())
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    wheel = root / f"dist/dsgpt_backend-{version}-py3-none-any.whl"
    records = [lock["python"], *lock["wheels"], ADB]
    args.cache.mkdir(parents=True, exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        assets = list(pool.map(lambda r: fetch(r, args.cache), records))
    dependencies([*assets[1:-1], wheel])
    out = args.output
    out.mkdir(parents=True, exist_ok=False)
    extract(assets[0], out / "python")
    for path in [*assets[1:-1], wheel]:
        extract(path, out / "python/Lib/site-packages", wheel=True)
    (out / "python/python313._pth").write_text("python313.zip\n.\nLib/site-packages\n")
    shutil.copytree(
        root / "scripts/acceptance",
        out / "python/Lib/site-packages/dsgpt_acceptance",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    extract(assets[-1], out)
    extract(fetch(USB_DRIVER, args.cache), out)
    shutil.copytree(args.client, out / "client")
    (out / "android").mkdir()
    shutil.copy2(args.android, out / "android/app-debug.apk")
    shutil.copy2(args.android_test, out / "android/app-debug-androidTest.apk")
    (out / "scripts").mkdir()
    for name in (
        "live_documents",
        "live_isolated_build",
        "live_browser_tool",
        "live_search_service",
        "live_attachment_semantic",
        "prepare_android_toolchain",
    ):
        shutil.copy2(root / "scripts" / (name + ".py"), out / "scripts")
    shutil.copytree(
        root / "execution", out / "execution", ignore=shutil.ignore_patterns("__pycache__")
    )
    (out / "tests/fixtures").mkdir(parents=True)
    shutil.copy2(root / "tests/fixtures/document-samples.json", out / "tests/fixtures")
    shutil.copy2(root / "ACCEPTANCE_TOOL.md", out / "START-HERE.txt")
    shutil.copy2(root / "CLIENT_ACCEPTANCE.md", out / "acceptance-scope.md")
    (out / "backend-provenance.json").write_text(
        json.dumps(
            {
                "python": lock["python"],
                "wheels": lock["wheels"],
                "client_provenance": "Current CI build; exact files are in kit-manifest.json",
            },
            indent=2,
        )
    )
    (out / "Run-dsGPT-Acceptance.cmd").write_bytes(
        (
            "@echo off\r\nsetlocal\r\ntitle dsGPT automatic acceptance\r\n"
            "echo dsGPT will test this PC and a USB-connected Pixel using separate test data.\r\n"
            "echo Missing Ollama, test model, Docker and Tailscale are installed automatically.\r\n"
            "echo First-run downloads can be several GB. Normal double-click is enough.\r\n"
            "echo Ollama setup and model download are automatic. No Ollama account is needed.\r\n"
            "echo Approve Windows permissions and phone authorization on their own screens.\r\n"
            "echo Keep this window open. A report ZIP will be copied to your Desktop.\r\n"
            'echo.\r\nif not exist "%~dp0python\\python.exe" (\r\n'
            " echo Extract the entire ZIP first, then run this CMD from the extracted folder.\r\n"
            " pause\r\n exit /b 2\r\n)\r\n"
            '"%~dp0python\\python.exe" -B -I -m dsgpt_acceptance --kit "%~dp0."\r\n'
            'set "DSGPT_RESULT=%ERRORLEVEL%"\r\n'
            "echo.\r\n"
            "if %DSGPT_RESULT% EQU 3010 echo Save your work and restart Windows. "
            "Setup will reopen after you sign in.\r\n"
            "if %DSGPT_RESULT% EQU 2 echo Some checks need setup or were skipped. Read report.\r\n"
            "if %DSGPT_RESULT% EQU 1 echo A check failed. Send the report ZIP back.\r\n"
            "if %DSGPT_RESULT% EQU 0 echo Checks finished. Send the report ZIP back.\r\n"
            "pause\r\nexit /b %DSGPT_RESULT%\r\n"
        ).encode("ascii")
    )
    launcher = (out / "Run-dsGPT-Acceptance.cmd").read_bytes()
    wireless = launcher.replace(b'--kit "%~dp0."', b'--kit "%~dp0." --wireless')
    wireless = wireless.replace(b"a USB-connected Pixel", b"a wirelessly connected Pixel")
    (out / "Run-dsGPT-Wireless.cmd").write_bytes(wireless)
    files = {
        str(p.relative_to(out)).replace("\\", "/"): {"bytes": p.stat().st_size, "sha256": digest(p)}
        for p in sorted(out.rglob("*"))
        if p.is_file()
    }
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    (out / "kit-manifest.json").write_text(
        json.dumps(
            {
                "source_commit": source,
                "python": lock["python"],
                "adb": ADB,
                "usb_driver": USB_DRIVER,
                "files": files,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps({"files": len(files), "source_commit": source, "kit": str(out)}))


if __name__ == "__main__":
    main()
