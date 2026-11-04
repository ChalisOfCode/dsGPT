"""Typed media orchestration fixtures; not evidence of actual speech recognition."""

import asyncio
import hashlib
import json
from dataclasses import replace

import pytest
from pydantic import ValidationError

from dsgpt import work_assets
from dsgpt.builds import WorkBuilds
from dsgpt.config import Model
from dsgpt.inference import ollama_input_estimate
from dsgpt.project_tools import ProjectAction, ProjectTools, action_schema
from dsgpt.scheduler import InferenceScheduler
from dsgpt.storage import Store
from dsgpt.work import WorkRegistry, research_page
from dsgpt.work_asset_tools import (
    ASSET_PAGE_BYTES,
    read_asset,
    related_asset_read,
    transcription_plan,
)


class SpeechSandbox:
    def __init__(self, omit_srt=False, fail=False, silence=False):
        self.calls, self.cleaned = [], []
        self.omit_srt, self.fail, self.silence = omit_srt, fail, silence

    async def cleanup(self, identifier):
        self.cleaned.append(identifier)

    async def execute(self, identifier, files, argv, artifacts, timeout, **kwargs):
        self.calls.append((identifier, files, argv, artifacts, timeout, kwargs))
        source = next(item for item in files if item["path"] == argv[4])
        start, duration = float(argv[7]), float(argv[9])
        report = {
            "source_sha256": source["sha256"],
            "start": start,
            "end": min(1200, start + duration),
            "duration": 1200,
            "next_start": start + duration if start + duration < 1200 else None,
            "word_count": 0 if self.silence else 2,
            "text": "" if self.silence else "fixture words",
        }
        bodies = [json.dumps(report).encode(), b"" if self.silence else b"fixture subtitles\n"]
        return {
            "exit_code": 1 if self.fail else 0,
            "stdout": "fixture only",
            "stderr": "injected failure" if self.fail else "",
            "omitted_output_bytes": 0,
            "artifacts": []
            if self.fail
            else [
                {"path": path, "content": body, "sha256": hashlib.sha256(body).hexdigest()}
                for path, body in zip(artifacts, bodies, strict=True)
                if not (self.omit_srt and path.endswith(".srt"))
            ],
        }


def setup(tmp_path, target="files", sandbox=None):
    store = Store(tmp_path)
    sandbox = sandbox or SpeechSandbox()
    builds = WorkBuilds(store, sandbox=sandbox)
    builds.ready = True
    model = Model("local", "Local", "ollama", "http://127.0.0.1:11434", "local")
    work = WorkRegistry(
        store, models={"local": model}, builds=builds, scheduler=InferenceScheduler(store)
    )
    tid = work.create("Speech", "Transcribe saved audio", "local", build_target=target, start=True)[
        "id"
    ]
    with store.transaction() as db:
        db.execute("UPDATE work_tasks SET status='running' WHERE id=?", (tid,))
        db.execute(
            "INSERT INTO work_inputs VALUES(?,?,?,?,?)",
            (
                tid,
                "speech.wav",
                b"fixture audio",
                hashlib.sha256(b"fixture audio").hexdigest(),
                "{}",
            ),
        )
    return store, work, tid, sandbox


def action(**changes):
    return ProjectAction(
        **{
            "tool": "transcribe_media",
            "path": "inputs/speech.wav",
            "summary": "Transcribe",
            **changes,
        }
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"path": "/etc/passwd"},
        {"path": "speech.wav"},
        {"path": "https://example.org/a.wav"},
        {"path": "inputs/../other.wav"},
        {"path": "C:/audio.wav"},
        {"start_seconds": -1},
        {"start_seconds": float("inf")},
        {"start_seconds": 604801},
        {"duration_seconds": 0},
        {"duration_seconds": 901},
        {"duration_seconds": float("nan")},
        {"argv": ["anything"]},
        {"artifacts": ["only.json"]},
        {"timeout_seconds": 1},
    ],
)
def test_typed_action_rejects_paths_windows_and_command_overrides(changes):
    with pytest.raises(ValidationError):
        action(**changes)


