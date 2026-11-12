"""Old delivered installer -> candidate on a disposable Windows runner only.

Inputs and the private receipt stay outside the checkout/artifact directories.
No model is downloaded or invoked. This checks preservation and authenticated
reconnect, not inference quality, physical hardware or Tailscale connectivity.
"""

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import time
import uuid
from pathlib import Path

TABLE_KEYS = {"conversations": "id", "messages": "id", "work_tasks": "id",
              "devices": "id", "work_files": "task_id,path"}

BASELINE_SHA256 = "99d879e7f7f4e415fb2e54a0ed4c45c184196235c119f6e58b6686dc38b13a9a"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require_runner():
    if os.name != "nt" or os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("Upgrade acceptance requires disposable Windows Actions")
    if os.environ.get("GITHUB_REPOSITORY") != "ChalisOfCode/dsGPT":
        raise RuntimeError("Unexpected acceptance repository")


def snapshot(database):
    # Fixed inert synthetic rows; no tokens, paths or raw messages go to reports.
    with sqlite3.connect(database) as db:
        result = {}
        for table, order in TABLE_KEYS.items():
            columns = [row[1] for row in db.execute(f"PRAGMA table_info({table})")]
            rows = db.execute(f"SELECT * FROM {table} ORDER BY {order}").fetchall()
            result[table] = {"columns": columns, "rows": rows}
        return result


def check_snapshot(database, expected):
    with sqlite3.connect(database) as db:
        for table, record in expected.items():
            if table not in TABLE_KEYS:
                raise ValueError("Unexpected snapshot table")
            columns = record["columns"]
            if not columns or any(not re.fullmatch(r"[a-z_]+", c) for c in columns):
                raise ValueError("Unexpected snapshot column")
            # New additive columns are allowed; every old value must match exactly.
            rows = db.execute(
                f"SELECT {','.join(columns)} FROM {table} ORDER BY {TABLE_KEYS[table]}"
            ).fetchall()
            if [list(row) for row in rows] != [list(row) for row in record["rows"]]:
                raise AssertionError("Original database records changed")
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise AssertionError("Upgraded database is invalid")
        if db.execute("PRAGMA foreign_key_check").fetchone():
            raise AssertionError("Upgraded database references are invalid")


def check_identity(actual, expected):
    # Compare authority as well as ID: reconnect must not silently broaden access.
    if (actual.get("id") != expected.get("id")
            or actual.get("role") != expected.get("role")
            or sorted(actual.get("scopes", [])) != sorted(expected.get("scopes", []))):
        raise AssertionError("Paired identity or authority changed")


def manifest(install_dir, expected_source=None):
    value = json.loads((install_dir / "application-manifest.json").read_text())
    source = value.get("source_commit")
    if not isinstance(source, str) or not re.fullmatch(r"[a-f0-9]{40}", source):
        raise ValueError("Installed source provenance missing")
    if expected_source is not None and source != expected_source:
        raise ValueError("Installed candidate source differs from tested source")
    for name, record in value["files"].items():
        path = install_dir / name
        if (not path.resolve().is_relative_to(install_dir.resolve()) or path.is_symlink()
                or not path.is_file() or path.stat().st_size != record["bytes"]
                or digest(path) != record["sha256"]):
            raise ValueError("Installed payload integrity failed")
    return source


def native_history(install_dir, directory, private, identifier, seed):
    """Launch each installed native client, without model downloads or inference."""
    import httpx
    from dsgpt_acceptance.__main__ import port
    from dsgpt_acceptance.cdp import CDP

    from dsgpt import managed
    from dsgpt.bootstrap import WindowsVault

    desktop = WindowsVault(directory, target="backend-connection.dsGPT-acceptance-" + identifier,
                           encoding="utf-16-le")
    if seed:
        managed.wire_desktop(WindowsVault(directory), desktop)
    # On upgrade do not repair/reseed even this isolated native-view credential.
    if desktop.read() != WindowsVault(directory, target=managed.CLIENT_TARGET,
                                      encoding="utf-16-le").read():
        raise AssertionError("Native-view credential was not preserved")
    debug_port = port()
    env = dict(os.environ, DSGPT_ACCEPTANCE_RUN_ID=identifier,
               DSGPT_ACCEPTANCE_DEBUG_PORT=str(debug_port),
               DSGPT_ACCEPTANCE_PROFILE=str(private / "upgrade-native-profile"))
    child = subprocess.Popen([str(install_dir / "client/dsGPT.exe")], env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    cdp = None
    try:
        deadline = time.monotonic() + 60
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=3) as client:
            while time.monotonic() < deadline:
                if child.poll() is not None:
                    raise AssertionError("Installed native client exited")
                try:
                    pages = client.get(f"http://127.0.0.1:{debug_port}/json/list").json()
                    page = next(p for p in pages if p.get("type") == "page")
                    cdp = CDP(page["webSocketDebuggerUrl"])
                    break
                except (httpx.HTTPError, ValueError, StopIteration, OSError):
                    time.sleep(0.25)
        if cdp is None:
            raise AssertionError("Installed native window did not open")
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            visible = cdp.evaluate(
                "document.body.innerText.includes('Synthetic prior-release conversation')")
            if visible:
                origin = cdp.evaluate("window.__TAURI_INTERNALS__.invoke('restore_connection')")
                if origin != managed.ORIGIN:
                    raise AssertionError("Installed native connection differs")
                return
            time.sleep(0.25)
        raise AssertionError("Prior conversation not visible in installed native client")
    finally:
        if cdp:
            cdp.close()
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=20)


