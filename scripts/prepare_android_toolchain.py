"""Prepare a minimal build context from exact reviewed public Android SDK bytes."""

import argparse
import hashlib
import json
import shutil
import urllib.request
from pathlib import Path

INPUTS = [
    (
        "sdk-build-tools.zip",
        "build-tools_r35_linux.zip",
        61958799,
        "bd3a4966912eb8b30ed0d00b0cda6b6543b949d5ffe00bea54c04c81e1561d88",
    ),
    (
        "sdk-platform.zip",
        "platform-35_r02.zip",
        64273788,
        "0988cacad01b38a18a47bac14a0695f246bc76c1b06c0eeb8eb0dc825ab0c8e0",
    ),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=False)
    evidence = []
    for name, publisher_name, size, digest in INPUTS:
        url = "https://dl.google.com/android/repository/" + publisher_name
        destination = args.directory / name
        total = 0
        with urllib.request.urlopen(url, timeout=60) as source, destination.open("wb") as target:
            while block := source.read(1024**2):
                total += len(block)
                if total > size:
                    raise ValueError("Android SDK input exceeded reviewed size")
                target.write(block)
        with destination.open("rb") as source:
            assert total == size and hashlib.file_digest(source, "sha256").hexdigest() == digest
        evidence.append({"url": url, "bytes": total, "sha256": digest})
    root = Path(__file__).resolve().parents[1]
    for name in ("Android.Dockerfile", "install-android-inputs.py", "build-android-fixture.py"):
        shutil.copyfile(root / "execution" / name, args.directory / name)
    args.output.write_text(json.dumps(evidence, indent=2) + "\n")
    print("Verified both Android SDK inputs and prepared the dedicated build context")


if __name__ == "__main__":
    main()
