"""Fresh actual-model media acceptance; never rescues prompts/actions/checkpoints.

Two boundaries are deliberately separate:
* --execution docker uses the production checked, networkless Docker runner.
* --execution reviewed-local permits only the reviewed asset worker's known media
  commands on generated test fixtures. It is NOT evidence of Docker isolation.

The model endpoint must already be running. This script never starts/pulls a model.
Use a new output directory for every attempt; completed/blocked tasks are never
resumed. Source drift aborts the acceptance result instead of mixing versions.
"""

import argparse
import asyncio
import hashlib
import io
import json
import math
import os
import re
import shutil
import signal
import tempfile
import time
import wave
from dataclasses import replace
from pathlib import Path

import httpx

import dsgpt
from dsgpt.builds import WorkBuilds
from dsgpt.config import Model
from dsgpt.inference import LocalInference
from dsgpt.project_tools import safe_path
from dsgpt.scheduler import InferenceScheduler
from dsgpt.storage import Store
from dsgpt.work import WorkRegistry
from dsgpt.work_media import PublicFileReader

SAMPLE_URL = "https://raw.githubusercontent.com/alphacep/vosk-api/master/python/example/test.wav"
SAMPLE_SHA = "dcfea5712c43a43ba7ae8083afb39d36993e5a69c46e88b68aaa72b65cb615bb"
KNOWN_WORDS = "one zero zero zero one nine oh two one oh zero one eight zero three".split()
CASES = {"short": [0], "medium": [0, 300], "long": [0, 300, 600, 900]}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def native_model_provenance(args):
    """Require an independently audited native copy; no quantization/model substitution."""
    if not args.native_model or not args.conversion_audit:
        raise ValueError("llama.cpp acceptance requires the native file and conversion audit")
    audit_bytes = args.conversion_audit.read_bytes()
    audit = json.loads(audit_bytes)
    with args.native_model.open("rb") as source:
        native_sha = hashlib.file_digest(source, "sha256").hexdigest()
    if (
        audit.get("passed") is not True
        or audit.get("quantization_preserved") is not True
        or audit.get("active_weights_preserved") is not True
        or audit.get("converted_gguf_sha256") != native_sha
        or audit.get("source_gguf_sha256") != args.original_gguf_sha256
        or audit.get("original_model_tag") != args.original_model_tag
        or not re.fullmatch(r"[a-f0-9]{64}", args.original_gguf_sha256 or "")
    ):
        raise ValueError("Native model does not match the passing original-model conversion audit")
    return {
        "path": str(args.native_model),
        "sha256": native_sha,
        "bytes": args.native_model.stat().st_size,
        "original_model_tag": args.original_model_tag,
        "source_gguf_sha256": args.original_gguf_sha256,
        "conversion_audit_path": str(args.conversion_audit),
        "conversion_audit_sha256": sha(audit_bytes),
        "conversion_audit": audit,
        "scope": "Native text-only copy of the same active weights; not the Ollama environment",
    }


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def source_hashes():
    root = Path(dsgpt.__file__).resolve().parent
    return {p.name: sha(p.read_bytes()) for p in sorted(root.glob("*.py"))}


def make_recording(sample, target, cue_offsets):
    """Place exact known PCM cues in silence without transcoding their samples."""
    with wave.open(io.BytesIO(sample), "rb") as source:
        params = source.getparams()
        if params.nchannels != 1 or params.sampwidth != 2 or params.comptype != "NONE":
            raise ValueError("Expected mono signed 16-bit PCM sample")
        cue = source.readframes(params.nframes)
    with wave.open(str(target), "wb") as out:
        out.setparams(params)
        frame = 0
        for offset in cue_offsets:
            position = round(offset * params.framerate)
            if position < frame:
                raise ValueError("Cue windows overlap")
            out.writeframesraw(b"\0" * ((position - frame) * 2))
            out.writeframesraw(cue)
            frame = position + params.nframes
    return {
        "sha256": sha(target.read_bytes()),
        "bytes": target.stat().st_size,
        "duration": frame / params.framerate,
        "cue_offsets": cue_offsets,
        "cue_duration": params.nframes / params.framerate,
        "cue_pcm_sha256": sha(cue),
        "sample_sha256": sha(sample),
    }


