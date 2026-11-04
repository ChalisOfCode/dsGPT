"""Fail closed before artifact uploads; no deletion and no billing-setting changes.

This repository-size guard complements verified $0 account budgets. It is not an
account-wide storage/billing guarantee: other repositories and simultaneous uploads
can consume allowance. Use one-day retention and the administrative usage block.
"""

import argparse
import json
import os
import re
import urllib.request
from pathlib import Path

MAX_ARTIFACT_BYTES = 128 * 1024**2
MAX_REPOSITORY_BYTES = 300 * 1024**2
FORBIDDEN_SUFFIXES = {".jks", ".keystore", ".p12", ".pfx", ".pem", ".key"}


def payload_size(paths):
    files = set()
    for path in paths:
        if not path.exists():
            raise ValueError("Expected artifact path is missing")
        if path.is_symlink():
            raise ValueError("Artifact symlinks are forbidden")
        entries = path.rglob("*") if path.is_dir() else [path]
        for entry in entries:
            if entry.is_symlink():
                raise ValueError("Artifact symlinks are forbidden")
            if entry.is_file():
                if entry.suffix.lower() in FORBIDDEN_SUFFIXES or entry.name.startswith(".env"):
                    raise ValueError("Private signing/configuration file in artifact selection")
                files.add(entry.resolve())
    total = sum(path.stat().st_size for path in files)
    if not files or total > MAX_ARTIFACT_BYTES:
        raise ValueError("Artifact is empty or exceeds the reviewed size limit")
    return total


def check_inventory(pages, additional):
    artifacts = [a for page in pages for a in page["artifacts"] if not a["expired"]]
    size = sum(a["size_in_bytes"] for a in artifacts)
    if size + additional > MAX_REPOSITORY_BYTES:
        raise ValueError("Artifact allowance guard: preserve existing outputs before cleanup")
    return size


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()
    if os.environ.get("DSGPT_ZERO_COST_READY") != "true":
        raise SystemExit("Administrative zero-cost verification is not recorded")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise SystemExit("Invalid repository identity")
    token = os.environ["GH_TOKEN"]

    def get(path):
        request = urllib.request.Request(
            "https://api.github.com/repos/" + repo + path,
            headers={
                "Authorization": "Bearer " + token,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    if get("")["private"]:
        raise SystemExit("Artifacts may only be uploaded for the authorized public repository")
    pages = []
    for number in range(1, 101):
        page = get(f"/actions/artifacts?per_page=100&page={number}")
        pages.append(page)
        if len(page["artifacts"]) < 100:
            break
    else:
        raise SystemExit("Artifact inventory exceeded the bounded review limit")
    additional = payload_size(args.paths)
    existing = check_inventory(pages, additional)
    print(
        json.dumps(
            {
                "existing_repository_bytes": existing,
                "selected_bytes": additional,
                "account_budget_verification_required": True,
            }
        )
    )


if __name__ == "__main__":
    main()
