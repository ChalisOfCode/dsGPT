import asyncio
import hashlib
import json
import sys
import wave
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from dsgpt import asset_worker, work_assets
from dsgpt.config import Model
from dsgpt.project_tools import ProjectAction, action_schema
from dsgpt.scheduler import InferenceScheduler
from dsgpt.storage import Store
from dsgpt.web_retrieval import ResearchError
from dsgpt.work import WorkRegistry, parse_model_action
from dsgpt.work_media import PublicFileReader


class Chunks(httpx.AsyncByteStream):
    def __init__(self, *chunks):
        self.chunks = chunks

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk


def reader(handler, limit=1024):
    return PublicFileReader(lambda: httpx.MockTransport(handler), max_bytes=limit)


async def test_file_stream_redirects_drop_cookies_and_retain_provenance(tmp_path):
    calls = []

    def handle(request):
        calls.append(request)
        assert "cookie" not in request.headers and "authorization" not in request.headers
        if len(calls) == 1:
            return httpx.Response(302, headers={"location": "/audio.wav", "set-cookie": "token=x"})
        return httpx.Response(
            200,
            headers={"content-type": "audio/wav", "content-length": "6"},
            stream=Chunks(b"abc", b"def"),
        )

    output = tmp_path / "download"
    result = await reader(handle).fetch("https://example.org/start", output)
    assert result["url"] == "https://example.org/start"
    assert result["final_url"] == "https://example.org/audio.wav"
    assert result["bytes"] == 6 and output.read_bytes() == b"abcdef"
    assert result["sha256"] == hashlib.sha256(b"abcdef").hexdigest()


@pytest.mark.parametrize(
    "url",
    [
        "http://example.org/a",
        "https://127.0.0.1/a",
        "https://192.168.1.1/a",
        "https://user:pw@example.org/a",
    ],
)
async def test_file_urls_rejected_before_connection(tmp_path, url):
    def deny(request):
        pytest.fail("Private URL reached transport")

    with pytest.raises(ResearchError):
        await reader(deny).fetch(url, tmp_path / "body")


async def test_private_redirect_cannot_fetch_private_file(tmp_path):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": "https://10.0.0.1/secret"})

    with pytest.raises(ResearchError):
        await reader(handle).fetch("https://example.org/start", tmp_path / "body")
    assert len(calls) == 1


@pytest.mark.parametrize(
    "headers,chunks,error",
    [
        ({"content-type": "text/html"}, [b"login"], "download_requires_direct_file_url"),
        ({"content-encoding": "gzip"}, [b"x"], "download_encoded_response_unsupported"),
        ({"content-length": "100"}, [b"abc"], "download_file_size_limit"),
        ({}, [b"abc", b"def"], "download_file_size_limit"),
        ({"content-length": "4"}, [b"abc"], "download_incomplete"),
        ({}, [], "download_incomplete"),
    ],
)
async def test_bad_file_responses_never_become_inputs(tmp_path, headers, chunks, error):
    with pytest.raises(ResearchError, match=error):
        await reader(
            lambda _: httpx.Response(200, headers=headers, stream=Chunks(*chunks)), 5
        ).fetch("https://example.org/file", tmp_path / "body")


def setup(tmp_path, mode="on", target="files"):
    store = Store(tmp_path)
    model = Model("local", "Local", "ollama", "http://127.0.0.1:11434", "local")
    work = WorkRegistry(store, models={"local": model}, scheduler=InferenceScheduler(store))
    task = work.create(
        "Media",
        "Transcribe this public audio",
        "local",
        build_target=target,
        web_mode=mode,
        start=True,
    )
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, stream=Chunks(b"original audio"))

    work.web.media.reader = reader(handle)
    with store.transaction() as db:
        db.execute("UPDATE work_tasks SET status='running'")
    return store, work, task["id"], calls


def action(**kwargs):
    return ProjectAction(
        tool="download_file",
        summary="Download public audio",
        url="https://example.org/test.wav",
        path="test.wav",
        **kwargs,
    )


