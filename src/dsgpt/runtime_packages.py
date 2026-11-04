"""Install only reviewed, digest-pinned runtime archives in private owned storage."""

import asyncio
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import tarfile
import zipfile
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath

from fastapi import HTTPException

from .catalog import Asset
from .downloads import DownloadError, secure_file
from .storage import canonical, utcnow


@dataclass(frozen=True)
class RuntimeSpec:
    id: str
    platform: str
    assets: tuple[str, ...]
    executable: str
    strip_prefix: str = ""


RUNTIMES = {
    r.id: r
    for r in [
        RuntimeSpec(
            "llama-b11718-linux-x64",
            "linux-x64",
            ("llama-b11718-linux-x64",),
            "llama-server",
            "llama-b11718/",
        ),
        RuntimeSpec(
            "llama-b11718-windows-cuda12",
            "windows-x64",
            ("llama-b11718-windows-cuda12", "llama-b11718-windows-cudart12"),
            "llama-server.exe",
        ),
    ]
}


def host_platform():
    machine = platform.machine().lower()
    return f"{platform.system().lower()}-{'x64' if machine in {'x86_64', 'amd64'} else machine}"


def safe_name(name):
    """One canonical portable name; no aliases, ADS, devices, traversal or case collisions."""
    parts = name.split("/")
    if (
        not name
        or len(name) > 220
        or any(
            not re.fullmatch(r"[A-Za-z0-9_.-]+", p)
            or p in {".", ".."}
            or p.endswith((".", " "))
            or p.split(".")[0].upper()
            in {
                "CON",
                "PRN",
                "AUX",
                "NUL",
                *(f"{prefix}{n}" for prefix in ("COM", "LPT") for n in range(1, 10)),
            }
            for p in parts
        )
    ):
        raise DownloadError("unsafe_runtime_archive")
    return name


def safe_directory(path):
    info = path.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_mode & stat.S_ISUID
        or getattr(info, "st_file_attributes", 0) & 0x400
    ):
        raise DownloadError("unsafe_storage")


def remove_owned_tree(path):
    """Only called on a fixed child of our private runtime directory. Never follow links."""
    safe_directory(path)
    for child in path.iterdir():
        info = child.lstat()
        if stat.S_ISDIR(info.st_mode):
            remove_owned_tree(child)
        else:
            with secure_file(child, os.O_RDONLY):
                pass
            child.unlink()
    path.rmdir()


async def hash_file(path):
    digest, size = hashlib.sha256(), 0
    with secure_file(path, os.O_RDONLY) as file:
        while block := file.read(1024**2):
            size += len(block)
            digest.update(block)
            await asyncio.sleep(0)
    return {"sha256": digest.hexdigest(), "size": size}


