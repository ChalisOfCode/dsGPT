"""Check binary assets using the production isolated runner and persistent signing path."""

import argparse
import asyncio
import hashlib
import json
import tempfile
from pathlib import Path

from dsgpt.builds import WorkBuilds
from dsgpt.project_tools import ProjectAction, ProjectTools
from dsgpt.storage import Store
from dsgpt.work import WorkRegistry


async def run(image, output):
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        store = Store(Path(temp))
        builds = WorkBuilds(store, image)
        await builds.probe()
        work = WorkRegistry(store, builds=builds)
        task = work.create("Asset fixture", "Verify APK EXE video tools", build_target="files")
        fixture = (Path(__file__).parent / "asset_fixture.py").read_text()
        with store.transaction() as db:
            ProjectTools.apply(
                db,
                task["id"],
                ProjectAction(
                    tool="write_file",
                    path="fixture.py",
                    content=fixture,
                    summary="Reviewed real tool fixture",
                ),
            )
            db.execute("UPDATE work_tasks SET status='running' WHERE id=?", (task["id"],))
        first = await builds.execute(
            task["id"],
            1,
            ProjectAction(
                tool="run",
                summary="Real APK EXE and video tools",
                argv=["/usr/bin/python3", "-I", "fixture.py"],
                artifacts=["asset-evidence.zip", "modified.apk"],
                timeout_seconds=900,
            ),
        )
        (output / "execution.json").write_text(json.dumps(first, indent=2))
        assert not first.get("error"), first
        assert first["apk_signing"]["modified.apk"]["signature_verified"]
        for artifact in store.all("SELECT * FROM work_artifacts WHERE task_id=?", (task["id"],)):
            (output / artifact["path"]).write_bytes(artifact["content"])
        second = await builds.execute(
            task["id"],
            2,
            ProjectAction(
                tool="run",
                summary="Read persistent previous output and verify signed APK",
                argv=[
                    "/opt/android/build-tools/35.0.0/apksigner",
                    "verify",
                    "--verbose",
                    "receipts/modified.apk",
                ],
            ),
        )
        (output / "receipt-reuse.json").write_text(json.dumps(second, indent=2))
        assert not second.get("error"), second
        assert not store.one("SELECT 1 FROM work_executions WHERE cleanup_pending=1")
        print(
            json.dumps(
                {
                    "passed": True,
                    "signed_apk_sha256": hashlib.sha256(
                        (output / "modified.apk").read_bytes()
                    ).hexdigest(),
                }
            )
        )


p = argparse.ArgumentParser()
p.add_argument("--image", required=True)
p.add_argument("--output", type=Path, required=True)
a = p.parse_args()
asyncio.run(run(a.image, a.output))
