import json
import runpy
import shutil
import sys
from pathlib import Path


def test_license_collection_is_independent_of_windows_default_encoding(tmp_path, monkeypatch):
    root = tmp_path / "project"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    script = scripts / "collect-client-licenses.py"
    shutil.copy2(Path(__file__).parents[1] / "scripts/collect-client-licenses.py", script)
    desktop = root / "clients/desktop"
    desktop.mkdir(parents=True)
    (desktop / "package-lock.json").write_text('{"packages":{}}', encoding="utf-8")
    package = root / "fixture-package"
    package.mkdir()
    license_bytes = "Copyright Ł · permission notice\n".encode()
    (package / "LICENSE").write_bytes(license_bytes)
    metadata = root / "metadata.json"
    metadata.write_text(
        json.dumps(
            {
                "packages": [
                    {
                        "name": "fixture",
                        "version": "1.0.0",
                        "license": "MIT",
                        "authors": ["Ł"],
                        "manifest_path": str(package / "Cargo.toml"),
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8-sig",
    )
    original = Path.read_text

    def windows_default(path, *args, **kwargs):
        kwargs.setdefault("encoding", "cp1252")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", windows_default)
    monkeypatch.setattr(sys, "argv", [str(script), str(metadata)])
    runpy.run_path(str(script), run_name="__main__")
    notices = root / "dist/windows-client/licenses"
    assert (notices / "rust/fixture-1.0.0/LICENSE").read_bytes() == license_bytes
    assert (notices / "THIRD_PARTY_NOTICES.txt").read_text(
        encoding="utf-8"
    ) == "fixture 1.0.0: MIT\n"
