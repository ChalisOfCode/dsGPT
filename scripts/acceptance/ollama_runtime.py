"""Install the publisher-pinned CLI/GPU runtime without a desktop installer or onboarding."""

import hashlib
import json
import re
import shutil
import stat
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath

import httpx
from filelock import FileLock

OLLAMA = {
    "version": "0.40.8",
    "url": "https://github.com/ollama/ollama/releases/download/v0.40.8/ollama-windows-amd64.zip",
    "bytes": 1582537058,
    "sha256": "04d1d43ac62c2deb0393307bb49fed7caf6b192de41bdd497aaa9488089d5552",
}


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def plain_path(path):
    """Do not reuse cache entries redirected by symlinks or Windows reparse points."""
    return not path.is_symlink() and not (getattr(path.lstat(), "st_file_attributes", 0) & 0x400)


def member_name(name):
    path = PurePosixPath(name)
    if (
        not name
        or path.is_absolute()
        or str(path) != name
        or "\\" in name
        or ":" in name
        or any(
            p in {".", ".."}
            or p.endswith((".", " "))
            or re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", p)
            for p in path.parts
        )
    ):
        raise ValueError("Unsafe path in Ollama runtime archive")
    return path


def installed_ok(directory, spec):
    try:
        if not plain_path(directory):
            return False
        record = json.loads((directory / "runtime.json").read_text(encoding="utf-8"))
        if record["archive"] != spec or "ollama.exe" not in record["files"]:
            return False
        expected = set(record["files"]) | {"runtime.json"}
        actual = set()
        for path in directory.rglob("*"):
            if not plain_path(path):
                return False
            if path.is_file():
                actual.add(path.relative_to(directory).as_posix())
        if actual != expected:
            return False
        for name, info in record["files"].items():
            path = directory / member_name(name)
            if path.stat().st_size != info["bytes"] or sha256(path) != info["sha256"]:
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def download(client, target, spec, progress):
    """Retry/resume interrupted downloads; never extract before publisher hash verification."""
    partial = target.with_suffix(".partial")
    for path in (target, partial):
        if path.exists() and not plain_path(path):
            raise ValueError("Unsafe Ollama download cache")
    if target.is_file() and target.stat().st_size == spec["bytes"]:
        progress("Checking the cached Ollama download...")
        if sha256(target) == spec["sha256"]:
            return
    last_error = None
    for attempt in range(3):
        try:
            offset = partial.stat().st_size if partial.exists() else 0
            if offset >= spec["bytes"]:
                if offset == spec["bytes"] and sha256(partial) == spec["sha256"]:
                    partial.replace(target)
                    return
                partial.unlink()
                offset = 0
            headers = {"Range": f"bytes={offset}-"} if offset else {}
            headers["Accept-Encoding"] = "identity"
            progress("Downloading the Ollama engine and NVIDIA libraries automatically...")
            with client.stream(
                "GET", spec["url"], headers=headers, follow_redirects=True, timeout=120
            ) as response:
                response.raise_for_status()
                if response.status_code == 206:
                    expected = f"bytes {offset}-{spec['bytes'] - 1}/{spec['bytes']}"
                    if response.headers.get("content-range") != expected:
                        raise ValueError("Unexpected range in Ollama runtime download")
                elif response.status_code == 200:
                    offset = 0  # Publisher ignored Range: replace the partial rather than append.
                else:
                    raise ValueError("Unexpected Ollama runtime download response")
                total, last = offset, 0
                with partial.open("ab" if offset else "wb") as stream:
                    for block in response.iter_bytes(1024 * 1024):
                        total += len(block)
                        if total > spec["bytes"]:
                            raise ValueError("Ollama download exceeded its pinned size")
                        stream.write(block)
                        if time.monotonic() - last >= 5:
                            progress(f"Ollama engine download: {total * 100 // spec['bytes']}%")
                            last = time.monotonic()
            if total != spec["bytes"]:
                raise httpx.ReadError("Incomplete Ollama runtime download")
            progress("Verifying the Ollama publisher checksum...")
            if sha256(partial) != spec["sha256"]:
                partial.unlink()
                raise ValueError("Ollama publisher checksum mismatch; nothing was installed")
            partial.replace(target)
            return
        except (httpx.HTTPError, OSError) as exc:
            last_error = exc
            if attempt < 2:
                progress("Download interrupted; retrying automatically with saved progress...")
                time.sleep(2)
    raise RuntimeError(
        "Ollama download failed after automatic retries; progress is saved"
    ) from last_error


def install(client, cache, progress=print):
    """Return the verified CLI. No GUI process, PATH change, account or system install."""
    spec = OLLAMA
    cache.mkdir(parents=True, exist_ok=True)
    if not plain_path(cache):
        raise ValueError("Unsafe Ollama runtime cache")
    directory = cache / ("ollama-" + spec["version"])
    with FileLock(str(cache / "ollama-setup.lock"), timeout=1800):
        if installed_ok(directory, spec):
            progress("Reusing the verified local Ollama engine. No account setup is needed.")
            return directory / "ollama.exe"
        if directory.exists() and not plain_path(directory):
            raise ValueError("Unsafe Ollama installation cache")
        archive = cache / ("ollama-" + spec["version"] + ".zip")
        if shutil.disk_usage(cache).free < spec["bytes"] + 5 * 1024**3:
            raise RuntimeError("Ollama setup needs about 7 GB free for its download and extraction")
        download(client, archive, spec, progress)
        progress("Preparing Ollama automatically; there is no welcome screen to complete...")
        with tempfile.TemporaryDirectory(prefix="ollama-extract-", dir=cache) as temporary:
            staged = Path(temporary) / "runtime"
            staged.mkdir()
            files, names, total = {}, set(), 0
            with zipfile.ZipFile(archive) as source:
                for item in source.infolist():
                    name = member_name(
                        item.filename.rstrip("/") if item.is_dir() else item.filename
                    )
                    if stat.S_ISLNK(item.external_attr >> 16):
                        raise ValueError("Linked file in Ollama runtime archive")
                    if item.is_dir():
                        continue
                    folded = str(name).casefold()
                    total += item.file_size
                    if folded in names or folded == "runtime.json" or total > 8 * 1024**3:
                        raise ValueError("Invalid Ollama runtime archive contents")
                    names.add(folded)
                    if len(names) > 20000:
                        raise ValueError("Too many files in Ollama runtime archive")
                    dest = staged / name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with source.open(item) as incoming, dest.open("xb") as outgoing:
                        shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
                    files[str(name)] = {"bytes": dest.stat().st_size, "sha256": sha256(dest)}
            if "ollama.exe" not in files:
                raise ValueError("Publisher archive did not contain the Ollama CLI")
            (staged / "runtime.json").write_text(
                json.dumps({"archive": spec, "files": files}, indent=2), encoding="utf-8"
            )
            # Only replace this fixed, owned cache. Existing Ollama app installations stay intact.
            if directory.exists():
                shutil.rmtree(directory)
            staged.replace(directory)
        return directory / "ollama.exe"
