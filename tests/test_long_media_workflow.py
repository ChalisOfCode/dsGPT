"""Long-window orchestration with synthetic speech receipts and the real data-only merger."""

import hashlib
import json

import pytest

from dsgpt import transcript_merge, work_assets
from dsgpt.builds import WorkBuilds
from dsgpt.project_tools import ProjectAction, ProjectTools
from dsgpt.sandbox import SandboxError
from dsgpt.storage import Store
from dsgpt.work import WorkRegistry
from dsgpt.work_asset_tools import asset_comparison_hint, list_assets, read_asset
from dsgpt.work_transcripts import assembly_plan, coverage_state


class WindowSandbox:
    """No shell execution: generate known receipts or call the pure merge implementation."""

    def __init__(self, folder, duration=2708.308):
        self.folder, self.duration, self.calls = folder, duration, []

    async def cleanup(self, identifier):
        pass

    async def execute(self, identifier, files, argv, artifacts, timeout, **kwargs):
        self.calls.append((files, argv, artifacts, timeout, kwargs))
        if argv[3] == "audio-transcribe":
            source = next(f for f in files if f["path"] == argv[4])
            start, count = float(argv[7]), float(argv[9])
            end = min(self.duration, start + count)
            words = [{"word": "hello", "start": start + 0.1, "end": start + 0.3, "confidence": 1.0}]
            segments = [
                {
                    "start": words[0]["start"],
                    "end": words[0]["end"],
                    "text": "hello",
                    "words": words,
                }
            ]
            report = {
                "source_sha256": source["sha256"],
                "engine": "vosk-0.3.45",
                "model": "fixture",
                "language": "en-US",
                "start": start,
                "end": end,
                "duration": self.duration,
                "next_start": end if end < self.duration else None,
                "word_count": 1,
                "uncertain_words": 0,
                "text": "hello",
                "segments": segments,
            }
            bodies = [json.dumps(report).encode(), transcript_merge.subtitles(segments).encode()]
        elif argv[3] == "audio-merge":
            folder = self.folder / identifier
            folder.mkdir(parents=True)
            for item in files:
                target = folder / item["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(
                    item["content"].encode()
                    if isinstance(item["content"], str)
                    else item["content"]
                )
            transcript_merge.merge(folder / argv[4], folder / argv[5], folder)
            bodies = [(folder / path).read_bytes() for path in artifacts]
        else:
            raise AssertionError("Fixture does not execute arbitrary commands")
        return {
            "exit_code": 0,
            "stdout": "data-only fixture",
            "stderr": "",
            "omitted_output_bytes": 0,
            "artifacts": [
                {"path": path, "content": body, "sha256": hashlib.sha256(body).hexdigest()}
                for path, body in zip(artifacts, bodies, strict=True)
            ],
        }


def setup(tmp_path, duration=2708.308):
    store = Store(tmp_path / "db")
    sandbox = WindowSandbox(tmp_path / "merge", duration)
    builds = WorkBuilds(store, sandbox=sandbox)
    builds.ready = True
    work = WorkRegistry(store, builds=builds)
    tid = work.create("Recording", "Transcribe the whole recording", build_target="files")["id"]
    with store.transaction() as db:
        db.execute("UPDATE work_tasks SET status='running' WHERE id=?", (tid,))
        db.execute(
            "INSERT INTO work_inputs VALUES(?,?,?,?,?)",
            (tid, "long.wav", b"fixture", hashlib.sha256(b"fixture").hexdigest(), "{}"),
        )
    return store, builds, tid, sandbox


async def window(builds, tid, step, start, duration=300):
    return await builds.execute(
        tid,
        step,
        ProjectAction(
            tool="transcribe_media",
            path="inputs/long.wav",
            start_seconds=start,
            duration_seconds=duration,
            summary="Transcribe next window",
        ),
    )


def read_all(db, tid, path):
    parts, offset = [], 0
    while True:
        page = read_asset(db, tid, path, offset)
        parts.append(page["content"])
        if page["next_offset"] is None:
            return "".join(parts)
        assert page["next_offset"] > offset
        offset = page["next_offset"]


