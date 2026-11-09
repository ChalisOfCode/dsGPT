"""Guest-safe bounded profile validation; no host services or dependencies."""

from pathlib import PurePosixPath

MAX_BYTES = 8 * 1024**2
MAX_ENVELOPE = 12 * 1024**2
MAX_FILES = 512


class AccountProfileError(Exception):
    pass


def validate(files):
    if type(files) is not dict or not 1 <= len(files) <= MAX_FILES:
        raise AccountProfileError("account_profile_invalid")
    total = 0
    for name, data in files.items():
        if (
            type(name) is not str
            or not 1 <= len(name) <= 240
            or any(ord(c) < 32 or ord(c) > 126 for c in name)
            or "\\" in name
            or ":" in name
            or name.startswith("/")
            or str(PurePosixPath(name)) != name
            or any(p in {".", ".."} for p in name.split("/"))
            or name.split("/")[0].startswith("Singleton")
            or type(data) is not bytes
        ):
            raise AccountProfileError("account_profile_invalid")
        total += len(data)
        if total > MAX_BYTES:
            raise AccountProfileError("account_profile_too_large")
    # Reject a file that is also another file's parent.
    if any(str(p) in files for name in files for p in PurePosixPath(name).parents):
        raise AccountProfileError("account_profile_invalid")
