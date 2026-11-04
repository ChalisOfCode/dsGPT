"""Source-bound window coverage and deterministic isolated transcript assembly plans."""

import hashlib
import json
import math

from . import work_assets
from .sandbox import SandboxError
from .storage import canonical

MAX_WINDOWS = 4096
TOLERANCE = 0.000001


def _coverage(db, task_id, path):
    source = work_assets.lookup(db, task_id, path)
    if source is None:
        return {"error": "transcription_saved_asset_required"}, [], []
    assets = work_assets.inventory(db, task_id)
    receipts = {item["path"]: item for item in assets["receipts"]}
    windows, excluded = [], []
    durations = set()
    for row in db.execute(
        "SELECT id,result FROM work_executions WHERE task_id=? AND status='completed' "
        "AND cleanup_pending=0 AND json_extract(action,'$.tool')='transcribe_media' "
        "ORDER BY step DESC,rowid DESC",
        (task_id,),
    ):
        result = json.loads(row["result"] or "{}")
        speech = result.get("transcription") or {}
        if speech.get("source_path") != path or speech.get("source_sha256") != source["sha256"]:
            continue
        expected = {"receipts/" + a["path"]: a for a in result.get("artifacts", [])}
        paths = [speech.get("transcript_path"), speech.get("subtitles_path")]
        if any(
            p not in receipts
            or p not in expected
            or any(receipts[p][key] != expected[p].get(key) for key in ("id", "sha256", "bytes"))
            or receipts[p]["execution_id"] != row["id"]
            for p in paths
        ):
            continue  # Missing, failed, replaced or foreign output cannot supply coverage.
        start, end, duration = [
            speech.get(k) for k in ("start_seconds", "end_seconds", "media_duration_seconds")
        ]
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in (start, end, duration)):
            return {"error": "transcript_window_metadata_invalid"}, [], []
        if not 0 <= start < end <= duration or end - start > 900 + TOLERANCE:
            return {"error": "transcript_window_metadata_invalid"}, [], []
        next_start = speech.get("next_start")
        if (
            end < duration - TOLERANCE
            and (
                type(next_start) not in (int, float)
                or not math.isfinite(next_start)
                or abs(next_start - end) > TOLERANCE
            )
        ) or (end >= duration - TOLERANCE and next_start is not None):
            return {"error": "transcript_window_metadata_invalid"}, [], []
        durations.add(float(duration))
        windows.append(
            {
                "path": paths[0],
                "sha256": receipts[paths[0]]["sha256"],
                "subtitles_path": paths[1],
                "subtitles_sha256": receipts[paths[1]]["sha256"],
                "start": float(start),
                "end": float(end),
                "execution_id": row["id"],
                "transcript_id": receipts[paths[0]]["id"],
                "subtitles_id": receipts[paths[1]]["id"],
            }
        )
        if len(windows) > MAX_WINDOWS:
            return {"error": "transcript_window_count_limit"}, [], []
    if durations and max(durations) - min(durations) > TOLERANCE:
        return {"error": "transcript_media_duration_mismatch"}, [], []
    duration = max(durations) if durations else None
    # Positive-length windows form an acyclic graph. Retain the newest valid route to each
    # reachable end, then select the route reaching the full duration or farthest safe prefix.
    reachable = {0.0: []}
    for window in sorted(windows, key=lambda item: (item["start"], item["end"])):
        beginning = next(
            (end for end in reachable if abs(end - window["start"]) <= TOLERANCE), None
        )
        if beginning is not None and window["end"] not in reachable:
            reachable[window["end"]] = [*reachable[beginning], window]
    covered = max(reachable)
    selected = reachable[covered]
    chosen = {item["execution_id"] for item in selected}
    excluded = [item for item in windows if item["execution_id"] not in chosen]
    ready = duration is not None and abs(covered - duration) <= TOLERANCE
    state = {
        "source_path": path,
        "source_sha256": source["sha256"],
        "media_duration_seconds": duration,
        "covered_until_seconds": covered,
        "next_start": None if ready else covered,
        "assembly_ready": ready,
        "selected_window_count": len(selected),
        "available_window_count": len(windows),
        "excluded_window_count": len(excluded),
        "coverage_sha256": hashlib.sha256(
            canonical(
                {
                    "source_sha256": source["sha256"],
                    "selected": selected,
                    "excluded": excluded,
                }
            ).encode()
        ).hexdigest(),
        "coverage": "Audio windows only; recognition accuracy and video frames remain unverified.",
    }
    return state, selected, excluded


def coverage_state(db, task_id, path):
    return _coverage(db, task_id, path)[0]


def assembly_plan(db, task_id, path):
    state, windows, excluded = _coverage(db, task_id, path)
    if state.get("error"):
        raise SandboxError(state["error"])
    if not state["assembly_ready"]:
        raise SandboxError("transcript_audio_coverage_incomplete")
    manifest = {
        "source_sha256": state["source_sha256"],
        "duration": state["media_duration_seconds"],
        "windows": windows,
        "excluded_windows": excluded,
    }
    content = canonical(manifest)
    digest = hashlib.sha256(content.encode()).hexdigest()
    name = "media/complete-" + digest[:24]
    manifest_path = ".dsgpt-media/assembly-" + digest[:24] + ".json"
    return {
        "argv": [
            "/usr/bin/python3",
            "-I",
            "/opt/dsgpt/asset_worker.py",
            "audio-merge",
            manifest_path,
            name + ".json",
        ],
        "artifacts": [name + ".json", name + ".srt"],
        "timeout_seconds": 300,
        "paths": [p for window in windows for p in (window["path"], window["subtitles_path"])],
        "manifest": {"path": manifest_path, "content": content, "sha256": digest},
        "source_sha256": state["source_sha256"],
        "state": state,
    }


