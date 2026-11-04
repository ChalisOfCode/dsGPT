"""Durable isolated command receipts and artifacts; uncertain commands are never replayed."""

import asyncio
import base64
import hashlib
import io
import json
import shutil
import zipfile
from pathlib import Path

from fastapi import HTTPException

from . import browser_worker, work_assets
from .project_tools import safe_path
from .sandbox import PIDS_LIMIT, DockerSandbox, SandboxError
from .storage import canonical, uid, utcnow
from .work_asset_tools import transcription_plan, transcription_result
from .work_transcripts import assembly_plan, assembly_result, coverage_state


def snapshot_hash(files):
    return hashlib.sha256(
        canonical(
            [[f["path"], f["sha256"]] for f in sorted(files, key=lambda f: f["path"])]
        ).encode()
    ).hexdigest()


def requested_artifact_paths(result):
    """Only explicitly persisted, valid intended paths can invalidate older outputs."""
    paths = result.get("requested_artifact_paths", []) if isinstance(result, dict) else []
    if not isinstance(paths, list):
        return []
    selected = []
    for path in paths:
        if not isinstance(path, str):
            continue
        try:
            safe_path(path)
        except ValueError:
            continue
        if path not in selected:
            selected.append(path)
    return selected


def current_file_receipts(db, task_id, digest=None):
    """Return current saved outputs, with historical paths preventing stale fallback."""
    saved = {}
    execution_paths = {}
    for artifact in db.execute(
        "SELECT a.id,a.execution_id,a.path,a.sha256,a.bytes,length(a.content) AS size "
        "FROM work_artifacts a JOIN work_executions e ON e.id=a.execution_id "
        "WHERE a.task_id=? AND e.task_id=?"
        + (" AND e.snapshot_sha256=?" if digest is not None else ""),
        (task_id, task_id, *([digest] if digest is not None else [])),
    ):
        saved[artifact["id"]] = dict(artifact)
        execution_paths.setdefault(artifact["execution_id"], set()).add(artifact["path"])
    seen, collected = set(), []
    for row in db.execute(
        "SELECT id,status,cleanup_pending,result FROM work_executions WHERE task_id=? "
        + ("AND snapshot_sha256=? " if digest is not None else "")
        + "ORDER BY step DESC,rowid DESC",
        (task_id, *([digest] if digest is not None else [])),
    ):
        try:
            result = json.loads(row["result"] or "{}")
        except (TypeError, ValueError):
            result = {}
        artifacts = result.get("artifacts", []) if isinstance(result, dict) else []
        artifacts = artifacts if isinstance(artifacts, list) else []
        artifacts = [
            artifact
            for artifact in artifacts
            if isinstance(artifact, dict) and isinstance(artifact.get("path"), str)
        ]
        paths = (
            execution_paths.get(row["id"], set())
            | {artifact["path"] for artifact in artifacts}
            | set(requested_artifact_paths(result))
        )
        available = paths - seen
        # A deleted, corrupt, or failed replacement must not resurrect an older file.
        seen.update(paths)
        if (
            row["status"] != "completed"
            or row["cleanup_pending"]
            or not isinstance(result, dict)
            or result.get("error")
            or result.get("exit_code", 0) != 0
        ):
            continue
        for artifact in artifacts:
            stored = saved.get(artifact.get("id")) if isinstance(artifact.get("id"), str) else None
            if (
                artifact["path"] not in available
                or stored is None
                or stored["execution_id"] != row["id"]
                or stored["size"] != stored["bytes"]
                or artifact.get("kind") not in ("file", "apk", "exe")
                or any(
                    artifact.get(key) != stored[key] for key in ("id", "path", "sha256", "bytes")
                )
            ):
                continue
            collected.append(
                {
                    **{key: stored[key] for key in ("id", "path", "sha256", "bytes")},
                    "kind": artifact["kind"],
                    "execution_id": row["id"],
                }
            )
            available.remove(artifact["path"])
    return collected


