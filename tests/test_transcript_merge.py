"""Offline data fixtures verify assembly integrity, not speech-recognition quality."""

import copy
import hashlib
import json
from uuid import uuid4

import pytest

from dsgpt import transcript_merge


def digest(body):
    return hashlib.sha256(body).hexdigest()


def fixture(root, duration=908.308, ends=(300, 600, 900, 908.308), silent=()):
    root.mkdir(exist_ok=True)
    (root / "receipts").mkdir(exist_ok=True)
    manifest = {"source_sha256": "a" * 64, "duration": duration, "windows": []}
    previous = 0
    for index, end in enumerate(ends):
        words = (
            []
            if index in silent
            else [
                {
                    "word": "one",
                    "start": previous + 0.81,
                    "end": previous + 1.11,
                    "confidence": 1.0,
                },
                {
                    "word": "zero",
                    "start": previous + 1.14,
                    "end": previous + 1.53,
                    "confidence": 0.55,
                },
            ]
        )
        segments = (
            []
            if not words
            else [
                {
                    "start": words[0]["start"],
                    "end": words[-1]["end"],
                    "text": "one zero",
                    "words": words,
                }
            ]
        )
        report = {
            "source_sha256": manifest["source_sha256"],
            "engine": "vosk-0.3.45",
            "model": "vosk-model-en-us-0.22-lgraph",
            "language": "en-US",
            "start": previous,
            "end": end,
            "duration": duration,
            "next_start": end if end < duration else None,
            "text": "one zero" if words else "",
            "segments": segments,
            "word_count": len(words),
            "uncertain_words": 1 if words else 0,
        }
        data = json.dumps(report, ensure_ascii=False).encode()
        captions = transcript_merge.subtitles(segments).encode()
        path, srt_path = f"receipts/window-{index}.json", f"receipts/window-{index}.srt"
        (root / path).write_bytes(data)
        (root / srt_path).write_bytes(captions)
        manifest["windows"].append(
            {
                "path": path,
                "sha256": digest(data),
                "subtitles_path": srt_path,
                "subtitles_sha256": digest(captions),
                "start": previous,
                "end": end,
            }
        )
        previous = end
    save(root, manifest)
    return manifest


def save(root, manifest):
    (root / "manifest.json").write_text(json.dumps(manifest))


def edit_report(root, manifest, index, edit):
    window = manifest["windows"][index]
    path = root / window["path"]
    report = json.loads(path.read_bytes())
    edit(report)
    data = json.dumps(report).encode()
    path.write_bytes(data)
    window["sha256"] = digest(data)
    save(root, manifest)


def run(root):
    return transcript_merge.merge(root / "manifest.json", root / "merged/output.json", root)


def test_four_windows_merge_original_timestamps_text_and_numbered_subtitles(tmp_path):
    manifest = fixture(tmp_path)
    result = run(tmp_path)
    output = json.loads((tmp_path / "merged/output.json").read_bytes())
    captions = (tmp_path / "merged/output.srt").read_text()
    assert result["assembled"] and result["full_audio_coverage"]
    assert result["window_count"] == 4 and result["next_start"] is None
    assert output["source_sha256"] == manifest["source_sha256"]
    assert (output["start"], output["end"], output["duration"]) == (0, 908.308, 908.308)
    assert [segment["start"] for segment in output["segments"]] == [0.81, 300.81, 600.81, 900.81]
    assert output["text"] == "one zero one zero one zero one zero"
    assert output["word_count"] == 8 and output["uncertain_words"] == 4
    assert output["windows"] == manifest["windows"]
    assert "4\n00:15:00,810 --> 00:15:01,530\none zero\n" in captions
    assert "not proof of recognition accuracy" in result["note"]
    assert (tmp_path / "receipts/window-0.json").read_bytes()


@pytest.mark.parametrize("silent", [(1, 3), (0, 1, 2, 3)])
def test_empty_windows_including_final_silence_are_valid_coverage(tmp_path, silent):
    fixture(tmp_path, silent=silent)
    result = run(tmp_path)
    output = json.loads((tmp_path / "merged/output.json").read_bytes())
    assert result["window_count"] == 4 and result["full_audio_coverage"]
    assert output["word_count"] == (4 - len(silent)) * 2
    assert len(output["segments"]) == 4 - len(silent)
    if len(silent) == 4:
        assert (tmp_path / "merged/output.srt").read_bytes() == b""