def test_schema_exposes_only_saved_paths_and_isolated_media_tools():
    def variants(**kwargs):
        return {v["properties"]["tool"]["const"]: v for v in action_schema(**kwargs)["oneOf"]}

    assert "transcribe_media" not in variants()
    assert "read_asset" not in variants()
    assert "transcribe_media" not in variants(isolated_execution=True, asset_paths=[])
    tools = variants(isolated_execution=True, asset_paths=["inputs/speech.wav"])
    speech = tools["transcribe_media"]["properties"]
    assert set(speech) == {"tool", "summary", "path", "start_seconds", "duration_seconds"}
    assert speech["path"] == {"enum": ["inputs/speech.wav"]}
    assert tools["read_asset"]["properties"]["offset"]["maximum"] == 768 * 1024**2
    assert tools["read_file"]["properties"]["offset"]["maximum"] == 262144
    with pytest.raises(ValidationError):
        ProjectAction(tool="read_file", path="test.txt", offset=262145, summary="Read")


@pytest.mark.parametrize("silence", [False, True])
async def test_transcription_collects_both_paths_and_replays_typed_action_once(tmp_path, silence):
    store, work, tid, sandbox = setup(tmp_path, sandbox=SpeechSandbox(silence=silence))
    result = await work.builds.execute(tid, 1, action())
    assert "error" not in result
    _, files, argv, outputs, timeout, kwargs = sandbox.calls[0]
    assert argv[:5] == [
        "/usr/bin/python3",
        "-I",
        "/opt/dsgpt/asset_worker.py",
        "audio-transcribe",
        "inputs/speech.wav",
    ]
    assert argv[5] == outputs[0] and outputs[1] == outputs[0].removesuffix(".json") + ".srt"
    assert argv[6:] == ["--start", "0.0", "--duration", "300.0"]
    assert timeout == 900 and kwargs == {"input_limit": 800 * 1024**2}
    assert (
        transcription_plan(action(start_seconds=0, duration_seconds=300), files)["artifacts"]
        == outputs
    )
    assert transcription_plan(action(start_seconds=300), files)["artifacts"] != outputs
    saved_action, saved_result = work.builds.pending(tid, 1)
    assert saved_action["tool"] == "transcribe_media" and saved_result == result
    assert ProjectAction.model_validate(saved_action) == action()
    with store.transaction() as db:
        db.execute("UPDATE work_tasks SET status='queued' WHERE id=?", (tid,))
    await work._step(store.one("SELECT * FROM work_tasks WHERE id=?", (tid,)))
    assert len(sandbox.calls) == 1 and work.builds.pending(tid, 1) is None
    step = store.one("SELECT action,result FROM work_steps WHERE task_id=?", (tid,))
    assert json.loads(step["action"])["tool"] == "transcribe_media"
    metadata = json.loads(step["result"])["transcription"]
    assert metadata["next_start"] == 300
    assert metadata["status"] == ("no_speech_detected" if silence else "transcribed")
    with store.connect() as db:
        for key in ("transcript_path", "subtitles_path"):
            output = ProjectTools.apply(db, tid, action(tool="read_asset", path=metadata[key]))
            assert output["next_offset"] is None and output["sha256"]
        assert len(work_assets.catalog(db, tid)["receipts"]) == 2


async def test_permission_missing_assets_and_missing_output_cannot_claim_success(tmp_path):
    store, work, tid, sandbox = setup(tmp_path)
    missing = await work.builds.execute(tid, 1, action(path="inputs/missing.wav"))
    assert missing["error"] == "transcription_saved_asset_required" and not sandbox.calls
    sandbox.omit_srt = True
    missing_output = await work.builds.execute(tid, 2, action())
    assert missing_output["error"] == "transcription_outputs_missing"
    with store.connect() as db:
        assert work_assets.catalog(db, tid)["receipts"] == []
        assert not work.builds.finish_evidence(db, tid, "files")
        db.execute("DELETE FROM work_build_profiles WHERE task_id=?", (tid,))
        db.commit()
    denied = await work.builds.execute(tid, 3, action())
    assert denied["error"] == "transcription_requires_isolated_work" and len(sandbox.calls) == 1
    with store.connect() as db:
        assert (
            read_asset(db, tid, "inputs/speech.wav")["error"] == "asset_tool_requires_isolated_work"
        )


