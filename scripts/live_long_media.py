"""Deterministic long-recording evidence using the real isolated Docker tool runner.

This checks tools and the known clean speech fixture, not model-driven planning or
general recognition accuracy. No model endpoint, host worker fallback, or network
download is used; --sample must be the hash-pinned sample exported by live_media.py.
"""

import argparse
import asyncio
import hashlib
import importlib.util
import json
import tempfile
import time
from pathlib import Path

from dsgpt.builds import WorkBuilds
from dsgpt.project_tools import ProjectAction, safe_path
from dsgpt.storage import Store
from dsgpt.work import WorkRegistry


def acceptance_helpers():
    spec = importlib.util.spec_from_file_location(
        "long_media_acceptance_helpers", Path(__file__).resolve().with_name("live_media_agent.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def harness_hashes():
    script = Path(__file__).resolve()
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (script, script.with_name("live_media_agent.py"))
    }


async def run(image, sample, output):
    output.mkdir(parents=True, exist_ok=False)
    harness_snapshot = harness_hashes()
    helpers = acceptance_helpers()
    report = {
        "passed": False,
        "model_driven": False,
        "execution": "production WorkBuilds with real checked networkless Docker containers",
        "scope": "Known clean 908.308-second PCM fixture, four windows and one assembled pair",
        "general_recognition_accuracy_verified": False,
        "image_id": image,
        "source_hashes": helpers.source_hashes(),
        "harness_hashes": harness_snapshot,
        "executions": [],
    }
    report_path = output / "validation.json"
    write_json(report_path, report)
    try:
        raw_sample = sample.read_bytes()
        assert hashlib.sha256(raw_sample).hexdigest() == helpers.SAMPLE_SHA, "sample hash mismatch"
        source = output / "long.wav"
        fixture = helpers.make_recording(raw_sample, source, [0, 300, 600, 900])
        assert abs(fixture["duration"] - 908.308) < 0.000001, fixture
        report["fixture"] = fixture
        write_json(output / "fixture.json", fixture)
        with tempfile.TemporaryDirectory(prefix="dsgpt-long-media-") as directory:
            store = Store(Path(directory))
            builds = WorkBuilds(store, image)
            probe = await builds.probe()
            write_json(output / "docker-probe.json", probe)
            assert probe["ready"] and probe["probe"]["image_id"] == image, probe
            report["docker_probe"] = probe
            work = WorkRegistry(store, builds=builds)
            task = work.create(
                "Long speech tool acceptance",
                "Transcribe the entire known recording and assemble one JSON/SRT pair.",
                build_target="files",
                originals=[
                    {
                        "name": "long.wav",
                        "original": source.read_bytes(),
                        "sha256": fixture["sha256"],
                        "extraction": {"fixture": True},
                    }
                ],
            )
            tid = task["id"]
            report["task_id"] = tid
            with store.transaction() as db:
                db.execute("UPDATE work_tasks SET status='running' WHERE id=?", (tid,))

            async def execute(step, action):
                started = time.monotonic()
                result = await builds.execute(tid, step, action)
                report["executions"].append(
                    {
                        "step": step,
                        "action": action.model_dump(exclude_defaults=True),
                        "seconds": round(time.monotonic() - started, 3),
                        "result": result,
                    }
                )
                write_json(output / f"execution-{step}.json", report["executions"][-1])
                write_json(report_path, report)
                assert not result.get("error") and result.get("exit_code") == 0, result
                saved = store.all(
                    "SELECT path,content,sha256 FROM work_artifacts WHERE execution_id=?",
                    (result["execution_id"],),
                )
                assert len(saved) == 2 and {Path(row["path"]).suffix for row in saved} == {
                    ".json",
                    ".srt",
                }
                for item in saved:
                    assert hashlib.sha256(item["content"]).hexdigest() == item["sha256"]
                    target = output / safe_path(item["path"])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(item["content"])
                print(
                    json.dumps(
                        {
                            "step": step,
                            "tool": action.tool,
                            "seconds": report["executions"][-1]["seconds"],
                        }
                    ),
                    flush=True,
                )
                return result

            windows = []
            for step, start in enumerate((0, 300, 600, 900), 1):
                result = await execute(
                    step,
                    ProjectAction(
                        tool="transcribe_media",
                        path="inputs/long.wav",
                        start_seconds=start,
                        duration_seconds=300,
                        summary="Transcribe next known audio window",
                    ),
                )
                progress = result["media_coverage"]
                assert progress["selected_window_count"] == step
                assert progress["assembly_ready"] == (step == 4)
                assert progress["next_start"] == (step * 300 if step < 4 else None)
                windows.append(result)
            assembled = await execute(
                5,
                ProjectAction(
                    tool="assemble_transcript",
                    path="inputs/long.wav",
                    summary="Assemble all known windows",
                ),
            )
            speech = assembled["transcription"]
            assert (
                speech["assembled"]
                and speech["full_audio_coverage"]
                and speech["window_count"] == 4
            )
            pair = {}
            for item in store.all(
                "SELECT path,content FROM work_artifacts WHERE execution_id=?",
                (assembled["execution_id"],),
            ):
                suffix = Path(item["path"]).suffix
                pair[suffix] = item["content"]
                (output / ("complete" + suffix)).write_bytes(item["content"])
            oracle = helpers.pair_verification(pair[".json"], pair[".srt"], fixture)
            assert oracle["passed"] and oracle["word_count"] == 60 and oracle["captions"] == 12, (
                oracle
            )
            combined = json.loads(pair[".json"])
            assert combined["window_count"] == 4 and combined["full_audio_coverage"]
            for item, result in zip(combined["windows"], windows, strict=True):
                expected = result["transcription"]
                hashes = {"receipts/" + a["path"]: a["sha256"] for a in result["artifacts"]}
                assert item["path"] == expected["transcript_path"]
                assert item["subtitles_path"] == expected["subtitles_path"]
                assert item["sha256"] == hashes[item["path"]]
                assert item["subtitles_sha256"] == hashes[item["subtitles_path"]]
                assert (
                    item["start"] == expected["start_seconds"]
                    and item["end"] == expected["end_seconds"]
                )
            original = store.one("SELECT original FROM work_inputs WHERE task_id=?", (tid,))[
                "original"
            ]
            assert hashlib.sha256(original).hexdigest() == fixture["sha256"]
            assert not store.one("SELECT 1 FROM work_executions WHERE cleanup_pending=1")
            assert helpers.source_hashes() == report["source_hashes"], (
                "backend source changed during test"
            )
            report.update(
                oracle=oracle,
                window_count=4,
                original_unchanged=True,
                all_containers_cleaned=True,
            )
        assert harness_hashes() == harness_snapshot, "acceptance scripts changed during test"
        report["passed"] = True
        write_json(report_path, report)
    except Exception as exc:
        report.update(passed=False, failure_type=type(exc).__name__, error=str(exc)[:400])
        write_json(report_path, report)
        raise
    print("Isolated long-recording and assembly checks passed; no model-planning claim", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--sample", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    asyncio.run(run(arguments.image, arguments.sample, arguments.output))
