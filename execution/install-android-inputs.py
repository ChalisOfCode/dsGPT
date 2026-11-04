"""Install the exact reviewed Android ZIPs while constructing the toolchain image."""

import hashlib
import stat
import zipfile
from pathlib import Path, PurePosixPath

root = Path("/opt/android")
expected = {
    "sdk-build-tools.zip": "bd3a4966912eb8b30ed0d00b0cda6b6543b949d5ffe00bea54c04c81e1561d88",
    "sdk-platform.zip": "0988cacad01b38a18a47bac14a0695f246bc76c1b06c0eeb8eb0dc825ab0c8e0",
}
for name, digest in expected.items():
    with (root / name).open("rb") as source:
        assert hashlib.file_digest(source, "sha256").hexdigest() == digest
with zipfile.ZipFile(root / "sdk-build-tools.zip") as archive:
    for item in archive.infolist():
        path = PurePosixPath(item.filename)
        assert not path.is_absolute() and ".." not in path.parts
        assert path.parts[0] == "android-15" and len(path.parts) > 1
        assert not stat.S_ISLNK(item.external_attr >> 16)
        target = root / "build-tools" / Path(*path.parts[1:])
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(item))
with zipfile.ZipFile(root / "sdk-platform.zip") as archive:
    candidates = [n for n in archive.namelist() if n.endswith("/android.jar")]
    assert len(candidates) == 1
    (root / "platform/android.jar").write_bytes(archive.read(candidates[0]))
for name in expected:
    (root / name).unlink()