def assembly_result(plan, artifacts):
    by_path = {artifact["path"]: artifact for artifact in artifacts}
    transcript, subtitles = plan["artifacts"]
    if transcript not in by_path or subtitles not in by_path:
        raise SandboxError("transcription_outputs_missing")
    report = json.loads(by_path[transcript]["content"])
    state = plan["state"]
    if (
        report.get("assembled") is not True
        or report.get("full_audio_coverage") is not True
        or report.get("source_sha256") != plan["source_sha256"]
        or report.get("window_count") != state["selected_window_count"]
        or report.get("start") != 0
        or report.get("end") != state["media_duration_seconds"]
        or report.get("duration") != state["media_duration_seconds"]
        or report.get("next_start") is not None
        or not isinstance(report.get("text"), str)
        or type(report.get("word_count")) is not int
        or report["word_count"] < 0
    ):
        raise SandboxError("assembled_transcript_report_invalid")
    preview = report["text"].encode("utf-8")[:600].decode("utf-8", errors="ignore")
    return {
        **state,
        "assembled": True,
        "full_audio_coverage": True,
        "transcript_path": "receipts/" + transcript,
        "subtitles_path": "receipts/" + subtitles,
        "start_seconds": 0,
        "end_seconds": state["media_duration_seconds"],
        "window_count": state["selected_window_count"],
        "word_count": report["word_count"],
        "uncertain_words": report.get("uncertain_words"),
        "preview": preview,
        "preview_complete": preview == report["text"],
        "total_text_characters": len(report["text"]),
        "verification": {
            "performed_by": "offline_transcript_merge",
            "json_srt_consistent": True,
            "window_hashes_verified": True,
            "contiguous_audio_coverage_verified": True,
            "absolute_timestamps_preserved": True,
            "validated_window_count": state["selected_window_count"],
            "recognition_accuracy_verified": False,
            "video_frames_reviewed": False,
        },
        "read": "Read and compare both assembled outputs; recognition accuracy remains unverified.",
    }


def explicit_whole_recording(requirements):
    """Recognize explicit positive whole-media requests, not model-generated reviews.

    Ambiguous/negated requests retain the existing scope-review path.
    """
    import re

    for sentence in re.split(r"[.!?\n]", requirements.lower()):
        if re.search(r"\b(?:not|never|don't|instead|only|excerpt)\b", sentence):
            continue
        if re.search(r"\b(?:transcrib\w*|caption\w*|subtitl\w*)\b", sentence) and re.search(
            r"\b(?:whole|entire|full|complete)\s+(?:recording|audio|video)\b", sentence
        ):
            return True
    return False


def whole_recording_blockers(db, task_id):
    """Do not let a generated coverage review waive an explicit whole-media request."""
    row = db.execute("SELECT requirements FROM work_tasks WHERE id=?", (task_id,)).fetchone()
    if not row or not explicit_whole_recording(row["requirements"]):
        return []
    paths = set()
    for execution in db.execute(
        "SELECT result FROM work_executions WHERE task_id=? "
        "AND json_extract(action,'$.tool')='transcribe_media'",
        (task_id,),
    ):
        speech = json.loads(execution["result"] or "{}").get("transcription") or {}
        if speech.get("source_path"):
            paths.add(speech["source_path"])
    blockers = []
    for path in sorted(paths):
        state = coverage_state(db, task_id, path)
        if state.get("assembly_ready") and state["selected_window_count"] > 1:
            receipts = {
                item["path"]: item for item in work_assets.inventory(db, task_id)["receipts"]
            }
            assembled = False
            for execution in db.execute(
                "SELECT id,result FROM work_executions WHERE task_id=? AND status='completed' "
                "AND cleanup_pending=0 AND json_extract(action,'$.tool')='assemble_transcript'",
                (task_id,),
            ):
                result = json.loads(execution["result"] or "{}")
                speech = result.get("transcription") or {}
                if (
                    speech.get("source_path") != path
                    or speech.get("coverage_sha256") != state["coverage_sha256"]
                    or speech.get("source_sha256") != state["source_sha256"]
                    or speech.get("full_audio_coverage") is not True
                ):
                    continue
                expected = {
                    "receipts/" + item["path"]: item for item in result.get("artifacts", [])
                }
                pair = [speech.get("transcript_path"), speech.get("subtitles_path")]
                if all(
                    name in receipts
                    and name in expected
                    and receipts[name]["execution_id"] == execution["id"]
                    and all(
                        receipts[name][key] == expected[name].get(key)
                        for key in ("id", "sha256", "bytes")
                    )
                    for name in pair
                ):
                    assembled = True
                    break
            if not assembled:
                blockers.append(
                    {
                        **state,
                        "error": "whole_recording_assembly_required",
                        "hint": "Call assemble_transcript, then review its complete output pair.",
                    }
                )
        if not state.get("assembly_ready"):
            blockers.append(
                {
                    **state,
                    "error": "whole_recording_coverage_incomplete",
                    "hint": "Transcribe the next missing window before marking coverage. "
                    "A partial transcript cannot satisfy the original whole-recording request.",
                }
            )
    return blockers