async def test_download_receipts_survive_restart_without_duplicate_network(tmp_path):
    store, work, tid, calls = setup(tmp_path)
    result = await work.web.execute(tid, 1, action())
    assert result["path"] == "inputs/test.wav" and not result["cached"]
    assert store.one("SELECT original FROM work_inputs")["original"] == b"original audio"
    same_step = await work.web.execute(tid, 1, action())
    assert same_step == result and len(calls) == 1
    another_step = await work.web.execute(tid, 2, action())
    assert another_step["cached"] and len(calls) == 1
    work.web.recover()
    assert work.web.pending(tid, 1)[1] == result
    session = store.one("SELECT * FROM work_sessions WHERE task_id=?", (tid,))
    work._commit(tid, session, action(), result)
    assert not work.web.pending(tid, 1)
    assert (
        json.loads(store.one("SELECT result FROM work_steps")["result"])["path"] == result["path"]
    )
    with store.connect() as db:
        snapshot, _ = work_assets.snapshot(db, tid)
    assert snapshot[0]["content"] == b"original audio"
    assert not list(tmp_path.glob("public-file-*"))


@pytest.mark.parametrize(
    "mode,target,error",
    [("off", "files", "work_web_disabled"), ("on", "source", "download_requires_isolated_work")],
)
async def test_download_cannot_bypass_permission_or_isolation(tmp_path, mode, target, error):
    store, work, tid, calls = setup(tmp_path, mode, target)
    result = await work.web.execute(tid, 1, action())
    assert result["error"] == error and not calls
    assert not store.all("SELECT * FROM work_inputs")


async def test_existing_originals_and_input_limits_preserved(tmp_path):
    store, work, tid, calls = setup(tmp_path)
    await work.web.execute(tid, 1, action())
    conflict = action().model_copy(update={"url": "https://example.org/different.wav"})
    assert (await work.web.execute(tid, 2, conflict))["error"] == "download_filename_already_exists"
    assert len(calls) == 1
    with store.transaction() as db:
        for name in ("two", "three", "four"):
            db.execute("INSERT INTO work_inputs VALUES(?,?,?,?,'{}')", (tid, name, b"x", "h"))
    extra = action().model_copy(update={"path": "five.wav"})
    assert (await work.web.execute(tid, 3, extra))["error"] == "work_input_limit_reached"
    assert (
        len(calls) == 1
        and store.one("SELECT original FROM work_inputs WHERE name='test.wav'")["original"]
        == b"original audio"
    )


@pytest.mark.parametrize("change", ["pause", "revoke", "cancel"])
async def test_late_or_cancelled_downloads_are_discarded_and_cleaned(tmp_path, change):
    store, work, tid, _ = setup(tmp_path)
    started, release = asyncio.Event(), asyncio.Event()

    class Delayed:
        async def fetch(self, url, output):
            output.write_bytes(b"partial")
            started.set()
            await release.wait()
            return {"url": url, "bytes": 7, "sha256": hashlib.sha256(b"partial").hexdigest()}

    work.web.media.reader = Delayed()
    pending = asyncio.create_task(work.web.execute(tid, 1, action()))
    await started.wait()
    if change == "cancel":
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert work.web.pending(tid, 1)[1]["error"] == "research_interrupted"
    else:
        with store.transaction() as db:
            db.execute(
                "UPDATE work_tasks SET status='paused',revision=revision+1"
                if change == "pause"
                else "UPDATE generation_options SET web_mode='off'"
            )
        release.set()
        result = await pending
        assert result["error"] in {"research_result_discarded", "work_web_disabled"}
    assert not store.all("SELECT * FROM work_inputs")
    assert not list(tmp_path.glob("public-file-*"))


def test_download_schema_and_filenames():
    for enabled, isolated in [(False, True), (True, False), (True, True)]:
        names = {
            r["properties"]["tool"]["const"]
            for r in action_schema(web_research=enabled, isolated_execution=isolated)["oneOf"]
        }
        assert ("download_file" in names) == (enabled and isolated)
    for name in ["../a", "inputs/../a.wav", "inputs/sub/a.wav", "NUL", "a" * 161]:
        with pytest.raises(ValidationError):
            ProjectAction(tool="download_file", summary="x", url="https://example.org/a", path=name)
    normalized = ProjectAction(
        tool="download_file", summary="x", url="https://example.org/a", path="inputs/a.wav"
    )
    assert normalized.path == "a.wav"


def test_model_progress_annotations_do_not_become_tool_arguments():
    value = {
        "tool": "download_file",
        "summary": "Fetch input",
        "url": "https://example.org/a.wav",
        "path": "inputs/a.wav",
        "progress": "Downloaded",
        "next_offset": 455,
    }
    parsed = parse_model_action(json.dumps(value))
    assert parsed.path == "a.wav" and parsed.offset == 0
    with pytest.raises(ValidationError):
        parse_model_action(json.dumps({**value, "shell_command": "unrecognized command"}))
    with pytest.raises(ValidationError):
        parse_model_action("{broken json")


