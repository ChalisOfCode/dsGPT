"""Bounded real-model edits, then independent production builds of both apps."""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from dsgpt.app_builder import project_files
from dsgpt.builds import WorkBuilds, snapshot_hash
from dsgpt.config import Model
from dsgpt.project_tools import ProjectAction, ProjectTools
from dsgpt.storage import Store
from dsgpt.work import WorkRegistry

sys.path.insert(0, str(Path(__file__).resolve().parent))
from live_complex_app_model import (  # noqa: E402
    MeasuredInference,
    digest,
    provenance,
    save_report,
    saved_sources,
)
from prepare_complex_model_ci import MODEL_SHA256, MODEL_TAG  # noqa: E402

LABELS = {"initial": "Smoke ready", "followup": "Smoke updated"}
MODEL_SECONDS = 360
TITLE = "dsGPT smoke"


async def edits(inference, model, files, label, budget):
    schema = {
        "type": "object",
        "properties": {
            "edits": {
                "type": "array",
                "minItems": 2,
                "maxItems": 2,
                "items": {
                    "oneOf": [
                        {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "tool": {"const": "edit_file"},
                                "path": {"const": f["path"]},
                                "expected_sha256": {"const": f["sha256"]},
                                "old_text": {"type": "string"},
                                "new_text": {"type": "string"},
                                "summary": {"type": "string"},
                            },
                            "required": [
                                "tool",
                                "path",
                                "expected_sha256",
                                "old_text",
                                "new_text",
                                "summary",
                            ],
                        }
                        for f in files
                    ],
                },
            },
        },
        "required": ["edits"],
        "additionalProperties": False,
    }
    messages = [
        {
            "role": "user",
            "content": (
                f"Set the Android on-screen heading and Windows window title to {label!r}. "
                "Return exactly one edit_file per supplied file. Copy its path, sha256 and a "
                "unique short old_text. Make only the label changes. Source snapshots:\n"
                + json.dumps(files, ensure_ascii=False)
            ),
        }
    ]
    fragments = []
    async with asyncio.timeout(budget):
        async for event in inference.stream(model, messages, response_schema=schema):
            if event["kind"] == "delta":
                fragments.append(event["data"]["text"])
            if event["kind"] == "warning":
                raise ValueError("Incomplete model response")
    payload = json.loads("".join(fragments))
    actions = [ProjectAction.model_validate(item) for item in payload["edits"]]
    hashes = {f["path"]: f["sha256"] for f in files}
    if (
        len(actions) != 2
        or {a.path for a in actions} != hashes.keys()
        or any(a.tool != "edit_file" or a.expected_sha256 != hashes[a.path] for a in actions)
    ):
        raise ValueError("Model did not return one targeted edit per platform")
    return actions