async def test_ten_windows_remain_readable_and_assemble_with_exact_absolute_times(tmp_path):
    store, builds, tid, sandbox = setup(tmp_path)
    first = None
    for step in range(1, 11):
        result = await window(builds, tid, step, (step - 1) * 300)
        assert "error" not in result
        first = first or result
        progress = result["media_coverage"]
        assert progress["selected_window_count"] == step
        assert progress["next_start"] == (step * 300 if step < 10 else None)
        assert progress["assembly_ready"] == (step == 10)
    with store.connect() as db:
        page = list_assets(db, tid)
        assert len(page["receipts"]) == 16 and page["total_receipts"] == 20
        later = list_assets(db, tid, page["next_offset"])
        assert len(later["receipts"]) == 4 and later["next_offset"] is None
        assert later["catalog_sha256"] == page["catalog_sha256"]
        oldest = first["transcription"]["transcript_path"]
        assert oldest not in {item["path"] for item in page["receipts"]}
        assert json.loads(read_asset(db, tid, oldest)["content"])["start"] == 0
        selected, _ = work_assets.snapshot(db, tid, paths=[oldest])
        assert [item["path"] for item in selected] == [oldest]
        ordinary, _ = work_assets.snapshot(db, tid, required_paths=[oldest])
        assert oldest in {item["path"] for item in ordinary}
    chosen = ProjectAction(
        tool="assemble_transcript", path="inputs/long.wav", summary="Assemble all windows"
    )
    assembled = await builds.execute(tid, 11, chosen)
    assert "error" not in assembled
    speech = assembled["transcription"]
    assert speech["full_audio_coverage"] and speech["window_count"] == 10
    assert speech["preview_complete"] and speech["total_text_characters"] == len(speech["preview"])
    assert speech["verification"]["json_srt_consistent"]
    assert not speech["verification"]["recognition_accuracy_verified"]
    files, argv, outputs, _, _ = sandbox.calls[-1]
    assert argv[:4] == ["/usr/bin/python3", "-I", "/opt/dsgpt/asset_worker.py", "audio-merge"]
    assert len(outputs) == 2 and len(files) == 21  # 20 exact receipts plus backend manifest.
    assert "inputs/long.wav" not in {item["path"] for item in files}
    with store.connect() as db:
        report = json.loads(read_all(db, tid, speech["transcript_path"]))
        assert [segment["start"] for segment in report["segments"]] == [
            0.1 + 300 * i for i in range(10)
        ]
        assert report["window_count"] == 10 and report["end"] == 2708.308
        srt = read_asset(db, tid, speech["subtitles_path"])["content"]
        assert "\n\n10\n00:45:00,100" in srt
    replay_action, replay_result = builds.pending(tid, 11)
    assert replay_action["tool"] == "assemble_transcript" and replay_result == assembled


async def test_gap_blocks_assembly_until_filled_and_redundant_windows_are_explicit(tmp_path):
    store, builds, tid, _ = setup(tmp_path, 908.308)
    await window(builds, tid, 1, 0)
    await window(builds, tid, 2, 600)
    await window(builds, tid, 3, 900)
    with store.connect() as db:
        state = coverage_state(db, tid, "inputs/long.wav")
        assert state["next_start"] == 300 and not state["assembly_ready"]
        with pytest.raises(SandboxError, match="transcript_audio_coverage_incomplete"):
            assembly_plan(db, tid, "inputs/long.wav")
    await window(builds, tid, 4, 300)
    await window(builds, tid, 5, 0, 900)  # Redundant alternate complete prefix.
    with store.connect() as db:
        plan = assembly_plan(db, tid, "inputs/long.wav")
        assert plan["state"]["assembly_ready"] and plan["state"]["excluded_window_count"] > 0
    result = await builds.execute(
        tid,
        6,
        ProjectAction(
            tool="assemble_transcript",
            path="inputs/long.wav",
            summary="Merge selected complete chain",
        ),
    )
    assert "error" not in result
    with store.connect() as db:
        output = json.loads(read_all(db, tid, result["transcription"]["transcript_path"]))
        assert output["excluded_window_count"] == plan["state"]["excluded_window_count"]
        assert all(
            not item["included"] and not item["contents_validated"]
            for item in output["excluded_windows"]
        )


@pytest.mark.parametrize("change", ["deleted", "hash_changed", "failed", "foreign_task"])
async def test_current_receipt_invalidation_never_resurrects_older_window(tmp_path, change):
    store, builds, tid, _ = setup(tmp_path, 8.308)
    first = await window(builds, tid, 1, 0)
    latest = await window(builds, tid, 2, 0)
    artifact = latest["artifacts"][0]
    other = WorkRegistry(store).create("Other", "Separate task", build_target="files")["id"]
    with store.transaction() as db:
        if change == "deleted":
            db.execute("DELETE FROM work_artifacts WHERE id=?", (artifact["id"],))
        elif change == "hash_changed":
            db.execute("UPDATE work_artifacts SET sha256=? WHERE id=?", ("0" * 64, artifact["id"]))
        elif change == "failed":
            db.execute(
                "UPDATE work_executions SET status='failed' WHERE id=?", (latest["execution_id"],)
            )
        else:
            db.execute("UPDATE work_artifacts SET task_id=? WHERE id=?", (other, artifact["id"]))
        assert not coverage_state(db, tid, "inputs/long.wav")["assembly_ready"]
        assert work_assets.lookup(db, tid, first["transcription"]["transcript_path"]) is None


