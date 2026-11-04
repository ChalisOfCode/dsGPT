"""Install pinned public SDK/Gradle inputs while constructing the reviewed image."""

import hashlib
import shutil
import stat
import sys
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

INPUTS = (
    (
        "build-tools_r35_linux.zip",
        "https://dl.google.com/android/repository/build-tools_r35_linux.zip",
        61958799,
        "bd3a4966912eb8b30ed0d00b0cda6b6543b949d5ffe00bea54c04c81e1561d88",
        "android/build-tools/35.0.0",
        True,
    ),
    (
        "platform-35_r02.zip",
        "https://dl.google.com/android/repository/platform-35_r02.zip",
        64273788,
        "0988cacad01b38a18a47bac14a0695f246bc76c1b06c0eeb8eb0dc825ab0c8e0",
        "android/platforms/android-35",
        True,
    ),
    (
        "gradle-8.13-bin.zip",
        "https://services.gradle.org/distributions/gradle-8.13-bin.zip",
        136983045,
        "20f1b1176237254a6fc204d8434196fa11a4cfb387567519c61556e8710aed78",
        "gradle",
        False,
    ),
)


def install(root):
    root = Path(root)
    cache = root / "downloads"
    cache.mkdir(parents=True, exist_ok=True)
    for name, url, size, expected, directory, strip in INPUTS:
        archive_path = cache / name
        if (
            not archive_path.is_file()
            or archive_path.stat().st_size != size
            or hashlib.sha256(archive_path.read_bytes()).hexdigest() != expected
        ):
            total, digest = 0, hashlib.sha256()
            temporary = archive_path.with_suffix(".partial")
            print("Downloading verified toolchain input: " + name, flush=True)
            with (
                urllib.request.urlopen(url, timeout=60) as response,
                temporary.open("wb") as output,
            ):
                while block := response.read(1024 * 1024):
                    total += len(block)
                    if total > size:
                        raise ValueError("Toolchain input exceeds reviewed size: " + name)
                    digest.update(block)
                    output.write(block)
            if total != size or digest.hexdigest() != expected:
                raise ValueError("Toolchain input failed SHA256/size verification: " + name)
            temporary.replace(archive_path)
        destination = root / directory
        destination.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive_path) as archive:
            if sum(i.file_size for i in archive.infolist()) > 1024**3:
                raise ValueError("Toolchain extraction exceeds size bound")
            for item in archive.infolist():
                path = PurePosixPath(item.filename)
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or stat.S_ISLNK(item.external_attr >> 16)
                ):
                    raise ValueError("Unsafe toolchain archive entry")
                parts = path.parts[1:] if strip else path.parts
                if not parts:
                    continue
                output = destination.joinpath(*parts)
                if not output.resolve().is_relative_to(destination.resolve()):
                    raise ValueError("Unsafe toolchain target")
                if item.is_dir():
                    output.mkdir(parents=True, exist_ok=True)
                else:
                    output.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(item) as source, output.open("wb") as target:
                        shutil.copyfileobj(source, target)
                    output.chmod(0o755 if item.external_attr >> 16 & 0o111 else 0o644)
        for executable in ("aapt", "aapt2", "d8", "apksigner", "zipalign"):
            path = destination / executable
            if path.is_file():
                path.chmod(0o755)
    licenses = root / "android/licenses"
    licenses.mkdir(exist_ok=True)
    (licenses / "android-sdk-license").write_text(
        "8933bad161af4178b1185d1a37fbf41ea5269c55\nd56f5187479451eabf01fb78af6dfcb131a6481e\n24333f8a63b6825ea9c5514f83c2829b004d1fee\n"
    )
    print("Android SDK 35 and Gradle 8.13 verified", flush=True)


if __name__ == "__main__":
    install(sys.argv[1] if len(sys.argv) > 1 else "/opt")