def artifact_kind(path, content):
    if path.lower().endswith(".exe") and len(content) >= 64 and content[:2] == b"MZ":
        offset = int.from_bytes(content[60:64], "little")
        if content[offset : offset + 4] == b"PE\0\0":
            return "exe"
    if path.lower().endswith(".apk") and content[:4] == b"PK\x03\x04":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                names = set(archive.namelist())
                if "AndroidManifest.xml" in names and (
                    "classes.dex" in names or "resources.arsc" in names
                ):
                    return "apk"
        except zipfile.BadZipFile:
            pass
    return "file"


class WorkBuilds:
    def __init__(self, store, image=None, sandbox=None):
        self.store, self.image = store, image
        self.sandbox = sandbox
        self.ready = False
        self.error = None if image or sandbox else "sandbox_not_configured"
        self.probe_evidence = None
        self.lock = asyncio.Lock()
        if image and sandbox is None:
            try:
                self.sandbox = DockerSandbox(
                    store.directory,
                    image,
                    store.one("SELECT owner_id FROM sandbox_identity WHERE id=1")["owner_id"],
                )
            except (SandboxError, OSError) as exc:
                self.error = str(exc) if isinstance(exc, SandboxError) else "docker_cli_unavailable"

    def status(self):
        return {
            "configured": bool(self.image or self.sandbox),
            "ready": self.ready,
            "error_code": self.error,
            "image_id": self.image,
            "probe": self.probe_evidence,
            "cleanup_pending": self.store.one(
                "SELECT count(*) AS n FROM work_executions WHERE cleanup_pending=1"
            )["n"],
            "host_execution": False,
            "network": "none",
            "gpu": False,
            "limits": {"cpus": 2, "memory_bytes": 4 * 1024**3, "pids": PIDS_LIMIT},
        }

    async def recover(self):
        self.ready = False
        for row in self.store.all("SELECT * FROM work_executions WHERE cleanup_pending=1"):
            cleaned = False
            if self.sandbox:
                try:
                    await self.sandbox.cleanup(row["id"])
                    cleaned = True
                except (SandboxError, OSError, TimeoutError, ValueError):
                    self.error = "sandbox_cleanup_pending"
            with self.store.transaction() as db:
                if row["status"] in {"prepared", "running"}:
                    try:
                        saved = json.loads(row["result"] or "{}")
                    except (TypeError, ValueError):
                        saved = {}
                    result = {
                        "error": "execution_interrupted",
                        "execution_id": row["id"],
                        "snapshot_sha256": row["snapshot_sha256"],
                        "help": "Previous command outcome was interrupted; it was not replayed.",
                    }
                    intended = requested_artifact_paths(saved)
                    if intended:
                        result["requested_artifact_paths"] = intended
                    for key in ("assets_sha256", "transcription_source_sha256"):
                        value = saved.get(key) if isinstance(saved, dict) else None
                        if (
                            isinstance(value, str)
                            and len(value) == 64
                            and all(c in "0123456789abcdef" for c in value)
                        ):
                            result[key] = value
                    db.execute(
                        "UPDATE work_executions SET status='interrupted',result=?,updated_at=? "
                        "WHERE id=?",
                        (canonical(result), utcnow(), row["id"]),
                    )
                if cleaned:
                    db.execute(
                        "UPDATE work_executions SET cleanup_pending=0 WHERE id=?", (row["id"],)
                    )
            if row["status"] in {"prepared", "running"}:
                self.store.log("build_interrupted", row["id"])

    async def probe(self):
        if self.lock.locked():
            raise HTTPException(409, "An isolated operation is already active")
        if not self.sandbox:
            raise HTTPException(409, {"code": self.error or "sandbox_not_configured"})
        async with self.lock:
            await self.recover()
            if self.status()["cleanup_pending"]:
                raise HTTPException(409, {"code": "sandbox_cleanup_pending"})
            identifier, now = uid(), utcnow()
            with self.store.transaction() as db:
                db.execute(
                    "INSERT INTO work_executions(id,action,snapshot_sha256,image_id,status,"
                    "created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                    (
                        identifier,
                        '{"tool":"sandbox_probe"}',
                        snapshot_hash([]),
                        self.image,
                        "prepared",
                        now,
                        now,
                    ),
                )
            try:
                evidence = await self.sandbox.probe(identifier)
                self.probe_evidence, self.ready, self.error = evidence, True, None
                with self.store.transaction() as db:
                    db.execute(
                        "UPDATE work_executions SET status='completed',result=?,cleanup_pending=0,"
                        "updated_at=? WHERE id=?",
                        (canonical(evidence), utcnow(), identifier),
                    )
            except (SandboxError, OSError, TimeoutError, ValueError, KeyError) as exc:
                self.ready = False
                self.error = str(exc) if isinstance(exc, SandboxError) else "sandbox_probe_failed"
                with self.store.transaction() as db:
                    db.execute(
                        "UPDATE work_executions SET status='failed',result=? WHERE id=?",
                        (canonical({"error": self.error}), identifier),
                    )
                # Cleanup may already have succeeded; recovery rechecks ownership/existence.
                self.store.log("build_failed", identifier)
                await self.recover()
                raise HTTPException(409, {"code": self.error}) from exc
        return self.status()

    def pending(self, task_id, step):
        row = self.store.one(
            "SELECT * FROM work_executions WHERE task_id=? AND step=? AND recorded=0 "
            "AND status IN ('completed','failed','interrupted')",
            (task_id, step),
        )
        return (json.loads(row["action"]), json.loads(row["result"])) if row else None

    async def execute(self, task_id, step, action):
        if action.tool in {"transcribe_media", "assemble_transcript"} and not self.store.one(
            "SELECT 1 FROM work_build_profiles WHERE task_id=?", (task_id,)
        ):
            return {"error": "transcription_requires_isolated_work"}
        if not self.ready or not self.sandbox:
            return {"error": "sandbox_not_ready"}
        async with self.lock:
            with self.store.transaction() as db:
                if (
                    db.execute("SELECT status FROM work_tasks WHERE id=?", (task_id,)).fetchone()[0]
                    != "running"
                ):
                    raise asyncio.CancelledError
                files = [
                    dict(r)
                    for r in db.execute(
                        "SELECT path,content,sha256 FROM work_files WHERE task_id=? ORDER BY path",
                        (task_id,),
                    )
                ]
                identifier, now, digest = uid(), utcnow(), snapshot_hash(files)
                db.execute(
                    "INSERT INTO work_executions(id,task_id,step,action,snapshot_sha256,image_id,"
                    "status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        identifier,
                        task_id,
                        step,
                        canonical(action.model_dump()),
                        digest,
                        self.image,
                        "prepared",
                        now,
                        now,
                    ),
                )
            result = {"execution_id": identifier, "snapshot_sha256": digest}
            status, artifacts, cancelled, cleaned = "failed", [], False, False
            try:
                with self.store.transaction() as db:
                    db.execute(
                        "UPDATE work_executions SET status='running' WHERE id=?", (identifier,)
                    )
                if action.tool in {"run", "transcribe_media", "assemble_transcript"}:
                    with self.store.connect() as db:
                        if action.tool == "assemble_transcript":
                            plan = assembly_plan(db, task_id, action.path)
                            assets, asset_digest = work_assets.snapshot(
                                db, task_id, paths=plan["paths"]
                            )
                        elif action.tool == "transcribe_media":
                            if not work_assets.lookup(db, task_id, action.path):
                                raise SandboxError("transcription_saved_asset_required")
                            assets, asset_digest = work_assets.snapshot(
                                db, task_id, paths=[action.path]
                            )
                        else:
                            required_paths = [
                                arg
                                for arg in action.argv
                                if arg.startswith(("inputs/", "receipts/"))
                                and work_assets.lookup(db, task_id, arg)
                            ]
                            assets, asset_digest = work_assets.snapshot(
                                db, task_id, required_paths=required_paths
                            )
                    if {f["path"].casefold() for f in files} & {
                        f["path"].casefold() for f in assets
                    }:
                        raise SandboxError("reserved_input_or_receipt_path")
                    files += assets
                    result["assets_sha256"] = asset_digest
                argv, outputs, timeout = action.argv, action.artifacts, action.timeout_seconds
                if action.tool == "transcribe_media":
                    plan = transcription_plan(action, assets)
                    result["transcription_source_sha256"] = plan["source_sha256"]
                    argv, outputs, timeout = (
                        plan["argv"],
                        plan["artifacts"],
                        plan["timeout_seconds"],
                    )
                if action.tool == "assemble_transcript":
                    if any(f["path"].startswith(".dsgpt-media/") for f in files):
                        raise SandboxError("reserved_media_manifest_path")
                    files.append(plan["manifest"])
                    result["transcription_source_sha256"] = plan["source_sha256"]
                    argv, outputs, timeout = (
                        plan["argv"],
                        plan["artifacts"],
                        plan["timeout_seconds"],
                    )
                if action.tool == "build_project":
                    argv = ["python3", "-I", "/opt/dsgpt/app_build_worker.py", action.target]
                    outputs = ["dist/build-report.json"]
                    outputs += [
                        "dist/app." + kind
                        for kind in (["apk", "exe"] if action.target == "apps" else [action.target])
                    ]
                    timeout = 900
                if action.tool == "browser":
                    if any(f["path"].startswith(".dsgpt-browser/") for f in files):
                        raise SandboxError("reserved_browser_path")
                    if action.path not in {f["path"] for f in files}:
                        raise SandboxError("browser_source_missing")
                    additions = {
                        ".dsgpt-browser/worker.py": Path(browser_worker.__file__).read_text(),
                        ".dsgpt-browser/request.json": canonical(
                            {
                                "path": action.path,
                                "steps": [s.model_dump() for s in action.browser_steps],
                            }
                        ),
                    }
                    files += [
                        {
                            "path": path,
                            "content": content,
                            "sha256": hashlib.sha256(content.encode()).hexdigest(),
                        }
                        for path, content in additions.items()
                    ]
                    argv = ["/usr/bin/python3", "-I", ".dsgpt-browser/worker.py"]
                    outputs = [".dsgpt-browser/screenshot.png", ".dsgpt-browser/result.json"]
                    timeout = 60
                result["requested_artifact_paths"] = [safe_path(path) for path in outputs]
                # Persist the validated output plan before dispatch. A hard process stop
                # cannot turn a failed replacement into the older successful artifact.
                with self.store.transaction() as db:
                    db.execute(
                        "UPDATE work_executions SET result=? WHERE id=?",
                        (canonical(result), identifier),
                    )
                output = await self.sandbox.execute(
                    identifier,
                    files,
                    argv,
                    outputs,
                    timeout,
                    **(
                        {"input_limit": 800 * 1024**2}
                        if action.tool in {"run", "transcribe_media", "assemble_transcript"}
                        and assets
                        else {}
                    ),
                )
                cleaned = True
                artifacts = output.pop("artifacts")
                result.update(output)
                if output["exit_code"]:
                    result["error"] = "command_failed"
                else:
                    if action.tool == "transcribe_media":
                        result["transcription"] = transcription_result(action, plan, artifacts)
                    if action.tool == "assemble_transcript":
                        result["transcription"] = assembly_result(plan, artifacts)
                    if action.tool == "build_project":
                        report = self.validate_app_report(artifacts, action.target)
                        if action.target in {"apk", "apps"}:
                            cleaned = False
                            artifacts, signing = await self.sign_apk(task_id, identifier, artifacts)
                            cleaned = True
                            report["checks"]["android"].update(signing)
                            report["artifacts"]["app.apk"] = next(
                                a["sha256"] for a in artifacts if a["path"] == "dist/app.apk"
                            )
                            body = (json.dumps(report, indent=2) + "\n").encode()
                            artifacts = [
                                a for a in artifacts if a["path"] != "dist/build-report.json"
                            ]
                            artifacts.append(
                                {
                                    "path": "dist/build-report.json",
                                    "content": body,
                                    "sha256": hashlib.sha256(body).hexdigest(),
                                }
                            )
                        result["verification"] = report
                    if action.tool == "run":
                        for index, artifact in enumerate(artifacts):
                            if artifact_kind(artifact["path"], artifact["content"]) == "apk":
                                original_path = artifact["path"]
                                candidate = {**artifact, "path": "dist/app.apk"}
                                cleaned = False
                                signed, signing = await self.sign_apk(
                                    task_id, identifier, [candidate]
                                )
                                cleaned = True
                                artifacts[index] = {**signed[0], "path": original_path}
                                result.setdefault("apk_signing", {})[original_path] = signing
                    status = "completed"
            except asyncio.CancelledError:
                cancelled, status = True, "interrupted"
                result["error"] = "execution_cancelled"
            except (SandboxError, OSError, TimeoutError, ValueError, KeyError) as exc:
                result["error"] = str(exc) if isinstance(exc, SandboxError) else "sandbox_failed"
            finally:
                if not cleaned:
                    try:
                        await self.sandbox.cleanup(identifier)
                        cleaned = True
                    except (SandboxError, OSError, TimeoutError, ValueError):
                        self.ready, self.error = False, "sandbox_cleanup_pending"
                metadata = []
                if shutil.disk_usage(self.store.directory).free < (
                    2 * sum(len(a["content"]) for a in artifacts) + 64 * 1024**2
                ):
                    artifacts, status = [], "failed"
                    result["error"] = "artifact_storage_full"
                with self.store.transaction() as db:
                    for artifact in artifacts:
                        artifact_id, content = uid(), artifact["content"]
                        db.execute(
                            "INSERT INTO work_artifacts VALUES(?,?,?,?,?,?,?)",
                            (
                                artifact_id,
                                identifier,
                                task_id,
                                artifact["path"],
                                artifact["sha256"],
                                len(content),
                                content,
                            ),
                        )
                        metadata.append(
                            {
                                "id": artifact_id,
                                "path": artifact["path"],
                                "sha256": artifact["sha256"],
                                "bytes": len(content),
                                "kind": artifact_kind(artifact["path"], content),
                            }
                        )
                    result["artifacts"] = metadata
                    db.execute(
                        "UPDATE work_executions SET status=?,result=?,cleanup_pending=?,"
                        "updated_at=? WHERE id=?",
                        (status, canonical(result), not cleaned, utcnow(), identifier),
                    )
                    if status == "completed" and action.tool in {
                        "transcribe_media",
                        "assemble_transcript",
                    }:
                        result["media_coverage"] = coverage_state(db, task_id, action.path)
                        db.execute(
                            "UPDATE work_executions SET result=? WHERE id=?",
                            (canonical(result), identifier),
                        )
            if status in {"failed", "interrupted"}:
                self.store.log("build_interrupted" if cancelled else "build_failed", identifier)
            if cancelled:
                raise asyncio.CancelledError
            return result

    @staticmethod
    def validate_app_report(artifacts, target):
        by_path = {a["path"]: a for a in artifacts}
        report = json.loads(by_path["dist/build-report.json"]["content"])
        if report.get("format") != "dsgpt-app-build-v1":
            raise SandboxError("app_build_report_invalid")
        for kind in ["apk", "exe"] if target == "apps" else [target]:
            artifact = by_path["dist/app." + kind]
            digest = hashlib.sha256(artifact["content"]).hexdigest()
            if (
                artifact_kind(artifact["path"], artifact["content"]) != kind
                or digest != artifact["sha256"]
                or report["artifacts"].get("app." + kind) != digest
            ):
                raise SandboxError("app_build_artifact_mismatch")
            checks = report["checks"].get("android" if kind == "apk" else "windows", {})
            valid = (
                (
                    type(checks.get("unit_tests")) is int
                    and checks["unit_tests"] > 0
                    and checks.get("lint_passed") is True
                    and checks.get("signature_verified") is True
                )
                if kind == "apk"
                else (
                    checks.get("portable_test_program_passed") is True
                    and checks.get("pe_verified") is True
                )
            )
            if not valid or checks.get("native_runtime_verified") is not False:
                raise SandboxError("app_build_checks_missing")
        return report

    async def sign_apk(self, task_id, identifier, artifacts):
        """Keep project keys out of generated-code containers and all model-visible artifacts."""
        apk = next(a for a in artifacts if a["path"] == "dist/app.apk")
        key = self.store.one("SELECT * FROM work_signing_keys WHERE task_id=?", (task_id,))
        inputs = {"input-apk.b64": base64.b64encode(apk["content"]).decode()}
        if key:
            if hashlib.sha256(key["key_bytes"]).hexdigest() != key["sha256"]:
                raise SandboxError("project_signing_key_integrity_failed")
            inputs["input-key.b64"] = base64.b64encode(key["key_bytes"]).decode()
        files = [
            {"path": path, "content": body, "sha256": hashlib.sha256(body.encode()).hexdigest()}
            for path, body in inputs.items()
        ]
        signed = await self.sandbox.execute(
            identifier,
            files,
            ["python3", "-I", "/opt/dsgpt/app_build_worker.py", "sign-android"],
            ["signed.apk", "signing.p12", "signing-report.json"],
            120,
            input_limit=384 * 1024**2,
        )
        if signed["exit_code"]:
            raise SandboxError("project_apk_signing_failed")
        outputs = {a["path"]: a for a in signed["artifacts"]}
        report = json.loads(outputs["signing-report.json"]["content"])
        if (
            report.get("signature_verified") is not True
            or report.get("signing_identity") != "project_persistent_development"
            or len(report.get("certificate_sha256", "")) != 64
        ):
            raise SandboxError("project_apk_signing_failed")
        private = outputs["signing.p12"]["content"]
        if key and private != key["key_bytes"]:
            raise SandboxError("project_signing_identity_changed")
        with self.store.transaction() as db:
            db.execute(
                "INSERT OR IGNORE INTO work_signing_keys VALUES(?,?,?,?)",
                (task_id, private, hashlib.sha256(private).hexdigest(), utcnow()),
            )
        replacement = outputs["signed.apk"]
        if artifact_kind("signed.apk", replacement["content"]) != "apk":
            raise SandboxError("signed_apk_invalid")
        replacement["path"] = "dist/app.apk"
        return [replacement if a["path"] == "dist/app.apk" else a for a in artifacts], report

    @staticmethod
    def summary(result):
        result = dict(result)
        for key in ("stdout", "stderr"):
            if key in result:
                text = result[key]
                raw = text.encode()
                result[key] = (
                    (
                        raw[:400].decode("utf-8", errors="ignore")
                        + "\n[... read_build_log for full output ...]\n"
                        + raw[-1000:].decode("utf-8", errors="ignore")
                    )
                    if len(raw) > 1500
                    else text
                )
                if result[key] != text:
                    result["log_excerpt"] = True
        return result

    @staticmethod
    def finish_evidence(db, task_id, target):
        files = [
            dict(r)
            for r in db.execute(
                "SELECT path,sha256 FROM work_files WHERE task_id=? ORDER BY path", (task_id,)
            )
        ]
        digest = snapshot_hash(files)
        latest = db.execute(
            "SELECT status,cleanup_pending FROM work_executions WHERE task_id=? "
            "AND snapshot_sha256=? ORDER BY step DESC LIMIT 1",
            (task_id, digest),
        ).fetchone()
        if not latest or latest[0] != "completed" or latest[1]:
            return None  # A known latest failure cannot be hidden by an older successful build.
        if target == "files":
            # Several commands may produce the requested windows and output formats.
            receipts = current_file_receipts(db, task_id, digest)
            if not receipts:
                return None
            executions = list(dict.fromkeys(receipt["execution_id"] for receipt in receipts))
            return {
                "execution_id": executions[0],
                "execution_ids": executions,
                "artifacts": [
                    {key: receipt[key] for key in ("id", "path", "sha256", "bytes", "kind")}
                    for receipt in receipts
                ],
                "snapshot_sha256": digest,
                "command_exit_code": 0,
                "native_runtime_verified": False,
            }
        required = {"apk", "exe"} if target == "apps" else {target}
        guided = db.execute("SELECT 1 FROM work_specs WHERE task_id=?", (task_id,)).fetchone()
        found, collected, executions = set(), [], []
        for row in db.execute(
            "SELECT id,result FROM work_executions WHERE task_id=? AND status='completed' "
            "AND cleanup_pending=0 AND snapshot_sha256=? ORDER BY updated_at DESC",
            (task_id, digest),
        ):
            result = json.loads(row["result"])
            if guided and target != "files" and not result.get("verification"):
                continue
            for artifact in result.get("artifacts", []):
                if target == "files" or artifact["kind"] in required:
                    found.add("files" if target == "files" else artifact["kind"])
                    collected.append(artifact)
            executions.append(row["id"])
            if required.issubset(found):
                return {
                    "execution_id": row["id"],
                    "execution_ids": executions,
                    "artifacts": collected,
                    "snapshot_sha256": digest,
                    "command_exit_code": 0,
                    "native_runtime_verified": False,
                }
        return None
