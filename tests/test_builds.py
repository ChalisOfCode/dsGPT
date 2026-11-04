import asyncio
import hashlib
import io
import json
import subprocess
import sys
import tarfile
import time

import pytest
from conftest import pair
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_stage3_work import AgentFixture, setup, wait_task

from dsgpt.builds import WorkBuilds, artifact_kind, snapshot_hash
from dsgpt.project_tools import ProjectAction, ProjectTools, action_schema
from dsgpt.sandbox import SandboxError, artifact_bytes, source_archive
from dsgpt.storage import Store, uid, utcnow
from dsgpt.work import WorkRegistry


class SandboxFixture:
    """Transport fixture, not evidence of a real container or compiler."""

    def __init__(self, fail_first=False):
        self.calls = []
        self.cleaned = []
        self.fail_first = fail_first
        self.cleanup_error = False

    async def probe(self, identifier):
        return {"fixture": True}

    async def cleanup(self, identifier):
        self.cleaned.append(identifier)
        if self.cleanup_error:
            raise SandboxError("daemon_unavailable")

    async def execute(self, identifier, files, argv, artifacts, timeout):
        self.calls.append((identifier, files, argv, artifacts, timeout))
        if self.fail_first and len(self.calls) == 1:
            return {
                "exit_code": 1,
                "stdout": "",
                "stderr": "injected build error",
                "omitted_output_bytes": 0,
                "artifacts": [],
            }
        content = b"FIXTURE ARTIFACT; NOT A COMPILED PROGRAM"
        return {
            "exit_code": 0,
            "stdout": "fixture command succeeded",
            "stderr": "",
            "omitted_output_bytes": 0,
            "artifacts": [
                {"path": p, "content": content, "sha256": hashlib.sha256(content).hexdigest()}
                for p in artifacts
            ],
        }


def request_start(client, target="files"):
    row = client.post(
        "/v1/work/tasks",
        json={
            "title": "Build fixture",
            "requirements": "Create the requested output",
            "model_id": "local",
            "build_target": target,
        },
    ).json()
    response = client.post(
        f"/v1/work/tasks/{row['id']}/actions", json={"action": "start", "revision": row["revision"]}
    )
    assert response.status_code == 200
    return row["id"]


def test_build_loop_records_failure_repairs_collects_and_finishes(tmp_path):
    bad, good = "bad fixture source", "repaired fixture source"
    digest = hashlib.sha256(bad.encode()).hexdigest()
    action = {
        "tool": "run",
        "argv": ["compiler", "main.txt"],
        "artifacts": ["output.bin"],
        "summary": "Build current files",
    }
    agent = AgentFixture(
        [
            {"tool": "write_file", "path": "main.txt", "content": bad, "summary": "Write"},
            action,
            {
                "tool": "write_file",
                "path": "main.txt",
                "content": good,
                "expected_sha256": digest,
                "summary": "Repair observed build error",
            },
            action,
            {"tool": "finish", "summary": "Collected output; fixture evidence only"},
        ]
    )
    app, _, headers = setup(tmp_path, agent)
    sandbox = SandboxFixture(fail_first=True)
    app.state.builds.sandbox = sandbox
    with TestClient(app, headers=headers) as client:
        assert client.post("/v1/work/sandbox/probe").json()["ready"]
        task_id = request_start(client)
        task = wait_task(client, task_id)
        assert task["status"] == "completed" and task["capability"] == "isolated_build"
        assert len(sandbox.calls) == 2
        assert sandbox.calls[0][1][0]["content"] == bad
        assert sandbox.calls[1][1][0]["content"] == good
        steps = client.get(f"/v1/work/tasks/{task_id}/steps").json()
        assert steps[1]["result"]["error"] == "command_failed"
        assert steps[-1]["result"]["build_command_succeeded"] is True
        assert steps[-1]["result"]["native_runtime_verified"] is False
        artifacts = client.get(f"/v1/work/tasks/{task_id}/artifacts").json()
        content = client.get(f"/v1/work/tasks/{task_id}/artifacts/{artifacts[0]['id']}")
        assert content.status_code == 200
        assert hashlib.sha256(content.content).hexdigest() == artifacts[0]["sha256"]
        assert content.headers["content-type"] == "application/octet-stream"
        jobs = client.get(f"/v1/work/tasks/{task_id}/executions").json()
        assert len(jobs) == 2 and all(j["recorded"] and not j["cleanup_pending"] for j in jobs)
        job = client.get(f"/v1/work/tasks/{task_id}/executions/{jobs[0]['id']}").json()
        assert job["result"]["exit_code"] == 0
        failure = app.state.store.one(
            "SELECT payload FROM diagnostic_snapshots WHERE reason='build_failed'"
        )
        assert failure is not None
        assert json.loads(failure["payload"])["executions"][0]["exit_code"] != 0
        assert bad not in failure["payload"]
        assert not (tmp_path / "main.txt").exists()