async def test_identical_transcriptions_cannot_evade_no_progress_with_new_receipt_ids(tmp_path):
    store, work, tid, _ = setup(tmp_path)
    for step in range(1, 4):
        with store.transaction() as db:
            db.execute("UPDATE work_tasks SET status='running' WHERE id=?", (tid,))
        session = store.one("SELECT * FROM work_sessions WHERE task_id=?", (tid,))
        result = await work.builds.execute(tid, step, action())
        work._commit(tid, session, action(), result)
    assert store.one("SELECT status FROM work_tasks WHERE id=?", (tid,))["status"] == "blocked"
    last = store.one("SELECT result FROM work_steps WHERE task_id=? AND step=3", (tid,))
    assert json.loads(last["result"])["error"] == "no_progress"


def test_asset_read_pages_utf8_bytes_without_host_or_cross_task_access(tmp_path):
    store, work, tid, _ = setup(tmp_path)
    content = ("a" * (ASSET_PAGE_BYTES - 1) + "é🙂" + "tail" * 70000).encode()
    with store.transaction() as db:
        db.execute(
            "INSERT INTO work_inputs VALUES(?,?,?,?,?)",
            (tid, "text.txt", content, hashlib.sha256(content).hexdigest(), "{}"),
        )
        first = read_asset(db, tid, "inputs/text.txt")
        assert first["content"] == "a" * (ASSET_PAGE_BYTES - 1)
        assert first["next_offset"] == ASSET_PAGE_BYTES - 1
        second = read_asset(db, tid, "inputs/text.txt", first["next_offset"])
        assert second["content"].startswith("é🙂tail")
        assert len(second["content"].encode()) <= ASSET_PAGE_BYTES
        clipped = research_page(second, 2)
        assert clipped["content"] == "é🙂" and clipped["next_offset"] == ASSET_PAGE_BYTES + 5
        assert research_page(first, len(first["content"]))["next_offset"] == first["next_offset"]
        tail = ProjectTools.apply(
            db, tid, action(tool="read_asset", path="inputs/text.txt", offset=270001)
        )
        assert "error" not in tail
        assert "error" in read_asset(db, tid, "inputs/text.txt", ASSET_PAGE_BYTES)
        for path in ("/etc/passwd", "../text.txt", "text.txt", "receipts/other.json"):
            assert read_asset(db, tid, path)["error"] == "saved_asset_not_found"
    other = work.create("Other", "Other task", "local", build_target="files")["id"]
    with store.connect() as db:
        assert read_asset(db, other, "inputs/text.txt")["error"] == "saved_asset_not_found"


async def test_receipts_require_same_task_completed_execution_and_cleanup(tmp_path):
    store, work, tid, _ = setup(tmp_path)
    result = await work.builds.execute(tid, 1, action())
    path = result["transcription"]["transcript_path"]
    other = work.create("Other", "Other task", "local", build_target="files")["id"]
    with store.transaction() as db:
        assert read_asset(db, tid, path)["content"]
        db.execute(
            "UPDATE work_executions SET cleanup_pending=1 WHERE id=?", (result["execution_id"],)
        )
        assert read_asset(db, tid, path)["error"] == "saved_asset_not_found"
        db.execute(
            "UPDATE work_executions SET cleanup_pending=0,task_id=? WHERE id=?",
            (other, result["execution_id"]),
        )
        assert read_asset(db, tid, path)["error"] == "saved_asset_not_found"


async def test_registry_dispatch_finishes_artifact_only_task_with_typed_actions(tmp_path):
    store, work, tid, sandbox = setup(tmp_path)
    calls = []

    class Agent:
        async def stream(self, model, messages, response_schema=None):
            calls.append(response_schema)
            if len(calls) == 1:
                assert '{"tool":"transcribe_media","path":' in messages[0]["content"]
                assert '{"tool":"read_asset","path":' in messages[0]["content"]
                assert "/opt/dsgpt/asset_worker.py" not in messages[0]["content"]
                output = action()
                paths = {v["properties"]["tool"]["const"]: v for v in response_schema["oneOf"]}
                assert paths["transcribe_media"]["properties"]["path"]["enum"] == [
                    "inputs/speech.wav"
                ]
            elif len(calls) == 2:
                result = json.loads(store.one("SELECT result FROM work_executions")["result"])
                output = action(tool="read_asset", path=result["transcription"]["transcript_path"])
            else:
                output = ProjectAction(tool="finish", summary="Saved and read both outputs")
            yield {"kind": "delta", "data": {"text": output.model_dump_json()}}

    work.inference = Agent()
    for _ in range(3):
        with store.transaction() as db:
            db.execute("UPDATE work_tasks SET status='queued' WHERE id=?", (tid,))
        await work._step(store.one("SELECT * FROM work_tasks WHERE id=?", (tid,)))
    assert len(sandbox.calls) == 1
    assert store.one("SELECT status FROM work_tasks WHERE id=?", (tid,))["status"] == "completed"
    assert not store.all("SELECT * FROM work_files WHERE task_id=?", (tid,))


