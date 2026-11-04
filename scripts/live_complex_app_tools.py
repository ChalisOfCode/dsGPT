"""Real compiler/behavior/repair/restart validation of reviewed Task Ledger sources.

Docker mode uses production WorkBuilds. --local-toolchain is explicitly a trusted
fixture-only host fallback: it never accepts model source or executes model actions.
Neither mode implies native GUI execution or physical-device validation.
"""

import argparse
import asyncio
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from dsgpt import app_build_worker
from dsgpt.builds import WorkBuilds, snapshot_hash
from dsgpt.project_tools import ProjectAction, ProjectTools
from dsgpt.storage import Store, utcnow
from dsgpt.work import WorkRegistry

sys.path.insert(0, str(Path(__file__).resolve().parent))
from complex_app_fixture import (  # noqa: E402
    DOMAIN_TEST_CASES,
    FOLLOWUP_ORACLE_CASE_COUNT,
    ORACLE_CASE_COUNT,
    fixture,
    package_name,
)

MARKER = "\n#error DSGPT_COMPLEX_FIXTURE_REPAIR\n"


def save_sources(db, task_id, sources):
    for path, content in sources.items():
        current = db.execute(
            "SELECT sha256,content FROM work_files WHERE task_id=? AND path=?", (task_id, path)
        ).fetchone()
        if current and current["content"] == content:
            continue
        result = ProjectTools.apply(
            db,
            task_id,
            ProjectAction(
                tool="write_file",
                path=path,
                content=content,
                summary="Reviewed deterministic fixture",
                expected_sha256=current["sha256"] if current else None,
            ),
        )
        assert not result.get("error"), result


def sources(store, task_id):
    return store.all(
        "SELECT path,content,sha256 FROM work_files WHERE task_id=? ORDER BY path", (task_id,)
    )


