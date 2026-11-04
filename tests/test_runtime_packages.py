import hashlib
import io
import sqlite3
import tarfile
import zipfile
from dataclasses import asdict

import pytest
from fastapi import HTTPException

from dsgpt.catalog import Asset
from dsgpt.downloads import DownloadError, DownloadManager
from dsgpt.migrations import VERSION_2, VERSION_3
from dsgpt.models import ModelRegistry
from dsgpt.runtime import ManagedInference
from dsgpt.runtime_packages import RuntimePackages, RuntimeSpec, host_platform
from dsgpt.storage import APPLICATION_ID, SCHEMA, SCHEMA_VERSION, Store, canonical


def zip_bytes(names=None):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for name, data in names or [("llama-server", b"executable"), ("lib.dll", b"library")]:
            z.writestr(name, data)
    return buffer.getvalue()


def setup(tmp_path, archive=None, suffix=".zip"):
    data = zip_bytes() if archive is None else archive
    asset = Asset(
        "runtime-fixture",
        "Fixture",
        "https://github.com/ggml-org/llama.cpp/releases/download/b1/fixture" + suffix,
        hashlib.sha256(data).hexdigest(),
        len(data),
        "test",
        "test",
        "test",
        suffix,
        "runtime",
    )
    weights = b"GGUF fixture"
    model = Asset(
        "model-fixture",
        "Fixture",
        "https://huggingface.co/test/test/resolve/" + "a" * 40 + "/test.gguf",
        hashlib.sha256(weights).hexdigest(),
        len(weights),
        "test",
        "test",
        "test",
    )
    store = Store(tmp_path)
    downloads = DownloadManager(store, {asset.id: asset, model.id: model}, reserve=0)
    for spec, content in [(asset, data), (model, weights)]:
        row = downloads.submit(spec.id)
        downloads.paths(spec)[1].write_bytes(content)
        downloads.update(row["id"], "downloaded", spec.size)
    spec = RuntimeSpec("runtime-fixture", host_platform(), (asset.id,), "llama-server")
    packages = RuntimePackages(store, downloads, {spec.id: spec})
    runtime = ManagedInference(store, downloads, ModelRegistry(store, {}), packages=packages)
    return runtime, asset, model


async def test_verified_install_attach_restart_reference_guards_and_remove(tmp_path):
    r, archive, weights = setup(tmp_path)
    result = await r.install("runtime-fixture")
    assert result["files_verified"] == 2
    assert (await r.install("runtime-fixture"))["installed"]
    assert r.packages.list()[0]["installed"]
    attached = await r.attach("local", "Fixture", weights.id, "runtime-fixture", 2048, 128)
    assert attached["inference_ready"]
    models = ModelRegistry(r.store, {}).models
    assert models["local"].runtime == "llama.cpp"
    for spec in (archive, weights):
        row = r.store.one("SELECT id FROM downloads WHERE asset_id=?", (spec.id,))
        with pytest.raises(HTTPException) as error:
            r.downloads.remove(row["id"])
        assert error.value.status_code == 409
    with pytest.raises(HTTPException):
        await r.remove("runtime-fixture")
    await r.forget("local")
    await r.remove("runtime-fixture")
    for row in r.downloads.list():
        assert r.downloads.remove(row["id"])["removed"]
    assert not list(r.packages.directory.iterdir())


@pytest.mark.parametrize(
    "name",
    ["../escape", "/absolute", "C:/drive", "x:stream", "CON.dll", "a/../../b", "trail.", "a\\b"],
)
async def test_malicious_archive_names_never_escape_owned_storage(tmp_path, name):
    r, _, _ = setup(tmp_path, zip_bytes([(name, b"bad")]))
    with pytest.raises(DownloadError):
        await r.install("runtime-fixture")
    assert not r.store.all("SELECT * FROM runtime_installations")
    assert not list(r.packages.directory.iterdir())


async def test_archive_symlinks_and_case_aliases_are_rejected(tmp_path):
    info = zipfile.ZipInfo("llama-server")
    info.create_system = 3
    info.external_attr = 0o120777 << 16
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as z:
        z.writestr(info, "/outside")
    r, _, _ = setup(tmp_path / "link", data.getvalue())
    with pytest.raises(DownloadError):
        await r.install("runtime-fixture")
    r, _, _ = setup(tmp_path / "case", zip_bytes([("A", b"a"), ("a", b"b")]))
    with pytest.raises(DownloadError):
        await r.install("runtime-fixture")


async def test_tar_internal_library_links_become_verified_regular_files(tmp_path):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w:gz") as t:
        for name, content in [("llama-server", b"server"), ("lib.so.1", b"library")]:
            entry = tarfile.TarInfo(name)
            entry.size, entry.mode = len(content), 0o755
            t.addfile(entry, io.BytesIO(content))
        for name, target in [("lib.so.0", "lib.so.1"), ("lib.so", "lib.so.0")]:
            entry = tarfile.TarInfo(name)
            entry.type, entry.linkname = tarfile.SYMTYPE, target
            t.addfile(entry)
    r, _, _ = setup(tmp_path, data.getvalue(), ".tar.gz")
    await r.install("runtime-fixture")
    path = r.packages.path("runtime-fixture") / "lib.so"
    assert path.read_bytes() == b"library" and not path.is_symlink()
    await r.packages.verify("runtime-fixture")


