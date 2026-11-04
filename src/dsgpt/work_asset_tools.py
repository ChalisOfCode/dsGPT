"""Typed offline media operations and bounded reads of task-owned saved assets."""

import codecs
import hashlib
import json
import math

from . import work_assets
from .sandbox import SandboxError
from .storage import canonical

ASSET_PAGE_BYTES = 6000


def related_asset_read(db, task_id, execution_id, source_digest, view):
    """Recover one already-requested complete companion from the current saved pair."""
    if (
        view.get("offset") != 0
        or view.get("next_offset") is not None
        or not isinstance(view.get("content"), str)
        or view.get("offset_unit") != "bytes"
    ):
        return None
    execution = db.execute(
        "SELECT result FROM work_executions WHERE task_id=? AND id=? "
        "AND snapshot_sha256=? AND status='completed' AND cleanup_pending=0",
        (task_id, execution_id, source_digest),
    ).fetchone()
    if not execution:
        return None
    result = json.loads(execution["result"] or "{}")
    speech = result.get("transcription") or {}
    paths = [speech.get("transcript_path"), speech.get("subtitles_path")]
    if view.get("path") not in paths or any(not path for path in paths):
        return None
    expected = {"receipts/" + item["path"]: item for item in result.get("artifacts", [])}
    assets = work_assets.inventory(db, task_id)
    current = {item["path"]: item for item in assets["inputs"] + assets["receipts"]}
    if current.get(speech.get("source_path"), {}).get("sha256") != speech.get("source_sha256"):
        return None
    for path in paths:
        saved, collected = current.get(path), expected.get(path)
        if (
            not saved
            or not collected
            or saved["bytes"] > ASSET_PAGE_BYTES
            or any(saved[key] != collected.get(key) for key in ("id", "sha256", "bytes"))
        ):
            return None
    body = view["content"].encode("utf-8")
    same = current[view["path"]]
    if len(body) != same["bytes"] or hashlib.sha256(body).hexdigest() != same["sha256"]:
        return None
    peer_path = next(path for path in paths if path != view["path"])
    peer = current[peer_path]
    requested = db.execute(
        "SELECT 1 FROM work_steps WHERE task_id=? AND json_extract(action,'$.tool')='read_asset' "
        "AND json_extract(result,'$.path')=? AND json_extract(result,'$.sha256')=? "
        "AND json_extract(result,'$.error') IS NULL LIMIT 1",
        (task_id, peer_path, peer["sha256"]),
    ).fetchone()
    if not requested:
        return None
    page = read_asset(db, task_id, peer_path)
    if "content" not in page or page.get("next_offset") is not None:
        return None
    content = page["content"].encode("utf-8")
    if len(content) != peer["bytes"] or hashlib.sha256(content).hexdigest() != peer["sha256"]:
        return None
    return page


def _whole_recording_hint(transcription, whole_recording=None, coverage=None):
    if whole_recording is False or transcription.get("assembled"):
        return None
    if coverage and coverage.get("error"):
        return (
            "Whole-recording coverage is unavailable: "
            + coverage["error"]
            + ". Investigate it before finishing."
        )
    if (
        transcription.get("start_seconds") == 0
        and transcription.get("end_seconds") == transcription.get("media_duration_seconds")
        and transcription.get("next_start") is None
        and transcription.get("end_seconds") is not None
    ):
        return None  # One full window already supplies the complete output pair.
    following = coverage.get("next_start") if coverage else transcription.get("next_start")
    if following is not None:
        return "The whole recording is not covered yet. Next JSON action: " + canonical(
            {
                "tool": "transcribe_media",
                "path": transcription["source_path"],
                "start_seconds": following,
                "summary": "Transcribe next missing audio window",
            }
        )
    return "The whole recording needs one assembled output pair. Next JSON action: " + canonical(
        {
            "tool": "assemble_transcript",
            "path": transcription["source_path"],
            "summary": "Assemble complete transcript and subtitles",
        }
    )