def test_more_than_sixteen_receipts_can_be_assembled(tmp_path):
    fixture(tmp_path, duration=2700, ends=tuple(range(150, 2701, 150)))
    result = run(tmp_path)
    assert result["window_count"] == 18 and result["end"] == 2700
    assert result["word_count"] == 36


@pytest.mark.parametrize(
    "change",
    [
        "gap",
        "overlap",
        "missing_final",
        "duplicate",
        "reverse",
        "mixed_source",
        "duration",
        "start",
        "end",
        "next_start",
        "engine",
        "count",
        "uncertain",
        "text",
        "word_text",
        "timestamp",
        "negative_timestamp",
        "nonfinite",
        "subtitles",
        "hash",
        "missing",
    ],
)
def test_bad_windows_cannot_claim_coverage_or_leave_outputs(tmp_path, change):
    manifest = fixture(tmp_path)
    if change == "gap":
        manifest["windows"][1]["start"] += 0.1
    elif change == "overlap":
        manifest["windows"][1]["start"] -= 0.1
    elif change == "missing_final":
        manifest["windows"].pop()
    elif change == "duplicate":
        manifest["windows"].insert(1, copy.deepcopy(manifest["windows"][0]))
    elif change == "reverse":
        manifest["windows"].reverse()
    elif change == "hash":
        manifest["windows"][0]["sha256"] = "f" * 64
    elif change == "missing":
        (tmp_path / manifest["windows"][0]["path"]).unlink()
    elif change == "subtitles":
        body = b"1\n00:00:00,000 --> 00:00:02,000\nwrong words\n"
        (tmp_path / manifest["windows"][0]["subtitles_path"]).write_bytes(body)
        manifest["windows"][0]["subtitles_sha256"] = digest(body)
    else:

        def corrupt(report):
            edits = {
                "mixed_source": ("source_sha256", "b" * 64),
                "duration": ("duration", 909),
                "start": ("start", 1),
                "end": ("end", 299),
                "next_start": ("next_start", None),
                "engine": ("engine", "other-engine"),
                "count": ("word_count", 99),
                "uncertain": ("uncertain_words", 99),
                "text": ("text", "wrong"),
                "nonfinite": ("duration", float("nan")),
            }
            if change == "word_text":
                report["segments"][0]["words"][0]["word"] = "different"
            elif change == "timestamp":
                report["segments"][0]["words"][0]["end"] = 400
            elif change == "negative_timestamp":
                report["segments"][0]["start"] = -0.0005
                report["segments"][0]["words"][0]["start"] = -0.0005
            else:
                key, value = edits[change]
                report[key] = value

        edit_report(tmp_path, manifest, 1 if change == "engine" else 0, corrupt)
    save(tmp_path, manifest)
    with pytest.raises((ValueError, OSError)):
        run(tmp_path)
    assert not (tmp_path / "merged/output.json").exists()
    assert not (tmp_path / "merged/output.srt").exists()


@pytest.mark.parametrize(
    "path",
    [
        "../outside.json",
        "/etc/passwd",
        "receipts/../window.json",
        "receipts\\window.json",
        "C:/window.json",
        "receipts/NUL.json",
    ],
)
def test_manifest_paths_cannot_escape_or_use_host_aliases(tmp_path, path):
    manifest = fixture(tmp_path)
    manifest["windows"][0]["path"] = path
    save(tmp_path, manifest)
    with pytest.raises(ValueError, match="invalid_path"):
        run(tmp_path)


def test_symlink_inputs_and_output_parents_are_rejected(tmp_path):
    manifest = fixture(tmp_path)
    original = tmp_path / manifest["windows"][0]["path"]
    real = tmp_path / "real.json"
    original.rename(real)
    original.symlink_to(real)
    with pytest.raises(ValueError, match="symlink"):
        run(tmp_path)
    original.unlink()
    real.rename(original)
    target = tmp_path / "actual"
    target.mkdir()
    (tmp_path / "merged").symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        run(tmp_path)
    assert not list(target.iterdir())


