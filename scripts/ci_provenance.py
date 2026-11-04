"""Bind shared build outputs to one exact source commit before another job uses them."""

import argparse
import hashlib
import json
import re
from pathlib import Path


def inventory(root):
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Symlinks are not accepted in shared build outputs")
        if path.is_file() and path != root / "SOURCE.json":
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            files[path.relative_to(root).as_posix()] = {
                "bytes": path.stat().st_size,
                "sha256": digest,
            }
    if not files:
        raise ValueError("Shared build output is empty")
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["write", "verify"])
    parser.add_argument("root", type=Path)
    parser.add_argument("commit")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.commit):
        raise ValueError("Expected an exact Git source SHA")
    record = {"schema": 1, "source_commit": args.commit, "files": inventory(args.root)}
    path = args.root / "SOURCE.json"
    if args.mode == "write":
        path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    elif json.loads(path.read_text()) != record:
        raise ValueError("Shared build output is stale, replaced or from another source version")
    print(
        json.dumps({"mode": args.mode, "source_commit": args.commit, "files": len(record["files"])})
    )


if __name__ == "__main__":
    main()
