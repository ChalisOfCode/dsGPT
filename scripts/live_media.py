"""Public download -> isolated local speech recognition -> reusable timestamped results."""

import argparse
import asyncio
import hashlib
import json
import tempfile
from pathlib import Path

from dsgpt.builds import WorkBuilds
from dsgpt.project_tools import ProjectAction
from dsgpt.storage import Store
from dsgpt.work import WorkRegistry

URL = "https://raw.githubusercontent.com/alphacep/vosk-api/master/python/example/test.wav"
SHA = "dcfea5712c43a43ba7ae8083afb39d36993e5a69c46e88b68aaa72b65cb615bb"


async def run(image, output):
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        store = Store(Path(directory))
        builds = WorkBuilds(store, image)
        await builds.probe()
        work = WorkRegistry(store, builds=builds)
        task = work.create(
            "Speech fixture", "Transcribe public speech", build_target="files", web_mode="on"
        )
        tid = task["id"]
        with store.transaction() as db:
            db.execute("UPDATE work_tasks SET status='running' WHERE id=?", (tid,))
        download = await work.web.execute(
            tid,
            1,
            ProjectAction(
                tool="download_file", summary="Public Vosk sample", url=URL, path="sample.wav"
            ),
        )
        (output / "download.json").write_text(json.dumps(download, indent=2))
        assert download.get("sha256") == SHA, download
        sample = store.one("SELECT original FROM work_inputs WHERE task_id=?", (tid,))["original"]
        assert hashlib.sha256(sample).hexdigest() == SHA
        (output / "sample.wav").write_bytes(sample)

        async def execute(step, argv=None, artifacts=None, *, action=None):
            result = await builds.execute(
                tid,
                step,
                action
                or ProjectAction(
                    tool="run",
                    summary="Verify speech workflow",
                    argv=argv,
                    artifacts=artifacts or [],
                    timeout_seconds=900,
                ),
            )
            (output / f"execution-{step}.json").write_text(json.dumps(result, indent=2))
            assert not result.get("error"), result
            for artifact in store.all(
                "SELECT * FROM work_artifacts WHERE execution_id=?", (result["execution_id"],)
            ):
                destination = output / artifact["path"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(artifact["content"])
            return result

        async def transcribe(step, path, prefix, **window):
            result = await execute(
                step,
                action=ProjectAction(
                    tool="transcribe_media", summary="Transcribe saved media", path=path, **window
                ),
            )
            # Both outputs are selected by the backend, never by a model-supplied command.
            saved = store.all(
                "SELECT path,content FROM work_artifacts WHERE execution_id=?",
                (result["execution_id"],),
            )
            assert len(saved) == 2 and {Path(a["path"]).suffix for a in saved} == {".json", ".srt"}
            paths = {}
            for artifact in saved:
                suffix = Path(artifact["path"]).suffix
                (output / (prefix + suffix)).write_bytes(artifact["content"])
                paths[suffix] = "receipts/" + artifact["path"]
            return paths

        worker = ["/usr/bin/python3", "-I", "/opt/dsgpt/asset_worker.py"]
        speech_paths = await transcribe(2, "inputs/sample.wav", "speech")
        report = json.loads((output / "speech.json").read_text())
        assert report["source_sha256"] == SHA
        assert report["text"].startswith("one zero zero zero one"), report
        assert report["text"].endswith("zero one eight zero three"), report
        assert report["next_start"] is None and report["word_count"] >= 13
        assert "-->" in (output / "speech.srt").read_text()
        reuse = await execute(3, [*worker, "read", speech_paths[".json"]], [])
        assert "one zero zero zero one" in reuse["stdout"]
        with store.connect() as db:
            read = work.tools.apply(
                db,
                tid,
                ProjectAction(
                    tool="read_asset", summary="Read saved transcript", path=speech_paths[".json"]
                ),
            )
        assert "one zero zero zero one" in read["content"] and not read.get("error"), read
        (output / "read-asset.json").write_text(json.dumps(read, indent=2))
        await execute(
            4,
            [
                "ffmpeg",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=blue:s=320x240:r=10",
                "-i",
                "inputs/sample.wav",
                "-t",
                "8.308",
                "-c:v",
                "libx264",
                "-threads",
                "2",
                "-c:a",
                "aac",
                "-y",
                "narrated.mp4",
            ],
            ["narrated.mp4"],
        )
        await transcribe(
            5, "receipts/narrated.mp4", "video", start_seconds=3, duration_seconds=5.308
        )
        video = json.loads((output / "video.json").read_text())
        assert video["word_count"] >= 7 and video["segments"][0]["start"] >= 3
        original = store.one("SELECT original FROM work_inputs WHERE task_id=?", (tid,))["original"]
        assert hashlib.sha256(original).hexdigest() == SHA
        assert not store.one("SELECT 1 FROM work_executions WHERE cleanup_pending=1")
        (output / "validation.json").write_text(
            json.dumps(
                {
                    "passed": True,
                    "download": "live public HTTPS, no cookies",
                    "transcription": "real local Vosk, isolated Docker, CPU only",
                    "checks": [
                        "original hash",
                        "known spoken words",
                        "subtitle timestamps",
                        "typed transcription automatically collects JSON and SRT",
                        "bounded saved transcript reads",
                        "fresh-container receipt reuse",
                        "video speech and time offset",
                    ],
                    "model_driven": False,
                },
                indent=2,
            )
        )
        print("Public file and isolated audio/video speech checks passed", flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--image", required=True)
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args()
    asyncio.run(run(args.image, args.output))
