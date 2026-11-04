"""Free, pinned secret scan of tracked source only; never upload raw scanner reports."""

import hashlib
import os
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path

VERSION = "8.30.1"
ARCHIVE_SHA256 = "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb"
URL = f"https://github.com/gitleaks/gitleaks/releases/download/v{VERSION}/gitleaks_{VERSION}_linux_x64.tar.gz"


def main():
    root = Path(__file__).resolve().parents[1]
    if os.name != "posix":
        raise RuntimeError("This pinned scanner build runs on the standard Linux CI job")
    paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().split("\0")
    with tempfile.TemporaryDirectory(prefix="dsgpt-source-scan-") as temporary:
        owned = Path(temporary)
        source = owned / "source"
        source.mkdir()
        for name in filter(None, paths):
            path = root / name
            if path.is_symlink() or not path.is_file():
                raise ValueError("Only regular tracked source files can be scanned")
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        archive = owned / "scanner.tar.gz"
        with urllib.request.urlopen(URL, timeout=60) as response, archive.open("xb") as out:
            total = 0
            while block := response.read(1024**2):
                total += len(block)
                if total > 16 * 1024**2:
                    raise ValueError("Scanner download exceeded its reviewed bound")
                out.write(block)
        with archive.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != ARCHIVE_SHA256:
                raise ValueError("Secret-scanner download does not match the reviewed release")
        binary = owned / "gitleaks"
        with tarfile.open(archive) as contents:
            member = contents.getmember("gitleaks")
            if not member.isfile() or member.size > 32 * 1024**2:
                raise ValueError("Unexpected scanner executable")
            binary.write_bytes(contents.extractfile(member).read())
        binary.chmod(0o700)
        subprocess.run(
            [str(binary), "dir", str(source), "--no-banner", "--redact=100"],
            check=True,
            timeout=120,
        )
    print("Tracked-source secret scan passed; manual privacy review is still required.")


if __name__ == "__main__":
    main()