def test_conditional_continuation_does_not_force_whole_scope_for_excerpt():
    speech = {
        "source_path": "inputs/long.wav",
        "next_start": 300,
        "transcript_path": "receipts/a.json",
        "subtitles_path": "receipts/a.srt",
    }
    hint = asset_comparison_hint(speech, 1, coverage={"next_start": 300, "assembly_ready": False})
    assert "If the user requested the whole recording" in hint
    assert "explicitly requested excerpt" in hint and '"start_seconds":300' in hint
    excerpt = asset_comparison_hint(speech, 1, whole_recording=False)
    assert "transcribe_media" not in excerpt and "mark_requirement" in excerpt


async def test_unrelated_source_edit_keeps_original_audio_windows_for_current_assembly(tmp_path):
    store, builds, tid, _ = setup(tmp_path, 308.308)
    first = await window(builds, tid, 1, 0)
    with store.transaction() as db:
        ProjectTools.apply(
            db,
            tid,
            ProjectAction(
                tool="write_file", path="notes.txt", content="Recording notes", summary="Save notes"
            ),
        )
    second = await window(builds, tid, 2, 300)
    assert second["media_coverage"]["assembly_ready"]
    assert first["snapshot_sha256"] != second["snapshot_sha256"]
    result = await builds.execute(
        tid,
        3,
        ProjectAction(
            tool="assemble_transcript", path="inputs/long.wav", summary="Assemble original audio"
        ),
    )
    assert "error" not in result and result["transcription"]["window_count"] == 2
    with store.connect() as db:
        assert (
            builds.finish_evidence(db, tid, "files")["snapshot_sha256"] == result["snapshot_sha256"]
        )


def test_explicit_snapshot_limits_and_integrity_errors_are_not_silent(tmp_path, monkeypatch):
    store, _, tid, _ = setup(tmp_path)
    with store.connect() as db:
        with pytest.raises(SandboxError, match="required_asset_missing"):
            work_assets.snapshot(db, tid, paths=["receipts/missing.json"])
        monkeypatch.setattr(work_assets, "SNAPSHOT_BYTES", 3)
        with pytest.raises(SandboxError, match="required_assets_exceed_snapshot_limit"):
            work_assets.snapshot(db, tid, paths=["inputs/long.wav"])
        monkeypatch.setattr(work_assets, "SNAPSHOT_BYTES", 768 * 1024**2)
    with store.transaction() as db:
        db.execute("UPDATE work_inputs SET original=? WHERE task_id=?", (b"changed", tid))
        with pytest.raises(SandboxError, match="asset_content_integrity_failed"):
            work_assets.snapshot(db, tid, paths=["inputs/long.wav"])


async def test_failed_empty_replacement_hides_previous_pair_until_successful_retry(tmp_path):
    store, builds, tid, sandbox = setup(tmp_path, 8.308)
    first = await window(builds, tid, 1, 0)
    original = sandbox.execute

    async def fail(identifier, files, argv, artifacts, timeout, **kwargs):
        persisted = json.loads(
            store.one("SELECT result FROM work_executions WHERE id=?", (identifier,))["result"]
        )
        assert persisted["requested_artifact_paths"] == artifacts
        assert persisted["transcription_source_sha256"] == first["transcription_source_sha256"]
        return {
            "exit_code": 1,
            "stdout": "",
            "stderr": "injected failure",
            "omitted_output_bytes": 0,
            "artifacts": [],
        }

    sandbox.execute = fail
    failed = await window(builds, tid, 2, 0)
    assert failed["error"] == "command_failed" and failed["artifacts"] == []
    with store.connect() as db:
        for path in (
            first["transcription"]["transcript_path"],
            first["transcription"]["subtitles_path"],
        ):
            assert work_assets.lookup(db, tid, path) is None
        assert not coverage_state(db, tid, "inputs/long.wav")["assembly_ready"]
    # Emulate the exact durable pre-dispatch state of a process that died without finally.
    pre_dispatch = {
        key: failed[key]
        for key in (
            "execution_id",
            "snapshot_sha256",
            "assets_sha256",
            "transcription_source_sha256",
            "requested_artifact_paths",
        )
    }
    with store.transaction() as db:
        db.execute(
            "UPDATE work_executions SET status='running',cleanup_pending=1,result=? WHERE id=?",
            (json.dumps(pre_dispatch), failed["execution_id"]),
        )
    await builds.recover()
    recovered = json.loads(
        store.one("SELECT result FROM work_executions WHERE id=?", (failed["execution_id"],))[
            "result"
        ]
    )
    assert recovered["error"] == "execution_interrupted"
    assert all(recovered[key] == value for key, value in pre_dispatch.items())
    with store.connect() as db:
        assert work_assets.lookup(db, tid, first["transcription"]["transcript_path"]) is None
        assert not coverage_state(db, tid, "inputs/long.wav")["assembly_ready"]
    sandbox.execute, builds.ready = original, True
    fresh = await window(builds, tid, 3, 0)
    assert fresh["media_coverage"]["assembly_ready"]
    with store.connect() as db:
        assert (
            work_assets.lookup(db, tid, fresh["transcription"]["transcript_path"])["id"]
            == fresh["artifacts"][0]["id"]
        )
