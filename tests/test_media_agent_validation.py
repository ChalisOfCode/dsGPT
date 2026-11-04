"""The live acceptance oracle must not mistake partial delivery for completion."""

import importlib.util
import io
import json
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    "live_media_agent", Path(__file__).resolve().parents[1] / "scripts/live_media_agent.py"
)
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)


@pytest.mark.parametrize(
    "fault",
    [None, "unpassed", "different_weights", "different_quant", "different_source", "changed_file"],
)
def test_native_copy_requires_passing_identity_audit(tmp_path, fault):
    native = tmp_path / "native.gguf"
    native.write_bytes(b"bounded fixture weights")
    audit_path = tmp_path / "audit.json"
    audit = {
        "passed": fault != "unpassed",
        "active_weights_preserved": fault != "different_weights",
        "quantization_preserved": fault != "different_quant",
        "source_gguf_sha256": "b" * 64 if fault == "different_source" else "a" * 64,
        "converted_gguf_sha256": acceptance.sha(native.read_bytes()),
        "original_model_tag": "original-9b",
    }
    audit_path.write_text(json.dumps(audit))
    args = SimpleNamespace(
        native_model=native,
        conversion_audit=audit_path,
        original_gguf_sha256="a" * 64,
        original_model_tag="original-9b",
    )
    if fault == "changed_file":
        native.write_bytes(b"different weights")
    if fault is None:
        assert acceptance.native_model_provenance(args)["sha256"] == audit["converted_gguf_sha256"]
    else:
        with pytest.raises(ValueError, match="conversion audit"):
            acceptance.native_model_provenance(args)


async def test_stream_progress_counts_bytes_without_changing_or_logging_model_content(
    monkeypatch, capsys
):
    events = [
        {"kind": "context", "data": {"input_tokens": 10}},
        {"kind": "delta", "data": {"text": "private café"}},
    ]

    async def stream(self, model, messages, response_schema=None):
        for event in events:
            yield event

    ticks = iter([0, 10, 40, 45])
    monkeypatch.setattr(acceptance.LocalInference, "stream", stream)
    monkeypatch.setattr(acceptance, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    inference = acceptance.AcceptanceInference(4, case="short")
    actual = [event async for event in inference.stream(None, [])]
    assert all(left is right for left, right in zip(actual, events, strict=True))
    logs = capsys.readouterr().out
    assert "private" not in logs
    progress = [json.loads(line) for line in logs.splitlines()]
    assert progress[0]["visible_output_bytes"] == len("private café".encode())
    assert progress[-1]["inference_finished"] is True


def sample_pair(offsets):
    fixture = {
        "sha256": "a" * 64,
        "duration": offsets[-1] + 8.308,
        "cue_duration": 8.308,
        "cue_offsets": offsets,
    }
    segments, captions = [], []
    for offset in offsets:
        words = [
            {"word": word, "start": offset + 0.5 + i * 0.2, "end": offset + 0.6 + i * 0.2}
            for i, word in enumerate(acceptance.KNOWN_WORDS)
        ]
        segments.append({"words": words})
        start, end = words[0]["start"], words[-1]["end"]

        def clock(t):
            ms = round(t * 1000)
            return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"

        captions.append(
            f"{len(captions) + 1}\n{clock(start)} --> {clock(end)}\n"
            + " ".join(acceptance.KNOWN_WORDS)
        )
    data = {
        "source_sha256": fixture["sha256"],
        "start": 0,
        "end": fixture["duration"],
        "duration": fixture["duration"],
        "next_start": None,
        "segments": segments,
        "text": " ".join(acceptance.KNOWN_WORDS * len(offsets)),
        "word_count": len(acceptance.KNOWN_WORDS) * len(offsets),
    }
    return data, "\n\n".join(captions).encode(), fixture


@pytest.mark.parametrize("offsets", [[0], [0, 300, 600, 900]])
def test_oracle_accepts_complete_known_cues_with_absolute_subtitles(offsets):
    data, subtitles, fixture = sample_pair(offsets)
    assert acceptance.pair_verification(json.dumps(data), subtitles, fixture)["passed"]


@pytest.mark.parametrize("defect", ["missing_late_cues", "partial", "source", "srt_clock", "nan"])
def test_oracle_rejects_incomplete_or_mismatched_delivery(defect):
    data, subtitles, fixture = sample_pair([0, 300, 600, 900])
    if defect == "missing_late_cues":
        data["segments"] = data["segments"][:1]
        data["text"] = " ".join(acceptance.KNOWN_WORDS)
        data["word_count"] = len(acceptance.KNOWN_WORDS)
        subtitles = subtitles.split(b"\n\n")[0]
    elif defect == "partial":
        data.update(end=300, next_start=300)
    elif defect == "source":
        data["source_sha256"] = "b" * 64
    elif defect == "srt_clock":
        subtitles = subtitles.replace(b"00:15:00,500", b"00:15:01,500")
    else:
        data["end"] = float("nan")
    result = acceptance.pair_verification(json.dumps(data), subtitles, fixture)
    assert not result["passed"] and result["errors"]


def test_pcm_fixture_keeps_cue_bytes_exact_and_leaves_silence_between(tmp_path):
    body = io.BytesIO()
    cue = b"\x01\x02" * 8000
    with wave.open(body, "wb") as out:
        out.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        out.writeframes(cue)
    destination = tmp_path / "recording.wav"
    metadata = acceptance.make_recording(body.getvalue(), destination, [0, 300, 600, 900])
    with wave.open(str(destination), "rb") as recording:
        for offset in [0, 300, 600, 900]:
            recording.setpos(offset * 16000)
            assert recording.readframes(8000) == cue
        recording.setpos(16000)
        assert recording.readframes(8000) == b"\0" * 16000
        assert recording.getnframes() / recording.getframerate() == 900.5
    assert metadata["cue_pcm_sha256"] == acceptance.sha(cue)


def test_reviewed_local_transport_rejects_generated_programs_and_host_paths(tmp_path):
    runner = acceptance.ReviewedLocalMedia(Path("python"), tmp_path)
    prefix = ["/usr/bin/python3", "-I", "/opt/dsgpt/asset_worker.py"]
    assert not runner.permitted(["python", "generated.py"])
    assert not runner.permitted([*prefix, "read", "/etc/passwd"])
    assert not runner.permitted([*prefix, "read", "inputs/../../etc/passwd"])
    assert not runner.permitted([*prefix, "audio-transcribe", "inputs/a.wav", "a.json"])
    assert not runner.permitted([*prefix, "video-info", "inputs/a.wav"])
    assert not runner.permitted([*prefix, "video-info", "inputs/a.wav", "/tmp/info.json"])
    assert runner.permitted([*prefix, "video-info", "inputs/a.wav", "media/info.json"])
    assert runner.permitted(
        [*prefix, "audio-transcribe", "inputs/a.wav", "a.json", "--start", "0", "--duration", "300"]
    )
    assert runner.permitted(
        [
            *prefix,
            "audio-merge",
            ".dsgpt-media/assembly-" + "a" * 24 + ".json",
            "media/complete-" + "a" * 24 + ".json",
        ]
    )
    assert not runner.permitted([*prefix, "audio-merge", "/tmp/evil.json", "merged.json"])
