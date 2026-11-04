"""Assemble an offline Windows runtime from publisher-verified, locked inputs.

This does not execute Windows binaries or claim native acceptance. No pip,
user-site directories, registry Python installation or PATH changes at install.
"""

import argparse
import base64
import csv
import email
import hashlib
import io
import json
import shutil
import stat
import subprocess
import tomllib
import zipfile
from pathlib import Path, PurePosixPath

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def digest(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def extract(archive, destination, wheel=False):
    with zipfile.ZipFile(archive) as z:
        names = set()
        for info in z.infolist():
            path = PurePosixPath(info.filename)
            if (
                path.is_absolute()
                or ".." in path.parts
                or "\\" in info.filename
                or ":" in info.filename
                or info.filename.casefold() in names
                or stat.S_ISLNK(info.external_attr >> 16)
            ):
                raise ValueError("Unsafe package member")
            names.add(info.filename.casefold())
            # srt's nine optional subtitle CLI scripts are retained at their
            # archive paths for provenance, never installed on PATH or executed.
            # Vosk uses its importable modules. Other wheel relocation still
            # requires a deliberate review rather than silently moving files.
            srt_script = (
                wheel
                and len(path.parts) == 3
                and path.parts[:2] == ("srt-3.5.3.data", "scripts")
                and path.name
                in {
                    "srt",
                    "srt-deduplicate",
                    "srt-fixed-timeshift",
                    "srt-linear-timeshift",
                    "srt-lines-matching",
                    "srt-mux",
                    "srt-normalise",
                    "srt-play",
                    "srt-process",
                }
            )
            if any(part.endswith(".data") for part in path.parts) and not srt_script:
                raise ValueError("Wheel relocation needs explicit review")
        if wheel:
            records = [n for n in z.namelist() if n.endswith(".dist-info/RECORD")]
            if len(records) != 1:
                raise ValueError("Missing wheel records")
            verified = {records[0]}
            for name, checksum, size in csv.reader(io.StringIO(z.read(records[0]).decode())):
                if name == records[0]:
                    continue
                algorithm, expected = checksum.split("=", 1)
                if algorithm != "sha256":
                    raise ValueError("Unsupported wheel checksum")
                data = z.read(name)
                actual = (
                    base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("=")
                )
                if actual != expected or len(data) != int(size):
                    raise ValueError("Wheel record mismatch")
                verified.add(name)
            if {n for n in z.namelist() if not n.endswith("/")} != verified:
                raise ValueError("Unrecorded wheel content")
        for info in z.infolist():
            target = destination / info.filename
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise ValueError("Package file collision")
            target.write_bytes(z.read(info))


def dependencies(wheels):
    environment = default_environment()
    environment.update(
        os_name="nt",
        sys_platform="win32",
        platform_system="Windows",
        platform_machine="AMD64",
        python_version="3.13",
        python_full_version="3.13.16",
        implementation_version="3.13.16",
        extra="",
    )
    records = {}
    for file in wheels:
        with zipfile.ZipFile(file) as z:
            metadata = email.message_from_bytes(
                z.read(next(n for n in z.namelist() if n.endswith(".dist-info/METADATA")))
            )
        key = canonicalize_name(metadata["Name"])
        if key in records:
            raise ValueError("Duplicate wheel package")
        records[key] = metadata
    checked = 0
    for metadata in records.values():
        for raw in metadata.get_all("Requires-Dist", []):
            requirement = Requirement(raw)
            if requirement.marker and not requirement.marker.evaluate(environment):
                continue
            dependency = records.get(canonicalize_name(requirement.name))
            if not dependency or dependency["Version"] not in requirement.specifier:
                raise ValueError("Unsatisfied Windows dependency: " + str(requirement))
            checked += 1
    return checked


def main():
    from ci_provenance import inventory

    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--client",
        type=Path,
        required=True,
        help="Current CI Windows client directory including SOURCE.json",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    lock = json.loads((root / "requirements-windows.lock.json").read_text())
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    backend = root / f"dist/dsgpt_backend-{version}-py3-none-any.whl"
    wheels = [args.inputs / "wheels" / record["file"] for record in lock["wheels"]]
    python = args.inputs / lock["python"]["file"]
    for path, record in [(python, lock["python"]), *zip(wheels, lock["wheels"], strict=True)]:
        if digest(path) != record["sha256"] or path.stat().st_size != record["bytes"]:
            raise ValueError("Locked input mismatch: " + path.name)
    with zipfile.ZipFile(backend) as z:
        for source in (root / "src/dsgpt").glob("*.py"):
            if z.read("dsgpt/" + source.name) != source.read_bytes():
                raise ValueError("Stale backend wheel")
    requirement_count = dependencies([*wheels, backend])
    source_commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    client_manifest = json.loads((args.client / "SOURCE.json").read_text())
    if (
        client_manifest.get("source_commit") != source_commit
        or client_manifest.get("files") != inventory(args.client)
        or "dsGPT.exe" not in client_manifest["files"]
    ):
        raise ValueError("Windows client differs from this source's verified build output")
    output = args.output
    output.mkdir(parents=True, exist_ok=False)
    extract(python, output / "python")
    for wheel in [*wheels, backend]:
        extract(wheel, output / "python/Lib/site-packages", wheel=True)
    # Embeddable _pth enables isolation without executing site/user .pth hooks.
    (output / "python/python313._pth").write_text("python313.zip\n.\nLib/site-packages\n")
    shutil.copytree(args.client, output / "client")
    shutil.copy2(root / "APP_START_HERE.md", output / "README.md")
    shutil.copy2(root / "requirements-windows.lock.json", output / "provenance.json")
    (output / "Backend Check.cmd").write_text(
        '@echo off\r\n"%~dp0python\\python.exe" -I -m dsgpt.managed check\r\npause\r\n'
    )
    (output / "Backend Console.cmd").write_text(
        '@echo off\r\n"%~dp0python\\python.exe" -I -m dsgpt.managed %*\r\n'
    )
    (output / "History Import.cmd").write_text(
        '@echo off\r\n"%~dp0python\\python.exe" -I -m dsgpt.history_import '
        '--data-dir "%LOCALAPPDATA%\\dsGPT\\managed\\data" %*\r\n'
    )
    (output / "Recover Owner.cmd").write_bytes(
        (root / "scripts/recover-owner.cmd")
        .read_bytes()
        .replace(b"\r\n", b"\n")
        .replace(b"\n", b"\r\n")
    )
    (output / "Startup Settings.cmd").write_bytes(
        (root / "scripts/startup-settings.cmd")
        .read_bytes()
        .replace(b"\r\n", b"\n")
        .replace(b"\n", b"\r\n")
    )
    manifest = {
        str(path.relative_to(output)): {"sha256": digest(path), "bytes": path.stat().st_size}
        for path in sorted(output.rglob("*"))
        if path.is_file()
    }
    report = {
        "version": version,
        "source_commit": source_commit,
        "python_version": lock["python"]["version"],
        "packages": len(wheels) + 1,
        "verified_dependency_edges": requirement_count,
        "windows_execution": "not_tested",
        "files": manifest,
    }
    (output / "payload-manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "output": str(output.resolve()),
                "files": len(manifest),
                "verified_dependency_edges": requirement_count,
            }
        )
    )


if __name__ == "__main__":
    main()
