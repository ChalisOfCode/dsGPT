"""Late harness failures must never leave a successful acceptance report."""

import asyncio
import hashlib
import importlib.util
import json
import tempfile
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    "long_media_reporting", Path(__file__).parents[1] / "scripts/live_long_media.py"
)
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)

SAMPLE = b"benign synthetic PCM fixture for report control flow only"
SAMPLE_SHA = hashlib.sha256(SAMPLE).hexdigest()


class ReceiptStore:
    def __init__(self, path):
        self.rows = {}

    def transaction(self):
        return nullcontext(SimpleNamespace(execute=lambda *args: None))

    def one(self, query, args=()):
        return {"original": SAMPLE} if "SELECT original" in query else None

    def all(self, query, args):
        return self.rows[args[0]]


class SyntheticBuilds:
    """Supply coherent receipts; never start a container or perform recognition."""

    def __init__(self, store, image):
        self.store, self.image, self.windows = store, image, []

    async def probe(self):
        return {"ready": True, "probe": {"image_id": self.image}}

    async def execute(self, task_id, step, action):
        stem = f"media/window-{step}" if step < 5 else "media/complete"
        speech = {
            "transcript_path": "receipts/" + stem + ".json",
            "subtitles_path": "receipts/" + stem + ".srt",
            "start_seconds": (step - 1) * 300,
            "end_seconds": min(step * 300, 908.308),
        }
        content = json.dumps(
            {"window_count": 4, "full_audio_coverage": True, "windows": self.windows}
        ).encode()
        rows = [
            {"path": stem + suffix, "content": data, "sha256": hashlib.sha256(data).hexdigest()}
            for suffix, data in ((".json", content), (".srt", b"synthetic caption"))
        ]
        self.store.rows[str(step)] = rows
        if step < 5:
            self.windows.append(
                {
                    "path": speech["transcript_path"],
                    "subtitles_path": speech["subtitles_path"],
                    "sha256": rows[0]["sha256"],
                    "subtitles_sha256": rows[1]["sha256"],
                    "start": speech["start_seconds"],
                    "end": speech["end_seconds"],
                }
            )
        else:
            speech.update(assembled=True, full_audio_coverage=True, window_count=4)
        return {
            "exit_code": 0,
            "execution_id": str(step),
            "transcription": speech,
            "artifacts": [{k: v for k, v in row.items() if k != "content"} for row in rows],
            "media_coverage": {
                "selected_window_count": step,
                "assembly_ready": step == 4,
                "next_start": step * 300 if step < 4 else None,
            },
        }


@pytest.mark.parametrize("failure", ["cleanup", "final_write"])
def test_late_failure_overrides_success_and_bounds_error(tmp_path, monkeypatch, failure):
    def make_recording(raw, target, starts):
        target.write_bytes(raw)
        return {"duration": 908.308, "sha256": SAMPLE_SHA}

    helpers = SimpleNamespace(
        SAMPLE_SHA=SAMPLE_SHA,
        source_hashes=lambda: {"synthetic_backend": "fixed"},
        make_recording=make_recording,
        pair_verification=lambda *args: {"passed": True, "word_count": 60, "captions": 12},
    )
    monkeypatch.setattr(acceptance, "acceptance_helpers", lambda: helpers)
    monkeypatch.setattr(acceptance, "Store", ReceiptStore)
    monkeypatch.setattr(acceptance, "WorkBuilds", SyntheticBuilds)
    monkeypatch.setattr(
        acceptance,
        "WorkRegistry",
        lambda *args, **kwargs: SimpleNamespace(create=lambda *a, **kw: {"id": "synthetic-task"}),
    )
    error = f"synthetic {failure} failure " + "x" * 500
    temporary_directory = tempfile.TemporaryDirectory
    write_json = acceptance.write_json

    class CleanupFailure:
        def __init__(self, *args, **kwargs):
            self.inner = temporary_directory(*args, **kwargs)

        def __enter__(self):
            return self.inner.__enter__()

        def __exit__(self, *args):
            self.inner.__exit__(*args)
            raise OSError(error)

    def final_write_failure(path, value):
        write_json(path, value)
        if value.get("passed") is True:
            raise OSError(error)

    if failure == "cleanup":
        monkeypatch.setattr(acceptance.tempfile, "TemporaryDirectory", CleanupFailure)
    else:
        monkeypatch.setattr(acceptance, "write_json", final_write_failure)
    sample = tmp_path / "sample.wav"
    sample.write_bytes(SAMPLE)
    output = tmp_path / "evidence"
    with pytest.raises(OSError, match=f"synthetic {failure} failure"):
        asyncio.run(acceptance.run("synthetic-image", sample, output))

    report = json.loads((output / "validation.json").read_text())
    assert len(report["executions"]) == 5 and report["original_unchanged"]
    assert report["passed"] is False
    assert report["failure_type"] == "OSError"
    assert report["error"] == error[:400]
    assert report["harness_hashes"] == acceptance.harness_hashes()
    assert set(report["harness_hashes"]) == {"live_long_media.py", "live_media_agent.py"}