def srt_captions(body):
    captions = []
    pattern = re.compile(r"(\d+):(\d\d):(\d\d),(\d{3}) --> (\d+):(\d\d):(\d\d),(\d{3})")
    for block in re.split(r"\n\s*\n", body.strip()):
        lines = block.splitlines()
        if len(lines) < 3 or not lines[0].isdigit():
            raise ValueError("Invalid subtitle block")
        match = pattern.fullmatch(lines[1])
        if not match:
            raise ValueError("Invalid subtitle timestamp")
        n = [int(x) for x in match.groups()]
        if any(n[index] >= 60 for index in (1, 2, 5, 6)) or int(lines[0]) != len(captions) + 1:
            raise ValueError("Invalid subtitle numbering or clock")
        start = n[0] * 3600 + n[1] * 60 + n[2] + n[3] / 1000
        end = n[4] * 3600 + n[5] * 60 + n[6] + n[7] / 1000
        if not 0 <= start < end:
            raise ValueError("Invalid subtitle interval")
        captions.append({"start": start, "end": end, "words": " ".join(lines[2:]).split()})
    return captions


def pair_verification(transcript, subtitles, fixture):
    """Independent acceptance oracle: full coverage, every known cue, matching SRT."""
    errors = []
    try:
        data = json.loads(transcript)
        captions = srt_captions(subtitles.decode("utf-8"))
        if data["source_sha256"] != fixture["sha256"]:
            errors.append("wrong_original_source_hash")
        if any(
            type(data[key]) not in {int, float} or not math.isfinite(data[key])
            for key in ("start", "end", "duration")
        ):
            raise ValueError("Invalid media duration")
        if (
            abs(data["start"]) > 0.001
            or abs(data["end"] - fixture["duration"]) > 0.001
            or abs(data["duration"] - fixture["duration"]) > 0.001
            or data.get("next_start") is not None
        ):
            errors.append("partial_media_coverage")
        words = [word for segment in data["segments"] for word in segment["words"]]
        if any(not math.isfinite(word[axis]) for word in words for axis in ("start", "end")) or any(
            not 0 <= word["start"] <= word["end"] <= fixture["duration"] + 0.01 for word in words
        ):
            errors.append("invalid_word_timestamps")
        if any(
            right["start"] < left["start"] for left, right in zip(words, words[1:], strict=False)
        ):
            errors.append("non_monotonic_words")
        actual_words = [word["word"] for word in words]
        if actual_words != data["text"].split() or data["word_count"] != len(words):
            errors.append("inconsistent_json_text")
        if [word for caption in captions for word in caption["words"]] != actual_words:
            errors.append("subtitles_do_not_match_json")
        index = 0
        for caption in captions:
            batch = words[index : index + len(caption["words"])]
            if (
                not batch
                or abs(caption["start"] - batch[0]["start"]) > 0.002
                or abs(caption["end"] - batch[-1]["end"]) > 0.002
            ):
                errors.append("subtitle_timestamps_do_not_match_json")
                break
            index += len(batch)
        if any(
            right["start"] < left["start"]
            for left, right in zip(captions, captions[1:], strict=False)
        ):
            errors.append("non_monotonic_subtitles")
        # The oracle is for this known clean fixture, not a general ASR accuracy guarantee.
        for offset in fixture["cue_offsets"]:
            cue_words = [
                word["word"]
                for word in words
                if offset <= word["start"] < offset + fixture["cue_duration"]
            ]
            if cue_words != KNOWN_WORDS:
                errors.append(f"known_speech_missing_or_changed_at_{offset}s")
            cue_captions = [
                caption
                for caption in captions
                if offset <= caption["start"] < offset + fixture["cue_duration"]
            ]
            if not cue_captions or any(
                caption["end"] > offset + fixture["cue_duration"] + 0.01 for caption in cue_captions
            ):
                errors.append(f"subtitle_timing_missing_or_wrong_at_{offset}s")
        if len(actual_words) != len(KNOWN_WORDS) * len(fixture["cue_offsets"]):
            errors.append("unexpected_or_missing_spoken_words")
        return {
            "passed": not errors,
            "errors": errors,
            "word_count": len(words),
            "captions": len(captions),
        }
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        return {
            "passed": False,
            "errors": ["invalid_transcript_or_subtitles"],
            "detail": type(exc).__name__,
        }