def materialize(rows, directory):
    for row in rows:
        path = directory / row["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(row["content"], encoding="utf-8")


def source_manifest(rows):
    return {row["path"]: row["sha256"] for row in rows}


def record_artifacts(store, execution_id, directory):
    directory.mkdir(parents=True, exist_ok=True)
    collected = []
    for row in store.all("SELECT * FROM work_artifacts WHERE execution_id=?", (execution_id,)):
        assert hashlib.sha256(row["content"]).hexdigest() == row["sha256"]
        path = directory / Path(row["path"]).name
        path.write_bytes(row["content"])
        collected.append({"path": str(path), "sha256": row["sha256"], "bytes": row["bytes"]})
    return collected


def checked_build(result, count):
    assert not result.get("error"), result
    report = result["verification"]
    assert report["checks"]["android"]["unit_tests"] >= count, report
    assert report["checks"]["windows"]["portable_test_program_passed"] is True
    assert "DSGPT_TASK_LEDGER_ORACLE_OK" in result.get("stdout", ""), result
    return report["checks"]["android"]["certificate_sha256"]


def record_task(report, task, rows):
    report.update(
        task_id=task["id"],
        android_package=package_name(task["id"]),
        windows_data_directory="dsGPT-TaskLedger-" + task["id"].replace("-", ""),
    )
    report["initial_source_sha256"] = snapshot_hash(rows)
    report["initial_sources"] = source_manifest(rows)


async def docker_run(args, report):
    store = Store(args.output / "database")
    builds = WorkBuilds(store, args.image)
    await builds.probe()
    work = WorkRegistry(store, builds=builds)
    task = work.create(
        "Task Ledger reviewed tool acceptance",
        "Compile reviewed Task Ledger APK and EXE",
        build_target="apps",
    )
    tid = task["id"]
    with store.transaction() as db:
        save_sources(db, tid, fixture(tid))
        db.execute("UPDATE work_tasks SET status='running' WHERE id=?", (tid,))
    rows = sources(store, tid)
    record_task(report, task, rows)
    materialize(rows, args.output / "initial/source")
    action = ProjectAction(
        tool="build_project",
        target="apps",
        summary="Compile reviewed Task Ledger and fixed contract tests",
    )
    first = await builds.execute(tid, 1, action)
    certificate = checked_build(first, ORACLE_CASE_COUNT)
    report["initial"] = first
    report["initial_artifacts"] = record_artifacts(
        store, first["execution_id"], args.output / "initial"
    )
    with store.transaction() as db:
        current = db.execute(
            "SELECT content FROM work_files WHERE task_id=? AND path='windows/main.cpp'", (tid,)
        ).fetchone()[0]
        save_sources(db, tid, {"windows/main.cpp": current + MARKER})
    failed = await builds.execute(
        tid,
        2,
        ProjectAction(
            tool="build_project",
            target="exe",
            summary="Observe deliberately injected compiler failure",
        ),
    )
    assert failed.get("error") and failed.get("exit_code") != 0, failed
    assert "DSGPT_COMPLEX_FIXTURE_REPAIR" in failed.get("stderr", ""), failed
    report["compiler_failure"] = failed
    before_restart = snapshot_hash(sources(store, tid))
    signing_before = store.one("SELECT sha256 FROM work_signing_keys WHERE task_id=?", (tid,))[
        "sha256"
    ]
    restored = Store(args.output / "database")
    resumed = WorkBuilds(restored, args.image)
    await resumed.recover()
    assert snapshot_hash(sources(restored, tid)) == before_restart
    assert (
        restored.one("SELECT sha256 FROM work_signing_keys WHERE task_id=?", (tid,))["sha256"]
        == signing_before
    )
    await resumed.probe()
    with restored.transaction() as db:
        save_sources(db, tid, fixture(tid, followup=True))
    final = await resumed.execute(tid, 3, action)
    assert checked_build(final, FOLLOWUP_ORACLE_CASE_COUNT) == certificate
    report["final"] = final
    report["final_artifacts"] = record_artifacts(
        restored, final["execution_id"], args.output / "final"
    )
    final_rows = sources(restored, tid)
    materialize(final_rows, args.output / "final/source")
    report["final_sources"] = source_manifest(final_rows)
    report["final_source_sha256"] = snapshot_hash(final_rows)
    report["checks"].update(
        real_compiler_failure=True,
        real_repaired_compile=True,
        domain_contract_initial=ORACLE_CASE_COUNT,
        domain_contract_followup=FOLLOWUP_ORACLE_CASE_COUNT,
        source_survived_store_reopen=True,
        signing_key_survived_store_reopen=True,
        apk_certificate_unchanged=True,
        current_source_receipts=final["snapshot_sha256"] == snapshot_hash(final_rows),
        no_cleanup_pending=resumed.status()["cleanup_pending"] == 0,
    )
    report["isolation_probe"] = resumed.probe_evidence
    report["restart_scope"] = (
        "Store and WorkBuilds recreated after completed failure; "
        "no process-crash or OS-reboot claim"
    )


def local_environment(root):
    root = root.resolve()
    compiler = root / "deb-root/usr/bin/x86_64-w64-mingw32-g++-posix"
    gradle = root / "gradle/gradle-8.13/bin/gradle"
    java = next(iter(sorted((root / "jdk").glob("*/bin/java"))), None)
    if java is None or not compiler.is_file() or not gradle.is_file():
        raise RuntimeError(
            "Prepared local toolchain is incomplete; this mode never downloads dependencies"
        )
    env = os.environ.copy()
    env.update(
        DSGPT_ANDROID_SDK=str(root / "android"),
        DSGPT_GRADLE=str(gradle),
        DSGPT_GRADLE_CACHE=str(root / "gradle-home"),
        DSGPT_WINDOWS_CXX=str(compiler),
        DSGPT_NATIVE_CXX=shutil.which("g++") or "g++",
        JAVA_HOME=str(java.parents[1]),
        JAVA_TOOL_OPTIONS="-XX:ActiveProcessorCount=2",
    )
    env["PATH"] = (
        str(java.parent) + os.pathsep + str(compiler.parent) + os.pathsep + env.get("PATH", "")
    )
    return env


def local_command(argv, cwd, env, log):
    started = time.monotonic()
    with log.open("w") as output:
        result = subprocess.run(
            argv, cwd=cwd, env=env, stdout=output, stderr=subprocess.STDOUT, timeout=900
        )
    return {
        "exit_code": result.returncode,
        "seconds": round(time.monotonic() - started, 3),
        "log": str(log),
    }


def local_build(directory, env, destination, target="apps"):
    shutil.rmtree(directory / "dist", ignore_errors=True)
    destination.mkdir(parents=True, exist_ok=True)
    result = local_command(
        [sys.executable, "-I", str(Path(app_build_worker.__file__).resolve()), target],
        directory,
        env,
        destination / "compiler.log",
    )
    if result["exit_code"] == 0:
        result["verification"] = json.loads((directory / "dist/build-report.json").read_text())
        for path in (directory / "dist").iterdir():
            if path.is_file():
                shutil.copy2(path, destination / path.name)
        if target in {"apk", "apps"}:
            xml = (
                directory
                / "android/app/build/test-results/testDebugUnitTest"
                / "TEST-IndependentTaskLedgerAcceptance.xml"
            )
            shutil.copy2(xml, destination / xml.name)
            suite = ET.parse(xml).getroot()
            result["independent_android_tests"] = {
                key: int(suite.attrib.get(key, 0))
                for key in ("tests", "failures", "errors", "skipped")
            }
    return result


def local_sign(store, tid, artifact_directory, env):
    signing = artifact_directory / "signing"
    signing.mkdir()
    (signing / "input-apk.b64").write_text(
        base64.b64encode((artifact_directory / "app.apk").read_bytes()).decode()
    )
    existing = store.one("SELECT key_bytes FROM work_signing_keys WHERE task_id=?", (tid,))
    if existing:
        (signing / "input-key.b64").write_text(base64.b64encode(existing["key_bytes"]).decode())
    result = local_command(
        [sys.executable, "-I", str(Path(app_build_worker.__file__).resolve()), "sign-android"],
        signing,
        env,
        artifact_directory / "signing.log",
    )
    assert result["exit_code"] == 0, result
    key = (signing / "signing.p12").read_bytes()
    with store.transaction() as db:
        if not existing:
            db.execute(
                "INSERT INTO work_signing_keys VALUES(?,?,?,?)",
                (tid, key, hashlib.sha256(key).hexdigest(), utcnow()),
            )
        else:
            assert key == existing["key_bytes"]
    report = json.loads((signing / "signing-report.json").read_text())
    shutil.copy2(signing / "signed.apk", artifact_directory / "app.apk")
    build_report_path = artifact_directory / "build-report.json"
    build_report = json.loads(build_report_path.read_text())
    build_report["checks"]["android"].update(report)
    build_report["artifacts"]["app.apk"] = hashlib.sha256(
        (artifact_directory / "app.apk").read_bytes()
    ).hexdigest()
    build_report_path.write_text(json.dumps(build_report, indent=2) + "\n")
    shutil.rmtree(signing)  # Signing material remains only in the private fixture database.
    return report


def local_run(args, report):
    env = local_environment(args.local_toolchain)
    store = Store(args.output / "database")
    task = WorkRegistry(store).create(
        "Reviewed local Task Ledger compiler check",
        "Reviewed deterministic sources",
        build_target="apps",
    )
    tid = task["id"]
    with store.transaction() as db:
        save_sources(db, tid, fixture(tid))
    rows = sources(store, tid)
    record_task(report, task, rows)
    directory = args.output / "workspace"
    materialize(rows, directory)
    # app_build_worker normally copies an image-owned cache into each sandbox. This
    # host mode accepts only our reviewed fixture, so reuse the prepared cache
    # instead of creating a multi-gigabyte duplicate on the constrained test host.
    cache = (args.local_toolchain / "gradle-home").resolve()
    if not cache.is_dir():
        raise RuntimeError("Prepared shared Gradle cache is missing")
    (directory / ".gradle-user").symlink_to(cache, target_is_directory=True)
    report["local_cache"] = {
        "strategy": "shared prepared Gradle cache; no per-workspace cache copy",
        "gradle_may_update_shared_cache": True,
    }
    materialize(rows, args.output / "initial/source")
    first = local_build(directory, env, args.output / "initial")
    report["initial"] = first
    assert first["exit_code"] == 0, first
    assert first["independent_android_tests"] == {
        "tests": ORACLE_CASE_COUNT,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
    }
    assert "DSGPT_TASK_LEDGER_ORACLE_OK" in (args.output / "initial/compiler.log").read_text()
    signature = local_sign(store, tid, args.output / "initial", env)
    first["verification"] = json.loads((args.output / "initial/build-report.json").read_text())
    with store.transaction() as db:
        current = db.execute(
            "SELECT content FROM work_files WHERE task_id=? AND path='windows/main.cpp'", (tid,)
        ).fetchone()[0]
        save_sources(db, tid, {"windows/main.cpp": current + MARKER})
    materialize(sources(store, tid), directory)
    failed = local_build(directory, env, args.output / "failure", "exe")
    report["compiler_failure"] = failed
    assert (
        failed["exit_code"] != 0
        and "DSGPT_COMPLEX_FIXTURE_REPAIR" in (args.output / "failure/compiler.log").read_text()
    )
    before = snapshot_hash(sources(store, tid))
    signing_before = store.one("SELECT sha256 FROM work_signing_keys WHERE task_id=?", (tid,))[
        "sha256"
    ]
    restored = Store(args.output / "database")
    assert snapshot_hash(sources(restored, tid)) == before
    assert (
        restored.one("SELECT sha256 FROM work_signing_keys WHERE task_id=?", (tid,))["sha256"]
        == signing_before
    )
    with restored.transaction() as db:
        save_sources(db, tid, fixture(tid, followup=True))
    final_rows = sources(restored, tid)
    materialize(final_rows, directory)
    materialize(final_rows, args.output / "final/source")
    final = local_build(directory, env, args.output / "final")
    report["final"] = final
    assert final["exit_code"] == 0, final
    assert final["independent_android_tests"] == {
        "tests": FOLLOWUP_ORACLE_CASE_COUNT,
        "failures": 0,
        "errors": 0,
        "skipped": 0,
    }
    assert "DSGPT_TASK_LEDGER_ORACLE_OK" in (args.output / "final/compiler.log").read_text()
    final_signature = local_sign(restored, tid, args.output / "final", env)
    final["verification"] = json.loads((args.output / "final/build-report.json").read_text())
    assert final_signature["certificate_sha256"] == signature["certificate_sha256"]
    report["signing"] = {"initial": signature, "final": final_signature}
    report["final_sources"] = source_manifest(final_rows)
    report["final_source_sha256"] = snapshot_hash(final_rows)
    report["checks"].update(
        real_compiler_failure=True,
        real_repaired_compile=True,
        domain_contract_initial=ORACLE_CASE_COUNT,
        domain_contract_followup=FOLLOWUP_ORACLE_CASE_COUNT,
        source_survived_store_reopen=True,
        signing_key_survived_store_reopen=True,
        apk_certificate_unchanged=True,
    )
    report["restart_scope"] = (
        "Store reopened after completed failure; local reviewed fixture only, "
        "not WorkBuilds execution receipts"
    )
    for phase in ("initial", "final"):
        report[phase + "_artifacts"] = [
            {
                "path": str(args.output / phase / name),
                "sha256": hashlib.sha256((args.output / phase / name).read_bytes()).hexdigest(),
                "bytes": (args.output / phase / name).stat().st_size,
            }
            for name in ("app.apk", "app.exe")
        ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--image", help="Prepared production Docker image ID")
    mode.add_argument(
        "--local-toolchain",
        type=Path,
        help="Prepared trusted-fixture-only host toolchain; "
        "no downloads and no model source accepted",
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="New evidence directory, not a release archive"
    )
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    report = {
        "fixture": "reviewed deterministic Task Ledger",
        "model_driven": False,
        "passed": False,
        "native_runtime_verified": False,
        "physical_device_verified": False,
        "isolation": bool(args.image),
        "production_execution_receipts": bool(args.image),
        "domain_test_cases": list(DOMAIN_TEST_CASES),
        "checks": {},
    }
    try:
        if args.image:
            asyncio.run(docker_run(args, report))
        else:
            local_run(args, report)
        report["passed"] = bool(report["checks"]) and all(report["checks"].values())
    except Exception as exc:
        report["error"] = type(exc).__name__ + ": " + str(exc)
    (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "report": str(args.output / "report.json"),
                "error": report.get("error"),
            }
        )
    )
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