async def test_cancelled_transcription_recovers_without_reexecuting_command(tmp_path):
    entered = asyncio.Event()

    class CancelledSandbox(SpeechSandbox):
        async def execute(self, *args, **kwargs):
            entered.set()
            await asyncio.Event().wait()

    store, work, tid, sandbox = setup(tmp_path, sandbox=CancelledSandbox())
    running = asyncio.create_task(work.builds.execute(tid, 1, action()))
    await entered.wait()
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    pending_action, result = work.builds.pending(tid, 1)
    assert pending_action["tool"] == "transcribe_media"
    assert result["error"] == "execution_cancelled" and sandbox.cleaned
    with store.connect() as db:
        assert work_assets.catalog(db, tid)["receipts"] == []


def test_guided_prompt_preserves_requirement_eof_in_recorded_read(tmp_path):
    store, work, tid, _ = setup(tmp_path)
    row = store.one("SELECT * FROM work_tasks WHERE id=?", (tid,))
    with store.transaction() as db:
        work.specs.initialize(db, tid, row["requirements"])
        db.execute("UPDATE work_spec_sections SET notes='Reviewed' WHERE task_id=?", (tid,))
    session = store.one("SELECT * FROM work_sessions WHERE task_id=?", (tid,))
    work._commit(
        tid, session, ProjectAction(tool="read_requirements", requirement_id=1, summary="Read")
    )
    session = store.one("SELECT * FROM work_sessions WHERE task_id=?", (tid,))
    messages = work._guided_prompt(row, session, work.models["local"], [])
    recorded = next(
        json.loads(message["content"].removeprefix("Recorded tool result: "))
        for message in messages
        if message["content"].startswith("Recorded tool result: ")
    )
    assert recorded["content"] == row["requirements"]
    assert recorded["next_offset"] is None and recorded["has_more"] is False


