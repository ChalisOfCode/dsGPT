"""Portable speech package integrity, including the reviewed SRT data files."""

import importlib.util
import json
import sys
import zipfile
from pathlib import Path

import pytest


@pytest.fixture
def builders(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root / "scripts"))
    modules = []
    for name in ("build_windows_bundle", "build_acceptance_kit"):
        spec = importlib.util.spec_from_file_location(name, root / "scripts" / (name + ".py"))
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        modules.append(module)
    return root, *modules


def test_vendored_srt_is_verified_and_keeps_cli_unregistered(builders, tmp_path):
    root, bundle, kit = builders
    record = next(
        r
        for r in json.loads((root / "requirements-windows.lock.json").read_text())["wheels"]
        if r["name"] == "srt"
    )
    wheel = kit.fetch(record, tmp_path)
    output = tmp_path / "site-packages"
    bundle.extract(wheel, output, wheel=True)
    assert (output / "srt.py").is_file()
    assert (output / "srt-3.5.3.dist-info/licenses/LICENSE").is_file()
    assert (output / "srt-3.5.3.data/scripts/srt").is_file()
    assert not (tmp_path / "Scripts").exists()
    with pytest.raises(ValueError, match="pinned SHA256"):
        kit.fetch({**record, "sha256": "0" * 64}, tmp_path)


def test_other_wheel_relocation_remains_rejected(builders, tmp_path):
    _, bundle, _ = builders
    bad = tmp_path / "unreviewed.whl"
    with zipfile.ZipFile(bad, "w") as wheel:
        wheel.writestr("srt-3.5.3.data/purelib/unreviewed.py", "print('unexpected')")
    with pytest.raises(ValueError, match="relocation"):
        bundle.extract(bad, tmp_path / "site", wheel=True)
    assert not (tmp_path / "site").exists()
