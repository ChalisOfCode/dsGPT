"""Package exactly the verified kit manifest, excluding runtime bytecode caches."""

import argparse
import hashlib
import json
import tempfile
import zipfile
from pathlib import Path, PurePosixPath


def package_kit(kit: Path, output: Path) -> dict:
    kit = kit.resolve(strict=True)
    output = output.resolve()
    if output.is_relative_to(kit):
        raise ValueError("Write the release archive outside the kit")
    manifest_path = kit / "kit-manifest.json"
    if manifest_path.is_symlink():
        raise ValueError("Kit must not contain symbolic links")
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    files = manifest["files"]
    if not isinstance(files, dict) or not files:
        raise ValueError("Kit manifest must contain files")
    names = {"kit-manifest.json"}
    for name in files:
        path = PurePosixPath(name)
        if (
            not name
            or path.is_absolute()
            or str(path) != name
            or ".." in path.parts
            or "\\" in name
            or ":" in name
            or name.casefold() in names
        ):
            raise ValueError("Invalid or duplicate kit manifest path")
        names.add(name.casefold())

    expected = set(files) | {"kit-manifest.json"}
    actual = set()
    excluded = []
    for path in kit.rglob("*"):
        if path.is_symlink():
            raise ValueError("Kit must not contain symbolic links")
        if path.is_file():
            name = path.relative_to(kit).as_posix()
            actual.add(name)
            if name not in expected:
                if "__pycache__" in path.relative_to(kit).parts and path.suffix == ".pyc":
                    excluded.append(name)
                else:
                    raise ValueError("Unexpected kit file: " + name)
    missing = expected - actual
    if missing:
        raise ValueError("Missing kit file: " + sorted(missing)[0])

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, suffix=".partial", delete=False) as f:
        temporary = Path(f.name)
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for name in sorted(expected):
                # Hash the exact bytes written to the ZIP, not a preceding read.
                data = manifest_bytes if name == "kit-manifest.json" else (kit / name).read_bytes()
                if name in files:
                    record = files[name]
                    if (
                        len(data) != record["bytes"]
                        or hashlib.sha256(data).hexdigest() != record["sha256"]
                    ):
                        raise ValueError("Kit integrity check failed: " + name)
                entry = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.create_system = 3
                entry.external_attr = 0o100644 << 16
                archive.writestr(entry, data)
        with temporary.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        temporary.replace(output)
        output.with_suffix(".sha256").write_text(digest + "\n", encoding="ascii")
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "source_commit": manifest["source_commit"],
        "manifest_files": len(files),
        "archive_files": len(expected),
        "excluded_runtime_caches": len(excluded),
        "sha256": digest,
        "bytes": output.stat().st_size,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(package_kit(args.kit, args.output), indent=2))


if __name__ == "__main__":
    main()