def asset_comparison_hint(transcription, requirement_id, whole_recording=None, coverage=None):
    continuation = _whole_recording_hint(transcription, whole_recording, coverage)
    if continuation and whole_recording is True:
        return continuation
    paths = [transcription["transcript_path"], transcription["subtitles_path"]]
    return (
        "If the user requested the whole recording: " + continuation + " "
        "For an explicitly requested excerpt, review only that requested scope instead. "
        if continuation
        else ""
    ) + (
        "Both complete saved outputs are displayed together. Compare their text and timestamps "
        "now; no repeated read is needed for this comparison. If this requirement is satisfied, "
        "return a mark_requirement action with requirement_id="
        + str(requirement_id)
        + ", evidence_paths="
        + canonical(paths)
        + ", content explaining the checks you actually "
        "performed and any uncertainty, and summary describing your progress. Investigate any "
        "discrepancy before marking it. File consistency does not prove recognition accuracy, "
        "full-media coverage, or other requirements."
    )


def asset_read_hint(view, transcription, requirement_id, whole_recording=None, coverage=None):
    """Guide the next choice from the page actually included in the model prompt."""
    if view.get("offset_unit") != "bytes" or "content" not in view:
        return None
    path, following = view["path"], view.get("next_offset")
    if following is not None:
        return (
            "The displayed asset page is partial. Continue at its next_offset. Next JSON action: "
            + canonical(
                {
                    "tool": "read_asset",
                    "path": path,
                    "offset": following,
                    "summary": "Read next output page",
                }
            )
        )
    if not transcription:
        return None
    transcript, subtitles = transcription["transcript_path"], transcription["subtitles_path"]
    if path == transcript:
        return (
            "The displayed page reaches the JSON transcript EOF. Check the matching SRT next. "
            "Next JSON action: "
            + canonical(
                {
                    "tool": "read_asset",
                    "path": subtitles,
                    "offset": 0,
                    "summary": "Check saved subtitles",
                }
            )
        )
    if path == subtitles:
        continuation = _whole_recording_hint(transcription, whole_recording, coverage)
        if continuation and whole_recording is True:
            return continuation
        return (
            "If the user requested the whole recording: " + continuation + " "
            "For an explicitly requested excerpt, review only that requested scope instead. "
            if continuation
            else ""
        ) + (
            "The displayed page reaches subtitle EOF. Review requirement "
            + str(requirement_id)
            + " against the saved outputs and any earlier pages still needed. When checked, use "
            "mark_requirement with this requirement_id, a factual content explanation of your "
            "checks, and evidence_paths=" + canonical([transcript, subtitles]) + ". "
            "Reaching EOF alone does not validate earlier pages or other requirements."
        )
    return None


def transcription_plan(action, assets):
    """Expand a saved asset/window into a fixed command inside the existing sandbox."""
    source = next((item for item in assets if item["path"] == action.path), None)
    if not source or not action.path.startswith(("inputs/", "receipts/")):
        raise SandboxError("transcription_saved_asset_required")
    window = [action.path, source["sha256"], action.start_seconds, action.duration_seconds]
    name = "media/transcript-" + hashlib.sha256(canonical(window).encode()).hexdigest()[:24]
    return {
        "argv": [
            "/usr/bin/python3",
            "-I",
            "/opt/dsgpt/asset_worker.py",
            "audio-transcribe",
            action.path,
            name + ".json",
            "--start",
            str(action.start_seconds),
            "--duration",
            str(action.duration_seconds),
        ],
        "artifacts": [name + ".json", name + ".srt"],
        "timeout_seconds": 900,
        "source_sha256": source["sha256"],
    }


