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
from pathlib import Path

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
        for table in ("conversations", "messages", "work_tasks", "devices"):
            columns = [row[1] for row in db.execute(f"PRAGMA table_info({table})")]
            rows = db.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
            result[table] = {"columns": columns, "rows": rows}
        return result


def check_snapshot(database, expected):
    with sqlite3.connect(database) as db:
        for table, record in expected.items():
            if table not in {"conversations", "messages", "work_tasks", "devices"}:
                raise ValueError("Unexpected snapshot table")
            columns = record["columns"]
            if not columns or any(not re.fullmatch(r"[a-z_]+", c) for c in columns):
                raise ValueError("Unexpected snapshot column")
            # New additive columns are allowed; every old value must match exactly.
            rows = db.execute(f"SELECT {','.join(columns)} FROM {table} ORDER BY id").fetchall()
            if [list(row) for row in rows] != [list(row) for row in record["rows"]]:
                raise AssertionError("Original database records changed")
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise AssertionError("Upgraded database is invalid")
        if db.execute("PRAGMA foreign_key_check").fetchone():
            raise AssertionError("Upgraded database references are invalid")


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
                "title": "Synthetic prior-release Work", "requirements": "Preserve café 原文"})
            code = managed.owner_request(directory, "POST", "/v1/pairings", {
                "scopes": ["chat", "work", "diagnostics"]})["code"]
            with httpx.Client(trust_env=False, follow_redirects=False, timeout=10) as client:
                response = client.post(managed.ORIGIN + "/v1/pairings/redeem", json={
                    "code": code, "name": "Synthetic upgrade device"})
                response.raise_for_status()
                paired = response.json()
            before = {"source": source, "chat_id": chat["id"], "task_id": task["id"],
                      "owner_sha256": hashlib.sha256(owner["token"].encode()).hexdigest(),
                      "desktop": desktop.read(), "paired_token": paired["token"]}
        else:
            if source == before["source"]:
                raise AssertionError("Same-version reinstall is not upgrade acceptance")
            if hashlib.sha256(owner["token"].encode()).hexdigest() != before["owner_sha256"]:
                raise AssertionError("Owner credential changed")
            # Do not wire/repair here: a surviving desktop credential must already exist.
            if desktop.read() != before["desktop"]:
                raise AssertionError("Desktop credential changed")
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=10) as client:
            headers = {"Authorization": "Bearer " + before["paired_token"]}
            identity = client.get(managed.ORIGIN + "/v1/device", headers=headers)
            identity.raise_for_status()
            if args.phase == "baseline":
                before["device_id"] = identity.json()["id"]
            elif identity.json()["id"] != before["device_id"]:
                raise AssertionError("Paired device identity changed")
            for path in ("/v1/conversations/" + before["chat_id"] + "/messages",
                         "/v1/work/tasks/" + before["task_id"]):
                client.get(managed.ORIGIN + path, headers=headers).raise_for_status()
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
                if response.json()["id"] != before["device_id"]:
                    raise AssertionError("Reconnect after restart changed identity")
        finally:
            managed.stop(directory)
        check_snapshot(store.path, before["snapshot"])
        args.report.write_text(json.dumps({
            "baseline_source": before["source"], "candidate_source": source,
            "baseline_installer_sha256": BASELINE_SHA256,
            "old_schema": before["schema"], "new_schema": schema,
            "old_rows_preserved": True, "migration_backup_verified": True,
            "owner_and_desktop_credentials_preserved": True,
            "paired_identity_and_scopes_reconnected": True, "backend_restart_passed": True,
            "scope": "Installed Windows backend; no model or physical/Tailscale claim."
        }, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--candidate", type=Path)
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
    if digest(args.candidate) == BASELINE_SHA256:
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