def test_build_request_tries_automatic_setup_and_reports_missing_docker(tmp_path, monkeypatch):
    def missing_docker():
        raise SandboxError("Docker is not installed")

    # Exercise the missing dependency deliberately, even on Docker-equipped CI.
    monkeypatch.setattr("dsgpt.sandbox.docker_binary", missing_docker)
    monkeypatch.setattr("dsgpt.tool_setup.docker_binary", missing_docker)
    agent = AgentFixture([])
    app, _, headers = setup(tmp_path, agent)
    with TestClient(app, headers=headers) as client:
        task = wait_task(client, request_start(client, "apk"))
        assert task["status"] == "blocked" and task["session"]["error_code"] == "docker_required"
        assert agent.calls == 0
        assert not client.get("/v1/capabilities").json()["work"]["code_execution"]
        assert client.post("/v1/work/sandbox/probe").status_code == 409


def test_finish_rejects_missing_or_wrong_artifact_type_and_stale_sources(tmp_path):
    store = Store(tmp_path)
    work = WorkRegistry(store)
    row = work.create("Build", "APK", build_target="apk")
    identifier = row["id"]
    with store.transaction() as db:
        ProjectTools.apply(
            db,
            identifier,
            ProjectAction(
                tool="write_file",
                summary="source",
                path="main.txt",
                content="hello",
            ),
        )
        files = [dict(r) for r in db.execute("SELECT path,sha256 FROM work_files")]
        execution = uid()
        output = b"Build report"
        artifact = {
            "id": "artifact",
            "kind": "file",
            "path": "report.txt",
            "sha256": hashlib.sha256(output).hexdigest(),
            "bytes": len(output),
        }
        result = {"artifacts": [artifact]}
        db.execute(
            "INSERT INTO work_executions(id,task_id,step,action,snapshot_sha256,status,result,"
            "cleanup_pending,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                execution,
                identifier,
                1,
                "{}",
                snapshot_hash(files),
                "completed",
                json.dumps(result),
                0,
                utcnow(),
                utcnow(),
            ),
        )
        db.execute(
            "INSERT INTO work_artifacts VALUES(?,?,?,?,?,?,?)",
            (
                artifact["id"],
                execution,
                identifier,
                artifact["path"],
                artifact["sha256"],
                artifact["bytes"],
                output,
            ),
        )
        assert not WorkBuilds.finish_evidence(db, identifier, "apk")
        assert WorkBuilds.finish_evidence(db, identifier, "files")
        failed = uid()
        db.execute(
            "INSERT INTO work_executions(id,task_id,step,action,snapshot_sha256,status,result,"
            "cleanup_pending,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                failed,
                identifier,
                2,
                "{}",
                snapshot_hash(files),
                "failed",
                "{}",
                0,
                utcnow(),
                utcnow(),
            ),
        )
        assert not WorkBuilds.finish_evidence(db, identifier, "files")
        db.execute("DELETE FROM work_executions WHERE id=?", (failed,))
        db.execute("UPDATE work_files SET sha256=?", ("f" * 64,))
        assert not WorkBuilds.finish_evidence(db, identifier, "files")


async def test_completed_receipt_recovered_without_reexecuting(tmp_path):
    store = Store(tmp_path)
    sandbox = SandboxFixture()
    builds = WorkBuilds(store, sandbox=sandbox)
    work = WorkRegistry(store, builds=builds)
    row = work.create("Build", "Files", build_target="files")
    identifier = row["id"]
    with store.transaction() as db:
        db.execute("UPDATE work_tasks SET status='running' WHERE id=?", (identifier,))
        db.execute("INSERT INTO work_sessions(task_id,model_id) VALUES(?,?)", (identifier, "local"))
    builds.ready = True
    action = ProjectAction(tool="run", summary="Collect", argv=["compiler"], artifacts=["out.bin"])
    original = await builds.execute(identifier, 1, action)
    restarted = WorkBuilds(Store(tmp_path), sandbox=sandbox)
    await restarted.recover()
    restored = restarted.pending(identifier, 1)
    assert restored[1] == original
    assert len(sandbox.calls) == 1
    session = store.one("SELECT * FROM work_sessions")
    work._commit(identifier, session, ProjectAction.model_validate(restored[0]), restored[1])
    assert not restarted.pending(identifier, 1)
    assert store.one("SELECT count(*) AS n FROM work_steps")["n"] == 1


async def test_cleanup_failure_prevents_readiness_and_does_not_replay(tmp_path):
    store = Store(tmp_path)
    sandbox = SandboxFixture()
    builds = WorkBuilds(store, sandbox=sandbox)
    execution = uid()
    with store.transaction() as db:
        db.execute(
            "INSERT INTO work_executions(id,action,snapshot_sha256,status,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?)",
            (execution, "{}", "a" * 64, "running", utcnow(), utcnow()),
        )
    sandbox.cleanup_error = True
    await builds.recover()
    assert not builds.ready and builds.status()["cleanup_pending"] == 1
    assert not sandbox.calls
    sandbox.cleanup_error = False
    await builds.recover()
    assert builds.status()["cleanup_pending"] == 0
    row = store.one("SELECT * FROM work_executions")
    assert row["status"] == "interrupted"
    assert json.loads(row["result"])["error"] == "execution_interrupted"