async def run(args, report):
    args.state.mkdir(parents=True, exist_ok=False)
    store = Store(args.state)
    builds = WorkBuilds(store, args.image)
    await builds.probe()
    if not builds.ready:
        raise RuntimeError("Production sandbox is not ready")
    model = Model(
        "smoke",
        "Exact local 9B",
        "ollama",
        "http://127.0.0.1:11435",
        MODEL_TAG,
        expected_digest=MODEL_SHA256,
        abliterated=True,
        context=16384,
        output_tokens=768,
    )
    inference = MeasuredInference(False, report["inference_calls"], cpu_threads=4)
    work = WorkRegistry(store, builds=builds)
    tid = work.create(TITLE, "Build and revise the two smoke labels.", build_target="apps")["id"]
    report["task_id"] = tid
    report["isolation_probe"] = builds.probe_evidence
    with store.transaction() as db:
        for platform in ("android", "windows"):
            for path, content in project_files(platform, TITLE, tid).items():
                result = ProjectTools.apply(
                    db,
                    tid,
                    ProjectAction(
                        tool="write_file",
                        path=path,
                        content=content,
                        summary="Standard scaffold",
                    ),
                )
                if result.get("error"):
                    raise ValueError(result["error"])
        db.execute("UPDATE work_tasks SET status='running' WHERE id=?", (tid,))
    budget, certificate, previous_label = MODEL_SECONDS, None, TITLE
    for step, (phase, label) in enumerate(LABELS.items(), 1):
        files = [
            f
            for f in saved_sources(store, tid)
            if f["path"].endswith(("/MainActivity.kt", "/main.cpp"))
        ]
        started = time.monotonic()
        try:
            actions = await edits(inference, model, files, label, budget)
        finally:
            budget -= time.monotonic() - started
            report["model_seconds"] = round(MODEL_SECONDS - budget, 3)
        evidence = report["phases"][phase] = {"model_actions": [a.model_dump() for a in actions]}
        with store.transaction() as db:
            for action in actions:
                result = ProjectTools.apply(db, tid, action)
                if result.get("error"):
                    raise ValueError(result["error"])
            by_path = dict(
                db.execute("SELECT path,content FROM work_files WHERE task_id=?", (tid,))
            )
            for before in files:
                expected = before["content"].replace(
                    json.dumps(previous_label), json.dumps(label), 1
                )
                if expected == before["content"] or by_path[before["path"]] != expected:
                    raise ValueError("Model edit changed more than the requested UI label")
            previous_label = label
            # Harness checks assert only the requested literal; native runners check UI.
            literal = json.dumps(label)
            tests = {
                "android/app/src/test/java/SmokeLabelTest.kt": (
                    "import java.io.File\nimport org.junit.Test\n"
                    "import org.junit.Assert.assertTrue\n"
                    "class SmokeLabelTest { @Test fun requestedLabelIsPresent() {\n"
                    'val activity = File("src/main/java").walkTopDown()'
                    '.single { it.name == "MainActivity.kt" }\n'
                    f"assertTrue(activity.readText().contains({json.dumps(literal)})) }} }}\n"
                ),
                "windows/tests.cpp": "#include <fstream>\n#include <iterator>\n#include <string>\n"
                'int main() { std::ifstream source("windows/main.cpp");\n'
                "std::string text((std::istreambuf_iterator<char>(source)), {});\n"
                f"return text.find({json.dumps(literal)}) == std::string::npos; }}\n",
            }
            for path, content in tests.items():
                existing = db.execute(
                    "SELECT content,sha256 FROM work_files WHERE task_id=? AND path=?", (tid, path)
                ).fetchone()
                if existing:
                    action = ProjectAction(
                        tool="edit_file",
                        path=path,
                        old_text=existing["content"],
                        new_text=content,
                        expected_sha256=existing["sha256"],
                        summary="Independent smoke assertion for revised label",
                    )
                else:
                    action = ProjectAction(
                        tool="write_file",
                        path=path,
                        content=content,
                        summary="Independent smoke assertion",
                    )
                result = ProjectTools.apply(db, tid, action)
                if result.get("error"):
                    raise ValueError(result["error"])
        evidence["source_sha256"] = snapshot_hash(saved_sources(store, tid))
        save_report(args.output, report)
        async with asyncio.timeout(30):
            await inference.release_resident()
        async with asyncio.timeout(240):
            result = await builds.execute(
                tid,
                step,
                ProjectAction(
                    tool="build_project",
                    target="apps",
                    summary="Independent smoke compilation",
                ),
            )
        evidence["build"] = result
        if result.get("error") or result.get("snapshot_sha256") != evidence["source_sha256"]:
            raise ValueError("Model-edited source did not compile")
        signer = result["verification"]["checks"]["android"]["certificate_sha256"]
        if not signer or (certificate is not None and signer != certificate):
            raise ValueError("Smoke APK signing continuity failed")
        certificate = signer
        artifacts = {}
        for artifact in result["artifacts"]:
            if artifact["kind"] not in {"apk", "exe"}:
                continue
            row = store.one("SELECT content FROM work_artifacts WHERE id=?", (artifact["id"],))
            if digest(row["content"]) != artifact["sha256"]:
                raise ValueError("Build artifact digest mismatch")
            target = args.artifacts / phase / "artifacts" / ("dist/app." + artifact["kind"])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(row["content"])
            artifacts[artifact["kind"]] = artifact["sha256"]
        if set(artifacts) != {"apk", "exe"}:
            raise ValueError("Both native artifacts are required")
        evidence.update(artifacts=artifacts, android_certificate_sha256=signer)
        save_report(args.output, report)
    report["status"] = "compiled"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    for name in ("state", "output", "artifacts"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    report = {
        "format": "dsgpt-bounded-model-smoke-v1",
        "status": "running",
        "source": provenance()["checkout_commit"],
        "model_digest": MODEL_SHA256,
        "model_budget_seconds": MODEL_SECONDS,
        "inference_calls": [],
        "phases": {},
    }
    try:
        asyncio.run(run(args, report))
    except BaseException as exc:
        report.update(status="failed", error=type(exc).__name__)
        raise
    finally:
        save_report(args.output, report)


if __name__ == "__main__":
    main()