def preserved_model_file(directory, expected=None):
    # Inert filesystem sentinel, explicitly not a model or inference fixture.
    path = directory / "managed-models" / "upgrade-preservation-fixture.bin"
    if expected is None:
        path.parent.mkdir(exist_ok=True)
        with path.open("xb") as output:
            output.write(b"dsGPT synthetic retained model-directory bytes\n" * 128)
        return {"bytes": path.stat().st_size, "sha256": digest(path)}
    if (not path.is_file() or path.is_symlink() or path.stat().st_size != expected["bytes"]
            or digest(path) != expected["sha256"]):
        raise AssertionError("Model-directory fixture bytes changed")
    return expected


def phase(args):
    # -I loads the ACTUAL installed old/candidate backend, never checkout source.
    import httpx

    from dsgpt import managed
    from dsgpt.bootstrap import WindowsVault
    from dsgpt.storage import Store, uid, utcnow
    from dsgpt.windows_security import private_directory

    directory = managed.managed_directory()
    private_directory(args.private)
    if not Path(managed.__file__).resolve().is_relative_to(args.install_dir.resolve()):
        raise RuntimeError("Acceptance imported a non-installed backend")
    source = manifest(args.install_dir, args.source if args.phase == "candidate" else None)
    receipt_path = args.private / "upgrade-receipt.json"
    before = json.loads(receipt_path.read_text()) if args.phase == "candidate" else None
    vault = managed.start(directory, args.install_dir)
    try:
        owner = vault.read()
        desktop = WindowsVault(directory, target=managed.CLIENT_TARGET, encoding="utf-16-le")
        if before is None:
            managed.wire_desktop(vault, desktop)
            chat = managed.owner_request(directory, "POST", "/v1/conversations", {
                "title": "Synthetic prior-release conversation"})
            task = managed.owner_request(directory, "POST", "/v1/work/tasks", {
                "title": "Synthetic prior-release Work", "requirements": "Preserve café 原文",
                "source_files": [{"name": "original.txt", "text": "Original café 原文\n"}]})
            code = managed.owner_request(directory, "POST", "/v1/pairings", {
                "scopes": ["chat", "work", "diagnostics"]})["code"]
            with httpx.Client(trust_env=False, follow_redirects=False, timeout=10) as client:
                response = client.post(managed.ORIGIN + "/v1/pairings/redeem", json={
                    "code": code, "name": "Synthetic upgrade device"})
                response.raise_for_status()
                paired = response.json()
            before = {"source": source, "chat_id": chat["id"], "task_id": task["id"],
                      "owner_sha256": hashlib.sha256(owner["token"].encode()).hexdigest(),
                      "desktop": desktop.read(), "paired_token": paired["token"],
                      "native_id": uuid.uuid4().hex,
                      "model_directory_fixture": preserved_model_file(directory)}
        else:
            if source == before["source"]:
                raise AssertionError("Same-version reinstall is not upgrade acceptance")
            if hashlib.sha256(owner["token"].encode()).hexdigest() != before["owner_sha256"]:
                raise AssertionError("Owner credential changed")
            # Do not wire/repair here: a surviving desktop credential must already exist.
            if desktop.read() != before["desktop"]:
                raise AssertionError("Desktop credential changed")
            preserved_model_file(directory, before["model_directory_fixture"])
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=10) as client:
            headers = {"Authorization": "Bearer " + before["paired_token"]}
            identity = client.get(managed.ORIGIN + "/v1/device", headers=headers)
            identity.raise_for_status()
            if args.phase == "baseline":
                before["device_identity"] = {
                    key: identity.json()[key] for key in ("id", "role", "scopes")}
            else:
                check_identity(identity.json(), before["device_identity"])
            for path in ("/v1/conversations/" + before["chat_id"] + "/messages",
                         "/v1/work/tasks/" + before["task_id"]):
                client.get(managed.ORIGIN + path, headers=headers).raise_for_status()
        native_history(args.install_dir, directory, args.private, before["native_id"],
                       seed=args.phase == "baseline")
    finally:
        managed.stop(directory)
    store = Store(directory)
    if args.phase == "baseline":
        # Synthetic persisted content is seeded through the actual OLD schema,
        # not presented as a generated model response.
        with store.transaction() as db:
            db.execute("INSERT INTO messages(id,conversation_id,role,content,status,ordinal,"
                       "created_at) VALUES(?,?,?,?,?,?,?)", (
                           uid(), before["chat_id"], "user", "Original café 原文", "completed", 1,
                           utcnow()))
            before["schema"] = db.execute("PRAGMA user_version").fetchone()[0]
        before["snapshot"] = snapshot(store.path)
        receipt_path.write_text(json.dumps(before), encoding="utf-8")
    else:
        check_snapshot(store.path, before["snapshot"])
        with store.connect() as db:
            schema = db.execute("PRAGMA user_version").fetchone()[0]
        if schema <= before["schema"]:
            raise AssertionError("Prior schema was not upgraded")
        backups = list(directory.glob(f"before-v{before['schema']}-to-v{schema}-*.db"))
        if len(backups) != 1:
            raise AssertionError("Expected one checked prior-schema backup")
        check_snapshot(backups[0], before["snapshot"])
        # A second real backend start must preserve credentials and paired access.
        managed.start(directory, args.install_dir)
        try:
            with httpx.Client(trust_env=False, follow_redirects=False, timeout=10) as client:
                response = client.get(managed.ORIGIN + "/v1/device", headers={
                    "Authorization": "Bearer " + before["paired_token"]})
                response.raise_for_status()
                check_identity(response.json(), before["device_identity"])
        finally:
            managed.stop(directory)
        check_snapshot(store.path, before["snapshot"])
        args.report.write_text(json.dumps({
            "baseline_source": before["source"], "candidate_source": source,
            "baseline_installer_sha256": BASELINE_SHA256,
            "old_schema": before["schema"], "new_schema": schema,
            "old_rows_and_imported_work_source_preserved": True, "migration_backup_verified": True,
            "owner_and_desktop_credentials_preserved": True,
            "paired_identity_and_scopes_reconnected": True, "backend_restart_passed": True,
            "old_and_candidate_native_history_visible": True,
            "synthetic_model_directory_bytes_preserved": True,
            "scope": "Installed Windows backend/native UI; no model or physical/Tailscale claim."
        }, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--candidate-sha256")
    parser.add_argument("--source", required=True)
    parser.add_argument("--install-dir", type=Path, required=True)
    parser.add_argument("--private", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--phase", choices=("baseline", "candidate"))
    args = parser.parse_args()
    require_runner()
    if not re.fullmatch(r"[a-f0-9]{40}", args.source):
        raise ValueError("Exact candidate source required")
    runner_temp = Path(os.environ["RUNNER_TEMP"]).resolve()
    if any(not path.resolve().is_relative_to(runner_temp) or path.resolve() == runner_temp
           for path in (args.install_dir, args.private)):
        raise ValueError("Installation and private receipt must remain in owned runner paths")
    if args.phase:
        phase(args)
        return
    if digest(args.baseline) != BASELINE_SHA256:
        raise ValueError("Prior delivered installer hash mismatch")
    if (not args.candidate_sha256
            or not re.fullmatch(r"[a-f0-9]{64}", args.candidate_sha256)
            or digest(args.candidate) != args.candidate_sha256):
        raise ValueError("Exact reviewed candidate installer hash required")
    if args.candidate_sha256 == BASELINE_SHA256:
        raise ValueError("Upgrade candidate equals old installer")
    data = Path(os.environ["LOCALAPPDATA"]) / "dsGPT/managed/data"
    if data.exists() or args.install_dir.exists() or args.private.exists():
        raise RuntimeError("Acceptance requires a fresh disposable profile and paths")
    args.private.mkdir(parents=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    for name, installer in (("baseline", args.baseline), ("candidate", args.candidate)):
        print("Checking installed upgrade phase:", name, flush=True)
        subprocess.run(subprocess.list2cmdline([str(installer.resolve()), "/S", "/NOSETUP"])
                       + " /D=" + str(args.install_dir.resolve()), check=True, timeout=180)
        subprocess.run([
            str(args.install_dir / "python/python.exe"), "-B", "-I", str(Path(__file__).resolve()),
            "--phase", name, "--source", args.source, "--install-dir", str(args.install_dir),
            "--private", str(args.private), "--report", str(args.report)
        ], check=True, timeout=180, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("Old-to-candidate installed backend preservation and reconnect passed.")


if __name__ == "__main__":
    main()