class CPUClient(httpx.AsyncClient):
    def __init__(self, *args, cpu_threads=4, **kwargs):
        super().__init__(*args, **kwargs)
        self.cpu_threads = cpu_threads

    def build_request(self, method, url, **kwargs):
        if str(url).endswith("/api/chat") and kwargs.get("json"):
            kwargs["json"].setdefault("options", {}).update(
                num_thread=self.cpu_threads, use_mmap=True, num_batch=64
            )
        return super().build_request(method, url, **kwargs)


class AcceptanceInference(LocalInference):
    """Resource/time settings only. Production stream/parser/actions remain unchanged."""

    def __init__(self, threads, case=None):
        super().__init__()
        self.threads = threads
        self.case = case
        self.calls = 0

    def client(self, model):
        return CPUClient(
            base_url=model.endpoint,
            trust_env=False,
            cpu_threads=self.threads,
            timeout=httpx.Timeout(connect=5, read=900, write=30, pool=5),
        )

    async def stream(self, model, messages, response_schema=None):
        self.calls += 1
        started = last = time.monotonic()
        visible_bytes = 0
        try:
            async for event in super().stream(model, messages, response_schema=response_schema):
                if event["kind"] == "delta":
                    visible_bytes += len(event["data"]["text"].encode("utf-8"))
                now = time.monotonic()
                if now - last >= 30:
                    print(
                        json.dumps(
                            {
                                "case": self.case,
                                "inference_call": self.calls,
                                "elapsed_seconds": round(now - started, 3),
                                "visible_output_bytes": visible_bytes,
                                "inference_finished": False,
                            }
                        ),
                        flush=True,
                    )
                    last = now
                yield event
        finally:
            print(
                json.dumps(
                    {
                        "case": self.case,
                        "inference_call": self.calls,
                        "elapsed_seconds": round(time.monotonic() - started, 3),
                        "visible_output_bytes": visible_bytes,
                        "inference_finished": True,
                    }
                ),
                flush=True,
            )


class FixtureBytes(httpx.AsyncByteStream):
    def __init__(self, path):
        self.path = path

    async def __aiter__(self):
        with self.path.open("rb") as source:
            while chunk := source.read(256 * 1024):
                yield chunk