@pytest.mark.parametrize("tamper", ["archive", "library", "extra", "missing", "link", "weights"])
async def test_tampering_prevents_install_or_attachment(tmp_path, tamper):
    r, archive, weights = setup(tmp_path)
    if tamper == "archive":
        r.downloads.paths(archive)[1].write_bytes(b"untrusted")
        with pytest.raises(DownloadError):
            await r.install("runtime-fixture")
        return
    await r.install("runtime-fixture")
    path = r.packages.path("runtime-fixture") / "lib.dll"
    if tamper == "library":
        path.write_bytes(b"changed")
    elif tamper == "extra":
        path.with_name("evil.dll").write_bytes(b"added")
    elif tamper == "weights":
        r.downloads.paths(weights)[1].write_bytes(b"GGUF altered")
    else:
        path.unlink()
        if tamper == "link":
            path.symlink_to(r.downloads.paths(weights)[1])
    with pytest.raises((DownloadError, OSError)):
        await r.attach("fixture", "Fixture", weights.id, "runtime-fixture")
    assert not r.store.all("SELECT * FROM managed_models")


async def test_install_and_remove_commit_crash_windows_recover(tmp_path):
    r, _, _ = setup(tmp_path)
    await r.install("runtime-fixture")
    with r.store.transaction() as db:
        db.execute("DELETE FROM runtime_installations")  # Rename-before-commit crash.
    assert (await r.install("runtime-fixture"))["installed"]
    directory = r.packages.path("runtime-fixture")
    directory.rename(r.packages.path("removed-runtime-fixture"))
    await r.packages.verify("runtime-fixture")
    assert directory.exists()


async def test_platform_budget_and_busy_asset_guards(tmp_path, monkeypatch):
    r, asset, model = setup(tmp_path)
    monkeypatch.setattr("dsgpt.runtime_packages.host_platform", lambda: "unsupported")
    with pytest.raises(HTTPException):
        await r.install("runtime-fixture")
    monkeypatch.undo()
    await r.install("runtime-fixture")
    with pytest.raises(HTTPException):
        await r.attach("fixture", "Fixture", model.id, "runtime-fixture", 512, 1024)
    with pytest.raises(HTTPException):
        await r.attach("fixture", "Fixture", model.id, "runtime-fixture", gpu_layers=1)
    r.downloads.busy_assets.add(model.id)
    row = r.store.one("SELECT id FROM downloads WHERE asset_id=?", (model.id,))
    with pytest.raises(HTTPException):
        r.downloads.remove(row["id"])
    async with r.lock:
        with pytest.raises(HTTPException):
            await r.unload()


def test_runtime_controls_deny_ordinary_devices_and_do_not_accept_paths_or_commands(backend):
    from conftest import pair

    phone, _ = pair(backend)
    headers = {"Authorization": "Bearer " + phone["token"]}
    for method, path, body in [
        ("GET", "/v1/runtimes", None),
        ("GET", "/v1/runtime/status", None),
        ("POST", "/v1/runtime/unload", None),
        ("POST", "/v1/runtimes/llama-b11718-linux-x64/install", None),
        ("DELETE", "/v1/runtimes/llama-b11718-linux-x64", None),
        (
            "POST",
            "/v1/models/managed",
            {"id": "a", "name": "A", "asset_id": "b", "runtime_id": "c"},
        ),
    ]:
        assert backend.client.request(method, path, headers=headers, json=body).status_code == 403
    response = backend.client.post(
        "/v1/models/managed",
        json={
            "id": "x",
            "name": "X",
            "asset_id": "a",
            "runtime_id": "b",
            "executable": "/bin/sh",
        },
    )
    assert response.status_code == 422


def test_schema_v3_upgrade_keeps_downloads_and_backs_up(tmp_path):
    r, asset, _ = setup(tmp_path / "fixture")
    directory = tmp_path / "old"
    directory.mkdir()
    with sqlite3.connect(directory / "dsgpt.db") as db:
        db.executescript(SCHEMA + VERSION_2 + VERSION_3)
        db.execute(f"PRAGMA application_id={APPLICATION_ID}")
        db.execute("PRAGMA user_version=3")
        db.execute(
            "INSERT INTO downloads VALUES(?,?,?,?,?,?,?,?)",
            (
                "saved",
                asset.id,
                canonical(asdict(asset)),
                "paused",
                10,
                None,
                "now",
                "now",
            ),
        )
    store = Store(directory)
    assert store.one("PRAGMA user_version")["user_version"] == SCHEMA_VERSION
    assert store.one("SELECT downloaded FROM downloads")["downloaded"] == 10
    backup = next(directory.glob(f"before-v3-to-v{SCHEMA_VERSION}-*.db"))
    with sqlite3.connect(backup) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 3
        assert db.execute("SELECT downloaded FROM downloads").fetchone()[0] == 10