def transcription_result(action, plan, artifacts):
    """A completed transcription must retain both outputs, including silent-audio SRTs."""
    by_path = {item["path"]: item for item in artifacts}
    transcript, subtitles = plan["artifacts"]
    if transcript not in by_path or subtitles not in by_path:
        raise SandboxError("transcription_outputs_missing")
    body = by_path[transcript]["content"]
    if len(body) > 8 * 1024**2:
        raise SandboxError("transcription_report_invalid")
    try:
        report = json.loads(body)
        numbers = [report[key] for key in ("start", "end", "duration")]
        if (
            any(type(value) not in {int, float} or not math.isfinite(value) for value in numbers)
            or report["source_sha256"] != plan["source_sha256"]
            or report["start"] != action.start_seconds
            or not report["start"] < report["end"] <= report["duration"]
            or report["end"] > action.start_seconds + action.duration_seconds + 0.000001
            or not isinstance(report["text"], str)
            or type(report["word_count"]) is not int
            or report["word_count"] < 0
        ):
            raise ValueError
        following = report["next_start"]
        if following is not None and (
            type(following) not in {int, float}
            or not math.isfinite(following)
            or abs(following - report["end"]) > 0.000001
            or following >= report["duration"]
        ):
            raise ValueError
        by_path[subtitles]["content"].decode("utf-8")
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise SandboxError("transcription_report_invalid") from exc
    return {
        "source_path": action.path,
        "source_sha256": plan["source_sha256"],
        "transcript_path": "receipts/" + transcript,
        "subtitles_path": "receipts/" + subtitles,
        "start_seconds": report["start"],
        "end_seconds": report["end"],
        "media_duration_seconds": report["duration"],
        "next_start": following,
        "word_count": report["word_count"],
        "status": "transcribed" if report["word_count"] else "no_speech_detected",
        "preview": report["text"][:400],
        "read": "Use read_asset with transcript_path or subtitles_path; follow next_offset.",
        "coverage": "Only this audio window was transcribed; video frames were not inspected.",
    }


def read_asset(db, task_id, path, offset=0):
    """Read at most 6000 UTF-8 bytes from a catalogued task blob, never the host filesystem."""
    if not db.execute("SELECT 1 FROM work_build_profiles WHERE task_id=?", (task_id,)).fetchone():
        return {"error": "asset_tool_requires_isolated_work"}
    if type(offset) is not int or not 0 <= offset <= 768 * 1024**2:
        return {"error": "asset_offset_out_of_range"}
    item = work_assets.lookup(db, task_id, path)
    if not item:
        return {"error": "saved_asset_not_found", "help": "Use an exact path in assets."}
    if "id" in item:
        row = db.execute(
            "SELECT substr(content,?,?) FROM work_artifacts WHERE task_id=? AND id=?",
            (offset + 1, ASSET_PAGE_BYTES, task_id, item["id"]),
        ).fetchone()
    else:
        row = db.execute(
            "SELECT substr(original,?,?) FROM work_inputs WHERE task_id=? AND name=?",
            (offset + 1, ASSET_PAGE_BYTES, task_id, item["name"]),
        ).fetchone()
    raw = row[0] or b""  # SQLite substr may return NULL for a zero-byte BLOB (silent-audio SRT).
    try:
        if any(byte < 32 and byte not in {9, 10, 13} for byte in raw):
            raise ValueError
        text = codecs.getincrementaldecoder("utf-8")().decode(
            raw, final=offset + len(raw) >= item["bytes"]
        )
    except (UnicodeError, ValueError):
        return {
            "error": "asset_is_not_utf8_text_or_offset_splits_character",
            "help": "Text only. For audio/video, call transcribe_media with the same path; "
            "read its transcript_path/subtitles_path. For text, use returned next_offset. "
            "Other binaries: work-assets-guide.txt.",
        }
    following = offset + len(text.encode("utf-8"))
    return {
        "path": path,
        "sha256": item["sha256"],
        "content": text,
        "offset": offset,
        "offset_unit": "bytes",
        "next_offset": following if following < item["bytes"] else None,
        "total_bytes": item["bytes"],
    }


def list_assets(db, task_id, offset=0, query=None):
    if not db.execute("SELECT 1 FROM work_build_profiles WHERE task_id=?", (task_id,)).fetchone():
        return {"error": "asset_tool_requires_isolated_work"}
    try:
        return work_assets.catalog(db, task_id, offset, query)
    except ValueError as exc:
        return {"error": str(exc)}