async def test_guided_asset_pages_fit_before_clipping_and_hint_only_displayed_bytes(tmp_path):
    class LongSpeech(SpeechSandbox):
        async def execute(self, *args, **kwargs):
            result = await super().execute(*args, **kwargs)
            report = json.loads(result["artifacts"][0]["content"])
            report["text"] = "é🙂" * 700
            body = json.dumps(report, ensure_ascii=False).encode()
            result["artifacts"][0].update(content=body, sha256=hashlib.sha256(body).hexdigest())
            return result

    store, work, tid, _ = setup(tmp_path, sandbox=LongSpeech())
    row = store.one("SELECT * FROM work_tasks WHERE id=?", (tid,))
    with store.transaction() as db:
        work.specs.initialize(db, tid, row["requirements"])
        db.execute("UPDATE work_spec_sections SET notes='Reviewed' WHERE task_id=?", (tid,))
    result = await work.builds.execute(tid, 1, action())
    metadata = result["transcription"]

    def recorded_read(path):
        with store.transaction() as db:
            db.execute("UPDATE work_tasks SET status='running' WHERE id=?", (tid,))
        session = store.one("SELECT * FROM work_sessions WHERE task_id=?", (tid,))
        work._commit(tid, session, action(tool="read_asset", path=path))
        return store.one("SELECT * FROM work_sessions WHERE task_id=?", (tid,))

    def view(messages):
        return next(
            json.loads(message["content"].removeprefix("Recorded tool result: "))
            for message in messages
            if message["content"].startswith("Recorded tool result: ")
        )

    session = recorded_read(metadata["transcript_path"])
    model = replace(work.models["local"], context=16384, output_tokens=1024)
    messages = work._guided_prompt(row, session, model, [])
    full = view(messages)
    assert len(full["content"].encode()) > 1800 and full["next_offset"] is None
    assert "paged_for_context" not in full
    hint = json.loads(messages[1]["content"])["next_step"]
    assert metadata["subtitles_path"] in hint and "EOF" in hint

    # The metadata-first policy now fits this complete output in the former test budget.
    # A genuinely smaller window must still page the exact output without inventing EOF.
    smaller = replace(model, context=12000)
    clipped_messages = work._guided_prompt(row, session, smaller, [])
    clipped = view(clipped_messages)
    assert clipped["paged_for_context"] and clipped["next_offset"] is not None
    assert clipped["next_offset"] == len(clipped["content"].encode("utf-8"))
    assert full["content"].encode().startswith(clipped["content"].encode())
    hint = json.loads(clipped_messages[1]["content"])["next_step"]
    continuation = json.loads(hint.split("Next JSON action: ", 1)[1])
    assert continuation["path"] == metadata["transcript_path"]
    assert continuation["offset"] == clipped["next_offset"]
    assert ollama_input_estimate(clipped_messages) + smaller.output_tokens <= smaller.context
    # Prompt construction does not alter the complete recorded read or pretend to mark coverage.
    stored = json.loads(
        store.one("SELECT result FROM work_steps WHERE task_id=?", (tid,))["result"]
    )
    assert stored["next_offset"] is None and stored["content"] == full["content"]
    omitted = work._guided_prompt(row, session, replace(model, context=512, output_tokens=128), [])
    omitted_context = json.loads(omitted[1]["content"])
    assert omitted_context["previous_result"]["path"] == metadata["transcript_path"]
    assert "Next JSON action:" not in omitted_context["next_step"]
    assert not any(m["content"].startswith("Recorded tool result: ") for m in omitted)
    session = recorded_read(metadata["subtitles_path"])
    subtitles = work._guided_prompt(row, session, model, [])
    assert view(subtitles)["next_offset"] is None
    hint = json.loads(subtitles[1]["content"])["next_step"]
    assert "mark_requirement" in hint and "checks you actually performed" in hint
    assert metadata["transcript_path"] in hint and metadata["subtitles_path"] in hint
    assert not json.loads(subtitles[1]["content"])["requirements"]["coverage"]["ready"]
    companion = json.loads(subtitles[-1]["content"].split(": ", 1)[1])
    assert companion["content"] == full["content"] and companion["next_offset"] is None
    assert companion["sha256"] == full["sha256"]
    assert ollama_input_estimate(subtitles) + model.output_tokens <= model.context
    limited = work._guided_prompt(row, session, smaller, [])
    assert not any(m["content"].startswith("Previously requested saved output") for m in limited)
    assert "Both complete saved outputs" not in json.loads(limited[1]["content"])["next_step"]
    assert view(limited)["content"] == view(subtitles)["content"]
    assert ollama_input_estimate(limited) + smaller.output_tokens <= smaller.context


async def test_comparison_requires_requested_hashes_and_current_complete_receipts(tmp_path):
    store, work, tid, _ = setup(tmp_path)
    result = await work.builds.execute(tid, 1, action())
    transcript = result["transcription"]["transcript_path"]
    subtitles = result["transcription"]["subtitles_path"]
    args = (tid, result["execution_id"], result["snapshot_sha256"])
    with store.connect() as db:
        full = read_asset(db, tid, subtitles)
        assert related_asset_read(db, *args, full) is None  # Companion was not requested.
    session = store.one("SELECT * FROM work_sessions WHERE task_id=?", (tid,))
    work._commit(tid, session, action(tool="read_asset", path=transcript))
    with store.transaction() as db:
        assert related_asset_read(db, *args, full)["path"] == transcript
        assert related_asset_read(db, *args, {**full, "content": "modified"}) is None
        assert related_asset_read(db, *args, {**full, "offset": 1}) is None
        assert related_asset_read(db, *args, {**full, "next_offset": 1}) is None
        assert related_asset_read(db, tid, result["execution_id"], "0" * 64, full) is None
        db.execute(
            "UPDATE work_artifacts SET sha256=? WHERE task_id=? AND path=?",
            ("f" * 64, tid, transcript.removeprefix("receipts/")),
        )
        assert related_asset_read(db, *args, full) is None
        original_hash = result["artifacts"][0]["sha256"]
        db.execute(
            "UPDATE work_artifacts SET sha256=? WHERE task_id=? AND path=?",
            (original_hash, tid, transcript.removeprefix("receipts/")),
        )
        db.execute(
            "UPDATE work_steps SET result=json_set(result,'$.sha256',?) WHERE task_id=?",
            ("f" * 64, tid),
        )
        assert related_asset_read(db, *args, full) is None