class ReviewedLocalMedia:
    """TEST ONLY: fixed reviewed worker commands, never arbitrary generated host code."""

    def __init__(self, worker_python, temporary_root):
        self.python = worker_python
        self.root = temporary_root
        self.worker = Path(dsgpt.__file__).resolve().parent / "asset_worker.py"

    async def cleanup(self, identifier):
        pass  # Each temporary directory/process is owned and cleaned by execute.

    def permitted(self, argv):
        if len(argv) < 5 or argv[:3] != ["/usr/bin/python3", "-I", "/opt/dsgpt/asset_worker.py"]:
            return False
        try:
            if argv[3] == "audio-merge":
                return (
                    len(argv) == 6
                    and re.fullmatch(r"\.dsgpt-media/assembly-[a-f0-9]{24}\.json", argv[4])
                    is not None
                    and re.fullmatch(r"media/complete-[a-f0-9]{24}\.json", argv[5]) is not None
                )
            path = safe_path(argv[4])
            if not path.startswith(("inputs/", "receipts/")):
                return False
            if argv[3] == "audio-transcribe":
                return (
                    len(argv) == 10
                    and safe_path(argv[5]).endswith(".json")
                    and argv[6] == "--start"
                    and argv[8] == "--duration"
                    and 0 <= float(argv[7]) <= 604800
                    and 1 <= float(argv[9]) <= 900
                )
            if argv[3] == "video-info":
                return len(argv) == 6 and safe_path(argv[5]).endswith(".json")
            if argv[3] == "read":
                return len(argv) == 5 or (
                    len(argv) == 7 and argv[5] == "--offset" and 0 <= int(argv[6]) <= 768 * 1024**2
                )
        except (ValueError, TypeError):
            return False
        return False

    async def execute(self, identifier, files, argv, artifacts, timeout, **kwargs):
        if not self.permitted(argv):
            return {
                "exit_code": 1,
                "stdout": "",
                "stderr": (
                    "Acceptance fixture permits only reviewed asset-worker media commands. "
                    "No arbitrary host command was executed."
                ),
                "omitted_output_bytes": 0,
                "artifacts": [],
            }
        with tempfile.TemporaryDirectory(prefix="reviewed-media-", dir=self.root) as directory:
            folder = Path(directory)
            for item in files:
                path = folder / safe_path(item["path"])
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(
                    item["content"].encode()
                    if isinstance(item["content"], str)
                    else item["content"]
                )
            process = await asyncio.create_subprocess_exec(
                str(self.python),
                "-I",
                str(self.worker),
                *argv[3:],
                cwd=folder,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=os.name == "posix",
            )
            try:
                out, err = await asyncio.wait_for(process.communicate(), timeout=min(timeout, 900))
            except BaseException:
                if process.returncode is None:
                    try:
                        if os.name == "posix":
                            os.killpg(process.pid, signal.SIGKILL)
                        else:
                            process.kill()
                    except ProcessLookupError:
                        pass
                    await process.wait()
                raise
            saved = []
            if process.returncode == 0:
                for name in artifacts:
                    path = folder / safe_path(name)
                    if not path.is_file() or path.stat().st_size > 8 * 1024**2:
                        return {
                            "exit_code": 1,
                            "stdout": out.decode(),
                            "stderr": "Expected bounded artifact was not produced",
                            "omitted_output_bytes": 0,
                            "artifacts": [],
                        }
                    body = path.read_bytes()
                    saved.append({"path": name, "content": body, "sha256": sha(body)})
            return {
                "exit_code": process.returncode,
                "stdout": out.decode(errors="replace"),
                "stderr": err.decode(errors="replace"),
                "omitted_output_bytes": 0,
                "artifacts": saved,
            }


def evaluate_task(store, task_id, fixture):
    """Read current successful receipts independently of the model's completion claim."""
    rows = store.all(
        "SELECT a.*,e.status,e.cleanup_pending,e.step FROM work_artifacts a "
        "JOIN work_executions e ON e.id=a.execution_id WHERE a.task_id=? AND e.task_id=? "
        "ORDER BY e.step DESC,a.rowid DESC",
        (task_id, task_id),
    )
    finish = store.one(
        "SELECT result FROM work_steps WHERE task_id=? AND "
        "json_extract(action,'$.tool')='finish' ORDER BY step DESC LIMIT 1",
        (task_id,),
    )
    delivered = (
        {item["id"]: item for item in json.loads(finish["result"]).get("artifacts", [])}
        if finish
        else {}
    )
    retained = any(
        row["sha256"] == fixture["sha256"] and sha(row["original"]) == fixture["sha256"]
        for row in store.all("SELECT sha256,original FROM work_inputs WHERE task_id=?", (task_id,))
    )
    current = {}
    for row in rows:
        current.setdefault(row["path"], row)
    pairs = []
    for path, row in current.items():
        peer = current.get(str(Path(path).with_suffix(".srt")))
        if not path.endswith(".json") or not peer:
            continue
        if any(
            item["status"] != "completed"
            or item["cleanup_pending"]
            or sha(item["content"]) != item["sha256"]
            for item in (row, peer)
        ):
            continue
        result = pair_verification(row["content"], peer["content"], fixture)
        if any(
            item["id"] not in delivered or delivered[item["id"]].get("sha256") != item["sha256"]
            for item in (row, peer)
        ):
            result["passed"] = False
            result["errors"].append("matching_pair_not_in_final_delivery")
        pairs.append({"json": path, "srt": peer["path"], **result})
    completed = (
        store.one("SELECT status FROM work_tasks WHERE id=?", (task_id,))["status"] == "completed"
    )
    windows = []
    for row in store.all(
        "SELECT result FROM work_executions WHERE task_id=? AND status='completed' "
        "AND cleanup_pending=0 AND json_extract(action,'$.tool')='transcribe_media' "
        "ORDER BY step",
        (task_id,),
    ):
        item = json.loads(row["result"]).get("transcription", {})
        if item.get("source_sha256") == fixture["sha256"]:
            windows.append([item.get("start_seconds"), item.get("end_seconds")])
    windows = sorted({tuple(window) for window in windows})
    coverage_errors = []
    cursor = 0
    for start, end in windows:
        if start is None or end is None or abs(start - cursor) > 0.001 or not start < end:
            coverage_errors.append("transcription_windows_not_contiguous")
            break
        if len(fixture["cue_offsets"]) > 1 and end - start > 300.001:
            coverage_errors.append("requested_five_minute_chunk_limit_exceeded")
        cursor = end
    if abs(cursor - fixture["duration"]) > 0.001:
        coverage_errors.append("transcription_windows_do_not_cover_recording")
    return {
        "passed": completed
        and retained
        and not coverage_errors
        and any(pair["passed"] for pair in pairs),
        "task_completed": completed,
        "exact_input_retained": retained,
        "transcription_windows": windows,
        "coverage_errors": coverage_errors,
        "pairs": pairs,
    }


