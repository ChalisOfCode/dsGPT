"""Pinned public reverse-engineering inputs; used at image construction, never during a task."""

import hashlib
import shutil
import sys
import tarfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

INPUTS = (
    (
        "voice.zip",
        "https://alphacephei.com/vosk/models/vosk-model-en-us-0.22-lgraph.zip",
        130557655,
        "d9838b4aaa82a75c4a17f5aca300eaca129aaab2a7cbf951bafbb500eb9c4334",
        "voice-model",
        "zip-strip",
    ),
    (
        "vosk.whl",
        "https://files.pythonhosted.org/packages/fc/ca/83398cfcd557360a3d7b2d732aee1c5f6999f68618d1645f38d53e14c9ff/vosk-0.3.45-py3-none-manylinux_2_12_x86_64.manylinux2010_x86_64.whl",
        7173758,
        "25e025093c4399d7278f543568ed8cc5460ac3a4bf48c23673ace1e25d26619f",
        "voice-python",
        "zip",
    ),
    (
        "apktool.jar",
        "https://github.com/iBotPeaches/Apktool/releases/download/v3.0.3/apktool_3.0.3.jar",
        15478013,
        "dbf930b076c6b9be08d57c449cacefc3bdd6b71ebd59b3066fc0e1f5b14f9423",
        "apktool",
        "jar",
    ),
    (
        "jadx.zip",
        "https://github.com/skylot/jadx/releases/download/v1.5.6/jadx-1.5.6.zip",
        72646741,
        "545ea2be9c242511bc145755cf4bda2485ade42966e096f8b4d3da2a230e8974",
        "jadx",
        "zip",
    ),
    (
        "ghidra.zip",
        "https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_12.2_build/ghidra_12.2_PUBLIC_20261016.zip",
        569712708,
        "2c2cd776db3c1f6a097ba418922378ac3649cadd5e844a6f5f088ae628a7be67",
        "ghidra",
        "zip-strip",
    ),
    (
        "jdk.tar.gz",
        "https://github.com/adoptium/temurin25-binaries/releases/download/jdk-25.0.5%2B8/OpenJDK25U-jdk_x64_linux_hotspot_25.0.5_8.tar.gz",
        141341188,
        "68982529869257d0ee6b824ec5aa270ff8b118bb438670da0b97ebdab178d7fb",
        "jdk",
        "tar",
    ),
)


def open_asset_download(url):
    """Retry transient response-open failures, never a partial or invalid archive."""
    for attempt in range(3):
        try:
            return urllib.request.urlopen(url, timeout=120)
        except urllib.error.HTTPError as error:
            if error.code not in {502, 503, 504} or attempt == 2:
                raise
            error.close()
        except urllib.error.URLError as error:
            if not isinstance(error.reason, TimeoutError) or attempt == 2:
                raise
        except TimeoutError:
            if attempt == 2:
                raise
        time.sleep(2 ** attempt)


def install(root):
    root = Path(root)
    downloads = root / "downloads"
    downloads.mkdir(exist_ok=True)
    for name, url, size, expected, folder, kind in INPUTS:
        target = downloads / name
        print("Installing verified asset tool: " + folder, flush=True)
        if (
            not target.is_file()
            or target.stat().st_size != size
            or hashlib.sha256(target.read_bytes()).hexdigest() != expected
        ):
            digest, total = hashlib.sha256(), 0
            with open_asset_download(url) as response, target.open("wb") as output:
                while data := response.read(1024 * 1024):
                    total += len(data)
                    if total > size:
                        raise ValueError("Download exceeds pinned size")
                    digest.update(data)
                    output.write(data)
            if total != size or digest.hexdigest() != expected:
                raise ValueError("Tool download failed integrity verification")
        destination = root / folder
        destination.mkdir(exist_ok=True)
        if kind == "jar":
            shutil.copyfile(target, destination / "apktool.jar")
        elif kind == "tar":
            stage = downloads / "jdk-expanded"
            stage.mkdir(exist_ok=True)
            with tarfile.open(target) as archive:
                archive.extractall(stage, filter="data")
            source = next(stage.iterdir())
            shutil.copytree(source, destination, dirs_exist_ok=True, symlinks=True)
        else:
            with zipfile.ZipFile(target) as archive:
                if sum(r.file_size for r in archive.infolist()) > 2 * 1024**3:
                    raise ValueError("Tool archive too large")
                for row in archive.infolist():
                    parts = (
                        Path(row.filename).parts[1:]
                        if kind == "zip-strip"
                        else Path(row.filename).parts
                    )
                    if not parts:
                        continue
                    output = destination.joinpath(*parts)
                    if not output.resolve().is_relative_to(destination.resolve()):
                        raise ValueError("Unsafe tool path")
                    if row.is_dir():
                        output.mkdir(parents=True, exist_ok=True)
                    else:
                        output.parent.mkdir(parents=True, exist_ok=True)
                        with archive.open(row) as inp, output.open("wb") as out:
                            shutil.copyfileobj(inp, out)
                        output.chmod(0o755 if row.external_attr >> 16 & 0o111 else 0o644)
    for folder in (root / "jadx/bin", root / "ghidra/support"):
        for file in folder.iterdir():
            if file.is_file():
                file.chmod(file.stat().st_mode | 0o555)


if __name__ == "__main__":
    install(sys.argv[1] if len(sys.argv) > 1 else "/opt")