def test_download_grammar_reuses_exact_request_and_observed_urls(tmp_path):
    store, work, tid, _ = setup(tmp_path)
    with store.transaction() as db:
        db.execute(
            "UPDATE work_tasks SET requirements=? WHERE id=?",
            (
                "Read https://example.org/video.mp4. Then (https://example.org/a_(b).wav). "
                "Do not fetch https://127.0.0.1/private",
                tid,
            ),
        )
    urls = work.web.media.urls(tid)
    assert urls == ["https://example.org/video.mp4", "https://example.org/a_(b).wav"]
    schema = action_schema(web_research=True, isolated_execution=True, download_urls=urls)
    tool = next(r for r in schema["oneOf"] if r["properties"]["tool"]["const"] == "download_file")
    assert tool["properties"]["url"] == {"enum": urls}


def test_bundled_guide_is_not_mistaken_for_private_user_input(tmp_path):
    store, work, tid, _ = setup(tmp_path, mode="auto")
    assert work.web.enabled(tid)
    assert store.one(
        "SELECT 1 FROM work_files WHERE task_id=? AND path='work-assets-guide.txt'", (tid,)
    )
    private = work.create(
        "Private",
        "Inspect source",
        "local",
        build_target="files",
        source_files=[{"name": "private.txt", "text": "private material"}],
        web_mode="auto",
    )
    assert not work.web.enabled(private["id"])


def test_transcription_outputs_absolute_timestamps_and_continuation(tmp_path, monkeypatch):
    monkeypatch.setattr(asset_worker, "ROOT", tmp_path)
    monkeypatch.setattr(
        asset_worker,
        "video_info",
        lambda _: {"streams": [{"codec_type": "audio"}], "format": {"duration": "1000"}},
    )
    calls = []

    def convert(argv, **kwargs):
        calls.append(argv)
        with wave.open(str(argv[-1]), "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(16000)
            f.writeframes(b"\0" * 8000)

    monkeypatch.setattr(asset_worker, "command", convert)

    class Recognizer:
        def __init__(self, *args):
            pass

        def SetWords(self, value):
            assert value

        def AcceptWaveform(self, data):
            return False

        def FinalResult(self):
            return json.dumps(
                {
                    "text": "hello there",
                    "result": [
                        {"word": "hello", "start": 0.1, "end": 0.2, "conf": 0.9},
                        {"word": "there", "start": 0.2, "end": 0.25, "conf": 0.4},
                    ],
                }
            )

    monkeypatch.setitem(
        sys.modules,
        "vosk",
        SimpleNamespace(
            Model=lambda path: path, KaldiRecognizer=Recognizer, SetLogLevel=lambda _: None
        ),
    )
    source = tmp_path / "media.mp4"
    source.write_bytes(b"source")
    output = tmp_path / "speech.json"
    result = asset_worker.audio_transcribe(source, output, start=60, seconds=300)
    report = json.loads(output.read_text())
    assert report["segments"][0]["words"][0]["start"] == 60.1
    assert report["uncertain_words"] == 1 and result["next_start"] == 360
    assert "00:01:00,100 --> 00:01:00,250" in output.with_suffix(".srt").read_text()
    assert calls[0][calls[0].index("-t") + 1] == "300"
    assert result["transcript"] == "speech.json" and result["subtitles"] == "speech.srt"
    assert source.read_bytes() == b"source"


@pytest.mark.parametrize(
    "start,seconds", [(-1, 10), (float("inf"), 10), (0, 901), (0, float("nan")), (0, 0)]
)
def test_transcription_rejects_unbounded_requests(tmp_path, start, seconds):
    with pytest.raises(ValueError):
        asset_worker.audio_transcribe(tmp_path / "x", tmp_path / "out.json", start, seconds)


def test_transcription_rejects_silent_video_before_loading_model(tmp_path, monkeypatch):
    monkeypatch.setattr(
        asset_worker, "video_info", lambda _: {"streams": [{"codec_type": "video"}]}
    )
    with pytest.raises(ValueError, match="no audio"):
        asset_worker.audio_transcribe(tmp_path / "x", tmp_path / "out.json")