class RuntimePackages:
    def __init__(self, store, downloads, specs=None):
        self.store, self.downloads = store, downloads
        self.specs = RUNTIMES if specs is None else specs
        self.directory = store.directory / "managed-runtimes"
        if not self.directory.exists():
            self.directory.mkdir(mode=0o700)
        safe_directory(self.directory)

    def path(self, identifier):
        safe_directory(self.directory)
        safe_name(identifier)
        if "/" in identifier:
            raise DownloadError("unsafe_storage")
        return self.directory / identifier

    def spec(self, identifier, require_host=True):
        spec = self.specs.get(identifier)
        if not spec:
            raise HTTPException(404, "Runtime is not in the reviewed catalog")
        if require_host and spec.platform != host_platform():
            raise HTTPException(409, "Runtime does not match this backend platform")
        return spec

    def list(self):
        return [
            {
                **asdict(spec),
                "supported_here": spec.platform == host_platform(),
                "installed": bool(
                    self.store.one("SELECT id FROM runtime_installations WHERE id=?", (spec.id,))
                ),
            }
            for spec in self.specs.values()
        ]

    def downloaded(self, identifier, kind):
        row = self.store.one("SELECT * FROM downloads WHERE asset_id=?", (identifier,))
        if not row or row["status"] != "downloaded":
            raise HTTPException(409, "Required asset has not finished downloading")
        asset = Asset(**json.loads(row["definition"]))
        if asset.kind != kind or asset != self.downloads.catalog.get(identifier):
            raise DownloadError("catalog_changed")
        return asset, self.downloads.paths(asset)[1]

    async def install(self, identifier):
        spec = self.spec(identifier)
        if self.store.one("SELECT id FROM runtime_installations WHERE id=?", (identifier,)):
            await self.verify(identifier)
            return {"id": identifier, "installed": True}
        target, stage = self.path(identifier), self.path("stage-" + identifier)
        removed = self.path("removed-" + identifier)
        if removed.exists() or removed.is_symlink():
            remove_owned_tree(removed)
        self.downloads.busy_assets.update(spec.assets)
        try:
            assets = [self.downloaded(key, "runtime") for key in spec.assets]
            for asset, path in assets:
                await self.downloads.verify(path, asset)
            if stage.exists() or stage.is_symlink():
                remove_owned_tree(stage)
            stage.mkdir(mode=0o700)
            manifest = {}
            for asset, path in assets:
                await self.extract(path, asset, spec, stage, manifest)
            if spec.executable not in manifest:
                raise DownloadError("runtime_executable_missing")
            if target.exists() or target.is_symlink():
                # Recover an interrupted rename-before-DB-commit only if every byte matches.
                await self.verify_tree(target, manifest)
                remove_owned_tree(stage)
            else:
                stage.rename(target)
            with self.store.transaction() as db:
                db.execute(
                    "INSERT INTO runtime_installations VALUES(?,?,?,?)",
                    (
                        identifier,
                        canonical(asdict(spec)),
                        canonical(manifest),
                        utcnow(),
                    ),
                )
                db.executemany(
                    "INSERT INTO runtime_sources VALUES(?,?)",
                    [(identifier, key) for key in spec.assets],
                )
            return {"id": identifier, "installed": True, "files_verified": len(manifest)}
        except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile) as exc:
            raise DownloadError("runtime_install_failed") from exc
        finally:
            self.downloads.busy_assets.difference_update(spec.assets)
            if stage.exists():
                remove_owned_tree(stage)

    async def extract(self, path, asset, spec, stage, manifest):
        # Internal tar library links become independent regular files; never create links.
        # Resolve against archive entries, not the filesystem, with bounded chain depth.
        with secure_file(path, os.O_RDONLY) as archive_file:
            if asset.suffix == ".zip":
                archive = zipfile.ZipFile(archive_file)
                entries = archive.infolist()
                names = [entry.filename for entry in entries]
            else:
                archive = tarfile.open(fileobj=archive_file, mode="r:gz")
                entries = archive.getmembers()
                names = [entry.name for entry in entries]
            with archive:
                if len(entries) > 1000 or len(set(names)) != len(names):
                    raise DownloadError("unsafe_runtime_archive")
                indexed = dict(zip(names, entries, strict=True))
                prepared = []
                for name, entry in indexed.items():
                    is_dir = entry.is_dir() if asset.suffix == ".zip" else entry.isdir()
                    if name.rstrip("/") == spec.strip_prefix.rstrip("/") and is_dir:
                        continue
                    if spec.strip_prefix and not name.startswith(spec.strip_prefix):
                        raise DownloadError("unsafe_runtime_archive")
                    relative = safe_name(
                        name[len(spec.strip_prefix) :].rstrip("/")
                        if is_dir
                        else name[len(spec.strip_prefix) :]
                    )
                    if is_dir:
                        continue
                    if asset.suffix == ".zip":
                        mode = entry.external_attr >> 16
                        if stat.S_IFMT(mode) not in {0, stat.S_IFREG} or entry.flag_bits & 1:
                            raise DownloadError("unsafe_runtime_archive")
                        size = entry.file_size
                        executable = False
                    else:
                        resolved = entry
                        for _ in range(8):
                            if not resolved.issym():
                                break
                            link = safe_name(
                                str(
                                    PurePosixPath(resolved.name).parent
                                    / safe_name(resolved.linkname)
                                )
                            )
                            resolved = indexed.get(link)
                            if resolved is None:
                                raise DownloadError("unsafe_runtime_archive")
                        if not resolved.isfile():
                            raise DownloadError("unsafe_runtime_archive")
                        entry = resolved
                        size, executable = entry.size, bool(entry.mode & 0o111)
                    if relative.casefold() in {
                        k.casefold() for k in manifest
                    } or relative.casefold() in {p[0].casefold() for p in prepared}:
                        raise DownloadError("unsafe_runtime_archive")
                    prepared.append((relative, entry, size, executable))
                total = sum(p[2] for p in prepared)
                if total > 4 * 1024**3 or total < 1:
                    raise DownloadError("runtime_archive_size_invalid")
                if shutil.disk_usage(stage).free < total + self.downloads.reserve:
                    raise DownloadError("insufficient_disk_space")
                for relative, entry, size, executable in prepared:
                    dest = stage / relative
                    dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    digest, count = hashlib.sha256(), 0
                    source = (
                        archive.open(entry)
                        if asset.suffix == ".zip"
                        else archive.extractfile(entry)
                    )
                    with source, secure_file(dest, os.O_CREAT | os.O_EXCL | os.O_RDWR) as output:
                        while block := source.read(1024**2):
                            count += len(block)
                            if count > size:
                                raise DownloadError("runtime_archive_size_invalid")
                            output.write(block)
                            digest.update(block)
                            await asyncio.sleep(0)
                        os.fsync(output.fileno())
                    if count != size:
                        raise DownloadError("runtime_archive_size_invalid")
                    if executable:
                        dest.chmod(0o700)
                    manifest[relative] = {
                        "sha256": digest.hexdigest(),
                        "size": size,
                        "executable": executable,
                    }

    async def verify_tree(self, directory, manifest):
        safe_directory(directory)
        observed = set()
        for parent, dirs, files in os.walk(directory, followlinks=False):
            for name in dirs:
                safe_directory(type(directory)(parent) / name)
            for name in files:
                path = type(directory)(parent) / name
                key = path.relative_to(directory).as_posix()
                expected = manifest.get(key)
                if (
                    not expected
                    or await hash_file(path) != {k: expected[k] for k in ("sha256", "size")}
                    or (
                        os.name != "nt"
                        and bool(path.stat().st_mode & 0o111) != expected["executable"]
                    )
                ):
                    raise DownloadError("runtime_integrity_failed")
                observed.add(key)
        if observed != manifest.keys():
            raise DownloadError("runtime_integrity_failed")

    async def verify(self, identifier):
        spec = self.spec(identifier)
        row = self.store.one("SELECT * FROM runtime_installations WHERE id=?", (identifier,))
        if not row:
            raise HTTPException(409, "Install the runtime before attaching a model")
        if row["definition"] != canonical(asdict(spec)):
            raise DownloadError("catalog_changed")
        directory, removed = self.path(identifier), self.path("removed-" + identifier)
        manifest = json.loads(row["manifest"])
        if not directory.exists() and removed.exists():
            # Interrupted removal before database commit: restore the verified installation.
            await self.verify_tree(removed, manifest)
            removed.rename(directory)
        try:
            await self.verify_tree(directory, manifest)
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise DownloadError("runtime_integrity_failed") from exc
        return self.path(identifier) / spec.executable

    async def remove(self, identifier):
        self.spec(identifier)
        if self.store.one("SELECT model_id FROM managed_models WHERE runtime_id=?", (identifier,)):
            raise HTTPException(409, "Forget attached models before removing this runtime")
        await self.verify(identifier)
        removed = self.path("removed-" + identifier)
        if removed.exists() or removed.is_symlink():
            raise DownloadError("unsafe_storage")
        self.path(identifier).rename(removed)
        with self.store.transaction() as db:
            db.execute("DELETE FROM runtime_installations WHERE id=?", (identifier,))
        remove_owned_tree(removed)
        return {"removed": True, "source_archives_retained": True}