async def run_case(args, case, fixture_path, fixture, model, expected_sources):
    folder = args.output / case
    folder.mkdir()
    store = Store(folder / "database")
    assert not store.all("SELECT id FROM work_tasks")
    inference = AcceptanceInference(args.threads, case=case)
    if args.execution == "docker":
        builds = WorkBuilds(store, args.image)
        await builds.probe()
    else:
        builds = WorkBuilds(store, sandbox=ReviewedLocalMedia(args.worker_python, folder))
        builds.ready = True
    work = WorkRegistry(
        store,
        models={model.id: model},
        inference=inference,
        scheduler=InferenceScheduler(store),
        builds=builds,
    )
    url = (
        SAMPLE_URL
        if case == "short"
        else f"https://example.org/dsgpt-fixtures/{case}-recording.wav"
    )
    requests = []

    def handle(request):
        requests.append(str(request.url))
        return (
            httpx.Response(
                200, headers={"content-type": "audio/wav"}, stream=FixtureBytes(fixture_path)
            )
            if str(request.url) == url
            else httpx.Response(404)
        )

    work.web.media.reader = PublicFileReader(lambda: httpx.MockTransport(handle))
    prompt = (
        f"Download the recording at {url} and transcribe the whole recording. "
        "Deliver one complete JSON transcript and a matching SRT subtitle file with the actual "
        "spoken words and their original timestamps. Include the entire recording, including "
        "speech after quiet sections. "
        "Check the saved outputs, then finish."
    )
    if len(fixture["cue_offsets"]) > 1:
        prompt += " Use chunks no longer than five minutes."
    task = work.create(
        f"Fresh {case} transcription",
        prompt,
        model.id,
        build_target="files",
        web_mode="on",
        start=True,
    )
    started = time.monotonic()
    report = {
        "case": case,
        "task_id": task["id"],
        "prompt": prompt,
        "fixture": fixture,
        "steps": [],
        "fresh_task": True,
        "resumed": False,
        "action_rewriting": False,
        "prompt_rescue": False,
        "requests": requests,
    }
    stop = None
    try:
        for _ in range(args.max_steps):
            if shutil.disk_usage(folder).free < 512 * 1024**2:
                stop = "acceptance_insufficient_disk_space"
                break
            if source_hashes() != expected_sources:
                stop = "production_source_changed"
                break
            row = store.one("SELECT * FROM work_tasks WHERE id=?", (task["id"],))
            if row["status"] in {"completed", "blocked"}:
                break
            remaining = args.max_seconds - (time.monotonic() - started)
            if remaining <= 0:
                stop = "acceptance_wall_time_limit"
                break
            before = store.one("SELECT step FROM work_sessions WHERE task_id=?", (task["id"],))[
                "step"
            ]
            turn = time.monotonic()
            await asyncio.wait_for(work._step(row), timeout=min(remaining, 1000))
            for step in store.all(
                "SELECT * FROM work_steps WHERE task_id=? AND step>? ORDER BY step",
                (task["id"], before),
            ):
                item = {
                    "step": step["step"],
                    "action": json.loads(step["action"]),
                    "result": json.loads(step["result"]),
                    "seconds": round(time.monotonic() - turn, 3),
                }
                report["steps"].append(item)
                print(
                    json.dumps(
                        {
                            "case": case,
                            "step": step["step"],
                            "tool": item["action"].get("tool"),
                            "error": item["result"].get("error"),
                            "seconds": item["seconds"],
                        }
                    ),
                    flush=True,
                )
            report.update(
                status=work.get(task["id"])["status"],
                elapsed_seconds=round(time.monotonic() - started, 3),
            )
            write_json(folder / "report.json", report)
        else:
            stop = "acceptance_step_limit"
    except TimeoutError:
        stop = "acceptance_wall_time_limit"
    except Exception as exc:
        stop = "acceptance_harness_error"
        report["harness_error"] = {"type": type(exc).__name__, "message": str(exc)[:300]}
    finally:
        try:
            await inference.release_resident()
        except Exception as exc:
            report["runtime_release_error"] = type(exc).__name__
    state = work.get(task["id"])
    report.update(
        status=state["status"],
        error_code=state["session"]["error_code"],
        harness_stop_reason=stop,
        elapsed_seconds=round(time.monotonic() - started, 3),
        source_unchanged=source_hashes() == expected_sources,
    )
    report["verification"] = evaluate_task(store, task["id"], fixture)
    report["passed"] = (
        report["verification"]["passed"] and report["source_unchanged"] and stop is None
    )
    report["artifacts"] = []
    for artifact in store.all(
        "SELECT id,path,sha256,bytes,content FROM work_artifacts WHERE task_id=?", (task["id"],)
    ):
        target = folder / "artifacts" / artifact["id"] / safe_path(artifact["path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(artifact.pop("content"))
        report["artifacts"].append(artifact)
    write_json(folder / "report.json", report)
    return report


async def main(args):
    if args.output.exists():
        raise ValueError("Use a new output directory; this acceptance never resumes an earlier run")
    if len(set(args.cases)) != len(args.cases):
        raise ValueError("Each case may appear only once in a fresh acceptance run")
    sample = args.sample_wav.read_bytes()
    if sha(sample) != SAMPLE_SHA:
        raise ValueError("Known public sample hash mismatch")
    args.output.mkdir(parents=True)
    sources = source_hashes()
    fixtures = {}
    for case in args.cases:
        path = args.output / f"{case}.wav"
        fixtures[case] = make_recording(sample, path, CASES[case])
        if case == "short":
            # Retain the original RIFF metadata/hash for the real public URL fixture.
            path.write_bytes(sample)
            fixtures[case].update(sha256=SAMPLE_SHA, bytes=len(sample))
    evidence = {
        "prepare_only": args.prepare_only,
        "fresh_end_to_end_completion_passed": False,
        "source_commit": args.source_commit,
        "production_source_sha256": sources,
        "harness_sha256": sha(Path(__file__).read_bytes()),
        "inference_backend": args.runtime,
        "execution_boundary": args.execution,
        "network": (
            "Controlled exact-byte public-URL fixtures; not live internet evidence. "
            "scripts/live_media.py separately verifies live public retrieval plus Docker."
        ),
        "fixture_sample_url": SAMPLE_URL,
        "fixtures": fixtures,
        "runtime_settings": {
            "context": args.context,
            "output_tokens": args.output_tokens,
            "cpu_threads": args.threads,
            "batch": 64,
            "mmap": True,
            "recommended_server_environment": {
                "OLLAMA_NUM_PARALLEL": "1",
                "OLLAMA_MAX_LOADED_MODELS": "1",
                "LLAMA_ARG_CTX_CHECKPOINTS": "2",
                "LLAMA_ARG_CACHE_RAM": "0",
            },
        },
        "no_owner_gpu_benchmark": True,
        "cases": [],
    }
    write_json(args.output / "validation.json", evidence)
    if args.prepare_only:
        print("Prepared known-speech fixtures; no inference server was contacted", flush=True)
        return 0
    if shutil.disk_usage(args.output).free < 1024**3:
        raise ValueError("Keep at least 1 GiB free before starting actual-model media acceptance")
    if args.execution == "reviewed-local" and (
        not args.worker_python or not args.worker_python.is_file()
    ):
        raise ValueError("Reviewed-local execution requires the Vosk-enabled --worker-python")
    if args.execution == "docker" and (not args.image or not shutil.which("docker")):
        raise ValueError("Docker execution requires an available Docker CLI and reviewed --image")
    if args.runtime == "llama.cpp":
        evidence["native_model"] = native_model_provenance(args)
    model = Model(
        "local",
        "Actual local media acceptance",
        args.runtime,
        args.endpoint,
        args.model,
        abliterated=True,
        context=args.context,
        output_tokens=args.output_tokens,
    )
    async with httpx.AsyncClient(base_url=model.endpoint, trust_env=False, timeout=10) as client:
        if model.runtime == "ollama":
            response = await client.get("/api/tags")
            response.raise_for_status()
            installed = next(
                (m for m in response.json()["models"] if m["name"] == model.runtime_model), None
            )
            if not installed:
                raise ValueError(
                    "Requested actual local model is not installed; no automatic pull attempted"
                )
            evidence["runtime_model"] = {
                key: installed.get(key) for key in ("name", "digest", "size", "details")
            }
            model = replace(model, expected_digest=installed["digest"])
        else:
            response = await client.get("/v1/models")
            response.raise_for_status()
            served = response.json()
            response = await client.get("/props")
            response.raise_for_status()
            props = response.json()
            if model.runtime_model not in {item["id"] for item in served.get("data", [])}:
                raise ValueError("Requested native model alias is not served")
            if props.get("default_generation_settings", {}).get("n_ctx") != model.context:
                raise ValueError("Native runtime is not serving the exact requested context")
            evidence["runtime_model"] = {"alias": model.runtime_model, "models": served}
            evidence["runtime_props"] = props
    for case in args.cases:
        report = await run_case(
            args, case, args.output / f"{case}.wav", fixtures[case], model, sources
        )
        evidence["cases"].append(
            {
                "case": case,
                "passed": report["passed"],
                "status": report["status"],
                "report": f"{case}/report.json",
                "elapsed_seconds": report["elapsed_seconds"],
            }
        )
        evidence["passed"] = len(evidence["cases"]) == len(args.cases) and all(
            case["passed"] for case in evidence["cases"]
        )
        evidence["fresh_end_to_end_completion_passed"] = evidence["passed"]
        write_json(args.output / "validation.json", evidence)
        if not report["passed"]:
            break
    return 0 if evidence.get("passed") else 1


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-wav", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default="huihui_ai/qwen3.5-abliterated:9b")
    parser.add_argument("--runtime", choices=["ollama", "llama.cpp"], default="ollama")
    parser.add_argument("--native-model", type=Path)
    parser.add_argument("--conversion-audit", type=Path)
    parser.add_argument("--original-gguf-sha256")
    parser.add_argument("--original-model-tag", default="huihui_ai/qwen3.5-abliterated:9b")
    parser.add_argument("--execution", choices=["docker", "reviewed-local"], required=True)
    parser.add_argument("--worker-python", type=Path)
    parser.add_argument("--image")
    parser.add_argument("--cases", nargs="+", choices=sorted(CASES), default=["short", "long"])
    parser.add_argument("--context", type=int, default=16384)
    parser.add_argument("--output-tokens", type=int, default=2048)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--max-steps", type=int, default=30)
    parser.add_argument("--max-seconds", type=int, default=7200)
    parser.add_argument("--prepare-only", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(arguments())))
