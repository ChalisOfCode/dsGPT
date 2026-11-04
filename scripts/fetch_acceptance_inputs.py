"""Fetch only reviewed public acceptance assets; verify exact bytes before use."""

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path

from dsgpt.catalog import CATALOG


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    evidence = []
    for key in ("qwen3-1-7b-q8-0", "llama-b11718-linux-x64"):
        asset = CATALOG[key]
        destination = args.directory / asset.url.rsplit("/", 1)[1]
        if not destination.exists():
            partial = destination.with_suffix(destination.suffix + ".partial")
            request = urllib.request.Request(asset.url, headers={"User-Agent": "dsGPT-acceptance"})
            total = 0
            with (
                urllib.request.urlopen(request, timeout=60) as response,
                partial.open("wb") as target,
            ):
                while block := response.read(1024**2):
                    total += len(block)
                    if total > asset.size:
                        raise ValueError("Publisher asset exceeded its reviewed size")
                    target.write(block)
            with partial.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if total != asset.size or digest != asset.sha256:
                raise ValueError("Publisher asset did not match the reviewed hash/size")
            partial.replace(destination)
        with destination.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        assert destination.stat().st_size == asset.size and digest == asset.sha256
        evidence.append(
            {
                "asset_id": key,
                "url": asset.url,
                "sha256": digest,
                "bytes": asset.size,
                "license": asset.license,
            }
        )
        print("Verified public input: " + key, flush=True)
    args.output.write_text(json.dumps(evidence, indent=2) + "\n")


if __name__ == "__main__":
    main()
