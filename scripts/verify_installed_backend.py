"""Verify the wheel installation before using it for the real integration gates."""

import argparse
import hashlib
import json
import sys
import tempfile
import tomllib
from pathlib import Path

from fastapi.testclient import TestClient

import dsgpt
from dsgpt.api import create_app
from dsgpt.config import Settings
from dsgpt.storage import SCHEMA_VERSION


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    installed = Path(dsgpt.__file__).resolve().parent
    assert installed.is_relative_to(Path(sys.prefix).resolve()), "Package is outside the check venv"
    assert not installed.is_relative_to(root), "Imported the source checkout instead of the wheel"
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    assert dsgpt.__version__ == version
    hashes = {}
    for source in sorted((root / "src/dsgpt").glob("*.py")):
        assert (installed / source.name).read_bytes() == source.read_bytes(), source.name
        hashes[source.name] = hashlib.sha256(source.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="dsgpt-installed-check-") as directory:
        app = create_app(Settings(Path(directory), {}, allowed_hosts=("testserver",)))
        owner = app.state.auth.initialize_owner()
        assert app.openapi()["info"]["version"] == version
        schema = app.state.store.one("PRAGMA user_version")["user_version"]
        assert schema == SCHEMA_VERSION
        with TestClient(app) as client:
            assert client.get("/health").status_code == 200
            assert client.get("/v1/work/sandbox").status_code == 401
            client.headers["Authorization"] = "Bearer " + owner["token"]
            assert client.get("/v1/work/sandbox").status_code == 200
    report = {
        "passed": True,
        "version": version,
        "schema": schema,
        "independent_wheel_installation": True,
        "installed_source_sha256": hashes,
        "health_and_authenticated_build_api": "passed",
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Verified installed backend {version}, schema {schema}, all {len(hashes)} modules")


if __name__ == "__main__":
    main()
