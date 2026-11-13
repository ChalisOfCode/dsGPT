"""Prepare a fresh locked runtime for production application packaging.

No APK or fake instrumentation is required for this intermediate payload. It is
not an acceptance-kit delivery. Reuses the same pinned runtime inputs and wheel
integrity/dependency checks as normal packaging; no installer is executed here.
"""
import argparse
import concurrent.futures
import json
import shutil
import subprocess
import tomllib
import zipfile
from pathlib import Path

from build_acceptance_kit import ADB, fetch
from build_windows_bundle import dependencies, digest, extract
from ci_provenance import inventory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--client", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    client = json.loads((args.client / "SOURCE.json").read_text())
    if client != {"schema": 1, "source_commit": source, "files": inventory(args.client)}:
        raise ValueError("Native client provenance mismatch")
    lock = json.loads((root / "requirements-windows.lock.json").read_text())
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    wheel = root / f"dist/dsgpt_backend-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel) as package:
        for path in (root / "src/dsgpt").glob("*.py"):
            if package.read("dsgpt/" + path.name) != path.read_bytes():
                raise ValueError("Stale backend wheel")
    args.cache.mkdir(parents=True, exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        assets = list(pool.map(lambda r: fetch(r, args.cache),
                              [lock["python"], *lock["wheels"], ADB]))
    dependencies([*assets[1:-1], wheel])
    args.output.mkdir(parents=True, exist_ok=False)
    extract(assets[0], args.output / "python")
    for path in [*assets[1:-1], wheel]:
        extract(path, args.output / "python/Lib/site-packages", wheel=True)
    (args.output / "python/python313._pth").write_text("python313.zip\n.\nLib/site-packages\n")
    shutil.copytree(root / "scripts/acceptance",
                    args.output / "python/Lib/site-packages/dsgpt_acceptance",
                    ignore=shutil.ignore_patterns("__pycache__"))
    extract(assets[-1], args.output)
    shutil.copytree(args.client, args.output / "client")
    (args.output / "kit-manifest.json").write_text(json.dumps({
        "kind": "application_runtime_intermediate", "source_commit": source,
        "backend_wheel_sha256": digest(wheel), "files": inventory(args.output),
    }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