def test_input_window_and_output_caps_fail_before_writes(tmp_path, monkeypatch):
    fixture(tmp_path)
    monkeypatch.setattr(transcript_merge, "MAX_WINDOWS", 3)
    with pytest.raises(ValueError, match="invalid_windows"):
        run(tmp_path)
    monkeypatch.setattr(transcript_merge, "MAX_WINDOWS", 4096)
    input_size = sum(path.stat().st_size for path in tmp_path.rglob("*") if path.is_file())
    monkeypatch.setattr(transcript_merge, "MAX_TOTAL_BYTES", input_size - 1)
    with pytest.raises(ValueError, match="input_limit"):
        run(tmp_path)
    monkeypatch.setattr(transcript_merge, "MAX_TOTAL_BYTES", input_size + 1)
    with pytest.raises(ValueError, match="output_limit"):
        run(tmp_path)
    assert not (tmp_path / "merged/output.json").exists()


def test_existing_output_and_duplicate_json_keys_are_not_replaced(tmp_path):
    fixture(tmp_path)
    (tmp_path / "merged").mkdir()
    original = tmp_path / "merged/output.srt"
    original.write_text("Keep this")
    with pytest.raises(ValueError, match="requires_new"):
        run(tmp_path)
    assert original.read_text() == "Keep this"
    original.unlink()
    (tmp_path / "manifest.json").write_text('{"duration":1,"duration":2}')
    with pytest.raises(ValueError, match="duplicate_json_key"):
        run(tmp_path)


def test_subtitle_renderer_batches_twelve_words_with_global_numbering():
    words = [
        {"word": str(index), "start": index, "end": index + 0.5, "confidence": 1}
        for index in range(13)
    ]
    text = transcript_merge.subtitles([{"words": words}, {"words": words[:1]}])
    assert "1\n00:00:00,000 --> 00:00:11,500" in text
    assert "2\n00:00:12,000 --> 00:00:12,500\n12\n" in text
    assert "3\n00:00:00,000 --> 00:00:00,500\n0\n" in text


def excluded_candidate():
    return {
        "path": "receipts/not-loaded.json",
        "sha256": "b" * 64,
        "subtitles_path": "receipts/not-loaded.srt",
        "subtitles_sha256": "c" * 64,
        "start": 150,
        "end": 450,
        "execution_id": str(uuid4()),
        "transcript_id": str(uuid4()),
        "subtitles_id": str(uuid4()),
        "untrusted_extra": "This field must not be copied to the report",
    }


def test_excluded_overlap_metadata_is_reported_without_reading_or_claiming_validation(tmp_path):
    manifest = fixture(tmp_path)
    candidate = excluded_candidate()
    manifest["excluded_windows"] = [candidate]
    save(tmp_path, manifest)
    result = run(tmp_path)
    output = json.loads((tmp_path / "merged/output.json").read_bytes())
    assert result["excluded_window_count"] == 1
    assert output["excluded_window_count"] == 1 and output["window_count"] == 4
    exclusion = output["excluded_windows"][0]
    assert exclusion["start"] == 150 and exclusion["end"] == 450
    assert exclusion["execution_id"] == candidate["execution_id"]
    assert exclusion["sha256"] == candidate["sha256"]
    assert exclusion["included"] is False and exclusion["contents_validated"] is False
    assert "untrusted_extra" not in exclusion
    assert "not read or validated" in result["excluded_windows_note"]
    assert not (tmp_path / candidate["path"]).exists()
    assert output["word_count"] == 8 and len(output["segments"]) == 4


@pytest.mark.parametrize(
    "change", ["too_many", "bad_path", "bad_hash", "bad_id", "nonfinite", "bad_type"]
)
def test_excluded_provenance_is_bounded_and_sanitized(tmp_path, monkeypatch, change):
    manifest = fixture(tmp_path)
    candidate = excluded_candidate()
    manifest["excluded_windows"] = [candidate]
    if change == "too_many":
        monkeypatch.setattr(transcript_merge, "MAX_WINDOWS", 4)
    elif change == "bad_path":
        candidate["path"] = "../outside.json"
    elif change == "bad_hash":
        candidate["sha256"] = "not a hash"
    elif change == "bad_id":
        candidate["execution_id"] = "x" * 36
    elif change == "nonfinite":
        candidate["end"] = float("nan")
    else:
        manifest["excluded_windows"] = "not a list"
    save(tmp_path, manifest)
    with pytest.raises(ValueError):
        run(tmp_path)
    assert not (tmp_path / "merged/output.json").exists()
