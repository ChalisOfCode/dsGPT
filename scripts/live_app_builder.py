"""Compile/test both reviewed app fixtures in production-isolated containers."""

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

from dsgpt.builds import WorkBuilds
from dsgpt.project_tools import ProjectAction, ProjectTools
from dsgpt.storage import Store
from dsgpt.work import WorkRegistry

# -I deliberately omits the script directory; load only this reviewed sibling.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from app_builder_fixture import fixture  # noqa: E402


async def run(image, output):
    with tempfile.TemporaryDirectory(prefix="dsgpt-app-check-") as directory:
        store = Store(Path(directory))
        builds = WorkBuilds(store, image)
        await builds.probe()
        work = WorkRegistry(store, builds=builds)
        task = work.create(
            "Recipe check", "Counter Android APK and Windows EXE", build_target="apps"
        )
        with store.transaction() as db:
            for path, content in fixture(task["id"]).items():
                ProjectTools.apply(
                    db,
                    task["id"],
                    ProjectAction(
                        tool="write_file",
                        path=path,
                        content=content,
                        summary="Reviewed test fixture",
                    ),
                )
            db.execute("UPDATE work_tasks SET status='running' WHERE id=?", (task["id"],))
        action = ProjectAction(
            tool="build_project", target="apps", summary="Build and test both apps"
        )
        first = await builds.execute(task["id"], 1, action)
        assert not first.get("error"), first
        original_certificate = first["verification"]["checks"]["android"]["certificate_sha256"]
        with store.transaction() as db:
            row = db.execute(
                "SELECT * FROM work_files WHERE task_id=? AND path LIKE '%/Counter.kt'",
                (task["id"],),
            ).fetchone()
            path = row["path"]
            ProjectTools.apply(
                db,
                task["id"],
                ProjectAction(
                    tool="edit_file",
                    path=path,
                    old_text="value + 1",
                    new_text="BROKEN_VALUE",
                    expected_sha256=row["sha256"],
                    summary="Inject actual compiler failure",
                ),
            )
        failed = await builds.execute(task["id"], 2, action)
        assert failed.get("error") and failed.get("exit_code") != 0, failed
        with store.transaction() as db:
            row = db.execute(
                "SELECT sha256 FROM work_files WHERE task_id=? AND path=?", (task["id"], path)
            ).fetchone()
            ProjectTools.apply(
                db,
                task["id"],
                ProjectAction(
                    tool="edit_file",
                    path=path,
                    old_text="BROKEN_VALUE",
                    new_text="value + 1",
                    expected_sha256=row[0],
                    summary="Repair compiler diagnostic",
                ),
            )
        final = await builds.execute(task["id"], 3, action)
        assert not final.get("error"), final
        assert (
            final["verification"]["checks"]["android"]["certificate_sha256"] == original_certificate
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "fixture": "reviewed source, not model-generated",
            "first": first,
            "injected_failure": failed,
            "repaired": final,
            "native_runtime_verified": False,
            "persistent_signing_verified": True,
            "isolation": builds.probe_evidence,
        }
        output.write_text(json.dumps(report, indent=2) + "\n")
        for row in store.all(
            "SELECT path,content FROM work_artifacts WHERE execution_id=?", (final["execution_id"],)
        ):
            (output.parent / Path(row["path"]).name).write_bytes(row["content"])
        print(json.dumps({"passed": True, "artifacts": [a["path"] for a in final["artifacts"]]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(run(args.image, args.output))
