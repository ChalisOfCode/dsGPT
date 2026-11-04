"""Kill a real isolated-build worker and validate owned-container recovery.

The guest command is a deterministic test fixture, never run on the host.
An independently owned container must survive the recovery operation.
"""

import argparse
import asyncio
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from dsgpt.builds import WorkBuilds
from dsgpt.project_tools import ProjectAction
from dsgpt.sandbox import DockerSandbox
from dsgpt.storage import Store
from dsgpt.work import WorkRegistry

GUEST = "import pathlib,time; pathlib.Path('/work/started').write_text('started'); time.sleep(240)"


async def worker(args):
    builds = WorkBuilds(Store(args.data), image=args.image)
    await builds.probe()
    await builds.execute(
        args.task,
        1,
        ProjectAction(
            tool="run",
            summary="Crash recovery fixture",
            argv=["python3", "-I", "-c", GUEST],
            timeout_seconds=300,
        ),
    )


async def main(args, report):
    with tempfile.TemporaryDirectory(prefix="dsgpt-live-recovery-") as directory:
        root = Path(directory)
        data, control = root / "data", root / "control"
        control.mkdir()
        store = Store(data)
        task = WorkRegistry(store).create("Recovery", "Deterministic fixture", build_target="files")
        with store.transaction() as db:
            db.execute("UPDATE work_tasks SET status='running' WHERE id=?", (task["id"],))
        sentinel = DockerSandbox(control, args.image, uuid4().hex)
        sentinel_id = str(uuid4())
        child = None
        receipt = None
        builds = WorkBuilds(store, image=args.image)
        try:
            await sentinel.create(sentinel_id)
            with args.output.with_suffix(".worker.log").open("w") as log:
                child = subprocess.Popen(
                    [
                        sys.executable,
                        str(Path(__file__).resolve()),
                        "--worker",
                        "--image",
                        args.image,
                        "--data",
                        str(data),
                        "--task",
                        task["id"],
                    ],
                    stdout=log,
                    stderr=log,
                    start_new_session=True,
                )
                deadline = time.monotonic() + 60
                started = False
                while time.monotonic() < deadline:
                    assert child.poll() is None, "Build worker exited before crash injection"
                    receipt = store.one(
                        "SELECT * FROM work_executions WHERE task_id=? AND status='running'",
                        (task["id"],),
                    )
                    if receipt:
                        code, out, _, _ = await builds.sandbox.cli(
                            [
                                "container",
                                "exec",
                                "--",
                                builds.sandbox.name(receipt["id"]),
                                "python3",
                                "-I",
                                "-c",
                                "import pathlib; print(pathlib.Path('/work/started').exists())",
                            ],
                        )
                        if code == 0 and out.strip() == b"True":
                            started = True
                            break
                    await asyncio.sleep(0.1)
                assert started, "Real guest command did not reach its marker"
                report["checks"]["guest_command_started"] = True
                child.kill()
                child.wait(timeout=10)
                report["checks"]["worker_killed"] = child.returncode == -signal.SIGKILL
                orphan = await builds.sandbox.inspect(builds.sandbox.name(receipt["id"]))
                report["checks"]["container_survived_worker_crash"] = orphan["State"]["Running"]

                restored = WorkBuilds(Store(data), image=args.image)
                await restored.recover()
                action, result = restored.pending(task["id"], 1)
                report["checks"]["uncertain_receipt_interrupted"] = (
                    result["error"] == "execution_interrupted" and action["argv"][-1] == GUEST
                )
                report["checks"]["cleanup_pending_cleared"] = (
                    restored.status()["cleanup_pending"] == 0
                )
                code, _, _, _ = await restored.sandbox.cli(
                    ["container", "inspect", restored.sandbox.name(receipt["id"])]
                )
                report["checks"]["owned_container_removed"] = code != 0
                other = await sentinel.inspect(sentinel.name(sentinel_id))
                report["checks"]["unrelated_owner_container_preserved"] = other["State"]["Running"]
                report["checks"]["readiness_requires_new_probe"] = not restored.ready
                await restored.probe()
                report["checks"]["new_probe_succeeds"] = restored.ready
                report["checks"]["uncertain_command_not_replayed"] = (
                    store.one(
                        "SELECT count(*) AS n FROM work_executions WHERE task_id=?", (task["id"],)
                    )["n"]
                    == 1
                )
                report["receipt"] = result
                report["probe"] = restored.probe_evidence
                report["passed"] = all(report["checks"].values())
        finally:
            if child is not None:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=10)
                # Only the process group created for this trusted fixture is reaped.
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            if receipt:
                await builds.sandbox.cleanup(receipt["id"])
            await sentinel.cleanup(sentinel_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--data", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--task", help=argparse.SUPPRESS)
    arguments = parser.parse_args()
    if arguments.worker:
        asyncio.run(worker(arguments))
    else:
        if not arguments.output:
            parser.error("--output is required")
        result = {
            "actual_docker_execution": True,
            "agent": "deterministic fixture",
            "checks": {},
            "passed": False,
        }
        try:
            asyncio.run(main(arguments, result))
        except Exception as exc:
            result["error"] = type(exc).__name__ + ": " + str(exc)
        arguments.output.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result))
        raise SystemExit(0 if result["passed"] else 1)