def test_artifact_and_execution_endpoints_require_work_scope(backend):
    chat, _ = pair(backend, ["chat"])
    headers = {"Authorization": "Bearer " + chat["token"]}
    task = backend.client.post("/v1/work/tasks", json={"title": "X", "requirements": "Y"}).json()
    for endpoint in ("artifacts", "executions", "artifacts/" + uid(), "executions/" + uid()):
        assert (
            backend.client.get(
                f"/v1/work/tasks/{task['id']}/{endpoint}", headers=headers
            ).status_code
            == 403
        )
    assert backend.client.post("/v1/work/sandbox/probe", headers=headers).status_code == 403


@pytest.mark.parametrize(
    "values",
    [
        {"argv": []},
        {"argv": ["a\0b"]},
        {"argv": ["x" * 8193]},
        {"argv": ["true"], "artifacts": ["../outside"]},
        {"argv": ["true"], "artifacts": ["a", "a"]},
        {"argv": ["true"], "timeout_seconds": 901},
    ],
)
def test_command_contract_bounds(values):
    with pytest.raises(ValidationError):
        ProjectAction(tool="run", summary="Run", **values)
    assert '"const": "run"' not in json.dumps(action_schema())
    assert '"const": "run"' in json.dumps(action_schema(isolated_execution=True))


def make_tar(name="out.bin", data=b"artifact", kind=tarfile.REGTYPE, extra=False):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w") as archive:
        item = tarfile.TarInfo(name)
        item.type = kind
        item.size = len(data) if kind == tarfile.REGTYPE else 0
        item.linkname = "/private" if kind != tarfile.REGTYPE else ""
        archive.addfile(item, io.BytesIO(data) if item.isfile() else None)
        if extra:
            archive.addfile(tarfile.TarInfo("second"))
    return out.getvalue()


def test_only_regular_expected_artifact_bytes_are_read_without_extraction(tmp_path):
    assert artifact_bytes(make_tar(), "output/out.bin") == b"artifact"
    for archive in (
        make_tar("../out.bin"),
        make_tar(kind=tarfile.SYMTYPE),
        make_tar(kind=tarfile.LNKTYPE),
        make_tar(extra=True),
        b"bad archive",
    ):
        with pytest.raises(SandboxError):
            artifact_bytes(archive, "out.bin")
    assert not list(tmp_path.iterdir())
    assert artifact_kind("fake.exe", b"MZgarbage") == "file"
    assert artifact_kind("fake.apk", b"PK\x03\x04garbage") == "file"


def test_snapshot_archive_is_content_verified_and_portable():
    content = "print('fixture')"
    row = {
        "path": "src/main.py",
        "content": content,
        "sha256": hashlib.sha256(content.encode()).hexdigest(),
    }
    with tarfile.open(fileobj=io.BytesIO(source_archive([row]))) as archive:
        entries = archive.getmembers()
        assert len(entries) == 1 and entries[0].isfile()
        assert entries[0].uid == entries[0].gid == 1000
        assert archive.extractfile(entries[0]).read() == content.encode()
    with pytest.raises(SandboxError):
        source_archive([{**row, "sha256": "0" * 64}])
    with pytest.raises(ValueError):
        source_archive([{**row, "path": "../../host"}])


def test_process_kill_leaves_durable_interrupted_receipt_without_replay(tmp_path):
    data, marker = tmp_path / "data", tmp_path / "effect.txt"
    store = Store(data)
    task = WorkRegistry(store).create("Crash", "Recovery", build_target="files")
    with store.transaction() as db:
        db.execute("UPDATE work_tasks SET status='running' WHERE id=?", (task["id"],))
    program = r"""
import asyncio,pathlib,sys
from dsgpt.builds import WorkBuilds
from dsgpt.storage import Store
from dsgpt.project_tools import ProjectAction
class Fixture:
 async def execute(self,*args):
  pathlib.Path(sys.argv[3]).write_text('one trusted fixture effect')
  await asyncio.Event().wait()
 async def cleanup(self,*args): pass
async def main():
 builds=WorkBuilds(Store(pathlib.Path(sys.argv[1])),sandbox=Fixture());builds.ready=True
 await builds.execute(sys.argv[2],1,ProjectAction(tool='run',summary='fixture',argv=['fixture']))
asyncio.run(main())
"""
    child = subprocess.Popen([sys.executable, "-c", program, str(data), task["id"], str(marker)])
    try:
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert marker.exists()
    finally:
        child.kill()
        child.wait(timeout=5)
    sandbox = SandboxFixture()
    restored = WorkBuilds(Store(data), sandbox=sandbox)
    asyncio.run(restored.recover())
    action, result = restored.pending(task["id"], 1)
    assert action["argv"] == ["fixture"] and result["error"] == "execution_interrupted"
    assert not sandbox.calls and len(sandbox.cleaned) == 1
    assert marker.read_text() == "one trusted fixture effect"
