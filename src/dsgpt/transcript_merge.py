"""Validate and assemble saved speech windows inside the offline asset container.

This module reads data only. It never starts a decoder, model, subprocess or network request.
Coverage describes transcription windows, not recognition accuracy or visual review.
"""

import hashlib
import json
import math
import os
import re
import stat
from pathlib import Path
from uuid import UUID

MAX_WINDOWS = 4096
MAX_MANIFEST_BYTES = 4 * 1024**2
MAX_TOTAL_BYTES = 256 * 1024**2
MAX_REPORT_BYTES = 8 * 1024**2
EPSILON = 0.000001
WORD_EPSILON = 0.001


def _number(value):
    if type(value) not in {int, float} or not math.isfinite(value):
        raise ValueError("transcript_merge_invalid_number")
    return value


def _digest(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("transcript_merge_invalid_hash")
    return value


def _path(root, value, *, argument=False):
    if not isinstance(value, (str, Path)):
        raise ValueError("transcript_merge_invalid_path")
    raw = str(value)
    if "\\" in raw or ":" in raw or any(ord(c) < 32 or ord(c) == 127 for c in raw):
        raise ValueError("transcript_merge_invalid_path")
    path = Path(value)
    if path.is_absolute():
        if not argument:
            raise ValueError("transcript_merge_invalid_path")
        try:
            path = path.relative_to(root)
        except ValueError as exc:
            raise ValueError("transcript_merge_invalid_path") from exc
    parts = path.parts
    if not parts or len(str(path)) > 240:
        raise ValueError("transcript_merge_invalid_path")
    for part in parts:
        if (
            part in {".", "..", ".git"}
            or part.endswith((".", " "))
            or any(char in '<>"|?*' for char in part)
            or re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(?:\..*)?", part)
        ):
            raise ValueError("transcript_merge_invalid_path")
    resolved = root
    for part in parts:
        resolved /= part
        if resolved.is_symlink():
            raise ValueError("transcript_merge_symlink")
    if not resolved.resolve().is_relative_to(root):
        raise ValueError("transcript_merge_invalid_path")
    return resolved


def _read(path, limit):
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError("transcript_merge_input_limit")
        body = stream.read(limit + 1)
        if len(body) > limit:
            raise ValueError("transcript_merge_input_limit")
        return body


def _json(body):
    def reject_constant(_):
        raise ValueError("transcript_merge_invalid_number")

    def unique_object(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("transcript_merge_duplicate_json_key")
            result[key] = value
        return result

    value = json.loads(body, parse_constant=reject_constant, object_pairs_hook=unique_object)
    if not isinstance(value, dict):
        raise ValueError("transcript_merge_invalid_report")
    return value


def _clock(value):
    value = round(value * 1000)
    return (
        f"{value // 3600000:02}:{value // 60000 % 60:02}:{value // 1000 % 60:02},{value % 1000:03}"
    )


def subtitles(segments):
    """Match the speech worker's twelve-word batching and absolute timestamp formatting."""
    captions = []
    for segment in segments:
        for index in range(0, len(segment["words"]), 12):
            batch = segment["words"][index : index + 12]
            captions.append(
                f"{len(captions) + 1}\n{_clock(batch[0]['start'])} --> {_clock(batch[-1]['end'])}\n"
                + " ".join(word["word"] for word in batch)
                + "\n"
            )
    return "\n".join(captions)


def _segments(report, start, end):
    segments = report.get("segments")
    if not isinstance(segments, list):
        raise ValueError("transcript_merge_invalid_segments")
    count, uncertain, previous = 0, 0, start
    for segment in segments:
        if not isinstance(segment, dict) or not isinstance(segment.get("text"), str):
            raise ValueError("transcript_merge_invalid_segment")
        begin, finish = _number(segment.get("start")), _number(segment.get("end"))
        if (
            begin < 0
            or begin < previous - WORD_EPSILON
            or not start - WORD_EPSILON <= begin <= finish <= end + WORD_EPSILON
        ):
            raise ValueError("transcript_merge_invalid_timestamps")
        words = segment.get("words")
        if not isinstance(words, list) or not words:
            raise ValueError("transcript_merge_invalid_words")
        word_previous = begin
        for word in words:
            if (
                not isinstance(word, dict)
                or not isinstance(word.get("word"), str)
                or not word["word"]
                or any(char.isspace() for char in word["word"])
                or any(ord(char) < 32 or ord(char) == 127 for char in word["word"])
            ):
                raise ValueError("transcript_merge_invalid_word")
            first, last = _number(word.get("start")), _number(word.get("end"))
            confidence = _number(word.get("confidence"))
            if (
                first < 0
                or not 0 <= confidence <= 1
                or first < word_previous - WORD_EPSILON
                or not begin - WORD_EPSILON <= first <= last <= finish + WORD_EPSILON
            ):
                raise ValueError("transcript_merge_invalid_timestamps")
            word_previous = last
            count += 1
            uncertain += confidence < 0.6
        if (
            abs(words[0]["start"] - begin) > EPSILON
            or abs(words[-1]["end"] - finish) > EPSILON
            or " ".join(word["word"] for word in words) != segment["text"]
        ):
            raise ValueError("transcript_merge_word_segment_mismatch")
        previous = finish
    if (
        type(report.get("word_count")) is not int
        or report["word_count"] != count
        or type(report.get("uncertain_words")) is not int
        or report["uncertain_words"] != uncertain
        or report.get("text") != " ".join(segment["text"] for segment in segments)
    ):
        raise ValueError("transcript_merge_text_count_mismatch")
    return segments, count, uncertain


def _excluded_provenance(root, manifest, duration, selected_count):
    """Retain only bounded metadata; excluded candidates are never read or merged."""
    excluded = manifest.get("excluded_windows", [])
    if not isinstance(excluded, list) or len(excluded) + selected_count > MAX_WINDOWS:
        raise ValueError("transcript_merge_excluded_window_limit")
    result = []
    for candidate in excluded:
        if not isinstance(candidate, dict):
            raise ValueError("transcript_merge_invalid_excluded_window")
        start, end = _number(candidate.get("start")), _number(candidate.get("end"))
        if not 0 <= start < end <= duration + EPSILON or end - start > 900 + EPSILON:
            raise ValueError("transcript_merge_invalid_excluded_window")
        item = {
            "path": str(_path(root, candidate.get("path")).relative_to(root)),
            "sha256": _digest(candidate.get("sha256")),
            "subtitles_path": str(_path(root, candidate.get("subtitles_path")).relative_to(root)),
            "subtitles_sha256": _digest(candidate.get("subtitles_sha256")),
            "start": start,
            "end": end,
            "included": False,
            "contents_validated": False,
        }
        for key in ("execution_id", "transcript_id", "subtitles_id"):
            if key in candidate:
                value = candidate[key]
                if not isinstance(value, str) or len(value) != 36 or str(UUID(value)) != value:
                    raise ValueError("transcript_merge_invalid_excluded_identifier")
                item[key] = value
        result.append(item)
    return result


def merge(manifest_path: Path, output: Path, root: Path):
    root = Path(root).resolve(strict=True)
    manifest_path = _path(root, manifest_path, argument=True)
    output = _path(root, output, argument=True)
    srt_output = _path(root, output.with_suffix(".srt"), argument=True)
    if output.suffix != ".json" or output.exists() or srt_output.exists():
        raise ValueError("transcript_merge_requires_new_json_and_srt")
    manifest_body = _read(manifest_path, MAX_MANIFEST_BYTES)
    manifest = _json(manifest_body)
    source = _digest(manifest.get("source_sha256"))
    duration = _number(manifest.get("duration"))
    windows = manifest.get("windows")
    if duration <= 0 or not isinstance(windows, list) or not 1 <= len(windows) <= MAX_WINDOWS:
        raise ValueError("transcript_merge_invalid_windows")
    excluded = _excluded_provenance(root, manifest, duration, len(windows))
    used, segments, provenance = set(), [], []
    total_bytes, previous, count, uncertain = len(manifest_body), 0, 0, 0
    engine = None
    for window in windows:
        if not isinstance(window, dict):
            raise ValueError("transcript_merge_invalid_window")
        start, end = _number(window.get("start")), _number(window.get("end"))
        if (
            start < 0
            or abs(start - previous) > EPSILON
            or not start < end <= duration + EPSILON
            or end - start > 900 + EPSILON
        ):
            raise ValueError("transcript_merge_gap_overlap_or_window_limit")
        transcript = _path(root, window.get("path"))
        subtitle = _path(root, window.get("subtitles_path"))
        for path in (transcript, subtitle):
            folded = str(path.relative_to(root)).casefold()
            if folded in used or path in {manifest_path, output, srt_output}:
                raise ValueError("transcript_merge_duplicate_path")
            used.add(folded)
        raw = _read(transcript, min(MAX_REPORT_BYTES, MAX_TOTAL_BYTES - total_bytes))
        total_bytes += len(raw)
        srt = _read(subtitle, min(MAX_REPORT_BYTES, MAX_TOTAL_BYTES - total_bytes))
        total_bytes += len(srt)
        if hashlib.sha256(raw).hexdigest() != _digest(window.get("sha256")) or hashlib.sha256(
            srt
        ).hexdigest() != _digest(window.get("subtitles_sha256")):
            raise ValueError("transcript_merge_hash_changed")
        report = _json(raw)
        if (
            report.get("source_sha256") != source
            or abs(_number(report.get("duration")) - duration) > EPSILON
            or abs(_number(report.get("start")) - start) > EPSILON
            or abs(_number(report.get("end")) - end) > EPSILON
        ):
            raise ValueError("transcript_merge_source_or_window_mismatch")
        following = report.get("next_start")
        if (
            end < duration - EPSILON
            and (following is None or abs(_number(following) - end) > EPSILON)
        ) or (end >= duration - EPSILON and following is not None):
            raise ValueError("transcript_merge_invalid_continuation")
        identity = tuple(report.get(key) for key in ("engine", "model", "language"))
        if any(not isinstance(value, str) or not value for value in identity) or (
            engine is not None and engine != identity
        ):
            raise ValueError("transcript_merge_engine_mismatch")
        engine = identity
        batch, batch_count, batch_uncertain = _segments(report, start, end)
        if srt.decode("utf-8") != subtitles(batch):
            raise ValueError("transcript_merge_subtitles_mismatch")
        segments.extend(batch)
        count += batch_count
        uncertain += batch_uncertain
        provenance.append(
            {
                "path": str(transcript.relative_to(root)),
                "sha256": window["sha256"],
                "subtitles_path": str(subtitle.relative_to(root)),
                "subtitles_sha256": window["subtitles_sha256"],
                "start": start,
                "end": end,
            }
        )
        previous = end
    if abs(previous - duration) > EPSILON:
        raise ValueError("transcript_merge_incomplete_coverage")
    report = {
        "source_sha256": source,
        "engine": engine[0],
        "model": engine[1],
        "language": engine[2],
        "start": 0,
        "end": duration,
        "duration": duration,
        "next_start": None,
        "text": " ".join(segment["text"] for segment in segments),
        "segments": segments,
        "word_count": count,
        "uncertain_words": uncertain,
        "assembled": True,
        "full_audio_coverage": True,
        "window_count": len(provenance),
        "windows": provenance,
        "excluded_window_count": len(excluded),
        "excluded_windows": excluded,
        "excluded_windows_note": "Listed candidates were not included in this assembly. "
        "Only their metadata was checked; their file contents were not read or validated.",
        "note": "All audio time windows were transcribed and their saved JSON/SRT consistency "
        "was checked. Recognition can mishear names, code and noisy speech; coverage is not "
        "proof of recognition accuracy. Timestamps refer to the original media. Video frames "
        "were not reviewed; speakers were not identified.",
    }
    body = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
    subtitle_body = subtitles(segments).encode("utf-8")
    if len(body) + len(subtitle_body) > MAX_TOTAL_BYTES:
        raise ValueError("transcript_merge_output_limit")
    output.parent.mkdir(parents=True, exist_ok=True)
    _path(root, output, argument=True)
    written = []
    try:
        for path, content in ((output, body), (srt_output, subtitle_body)):
            with path.open("xb") as stream:
                written.append(path)
                stream.write(content)
    except OSError:
        for path in written:
            path.unlink(missing_ok=True)
        raise
    return {
        key: report[key]
        for key in (
            "source_sha256",
            "engine",
            "model",
            "language",
            "start",
            "end",
            "duration",
            "next_start",
            "word_count",
            "uncertain_words",
            "assembled",
            "full_audio_coverage",
            "window_count",
            "excluded_window_count",
            "excluded_windows_note",
            "note",
        )
    } | {
        "transcript": str(output.relative_to(root)),
        "subtitles": str(srt_output.relative_to(root)),
        "preview": report["text"][:400],
        "status": "assembled",
    }
