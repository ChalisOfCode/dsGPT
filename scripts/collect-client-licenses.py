"""Collect redistribution notices from the exact resolved Rust/npm package graph."""

import json
import shutil
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
out = root / "dist/windows-client/licenses"
out.mkdir(parents=True, exist_ok=True)
metadata = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8-sig"))
rows = []
for package in metadata["packages"]:
    rows.append(
        f"{package['name']} {package['version']}: {package.get('license') or 'see package'}"
    )
    folder = Path(package["manifest_path"]).parent
    for file in folder.iterdir():
        if file.is_file() and file.name.upper().startswith(("LICENSE", "COPYING", "NOTICE")):
            dest = out / "rust" / (package["name"] + "-" + package["version"]) / file.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(file, dest)
lock = json.loads((root / "clients/desktop/package-lock.json").read_text(encoding="utf-8"))
for name, info in lock["packages"].items():
    if not name or info.get("dev"):
        continue
    rows.append(
        f"{name.removeprefix('node_modules/')} {info.get('version')}: "
        f"{info.get('license', 'see package')}"
    )
    folder = root / "clients/desktop" / name
    for file in folder.glob("*"):
        if file.is_file() and file.name.upper().startswith(("LICENSE", "COPYING", "NOTICE")):
            dest = out / "javascript" / name.removeprefix("node_modules/") / file.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(file, dest)
(out / "THIRD_PARTY_NOTICES.txt").write_text("\n".join(sorted(rows)) + "\n", encoding="utf-8")
