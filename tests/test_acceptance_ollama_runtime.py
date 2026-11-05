"""Exercise unattended runtime acquisition, interrupted transfers and damaged-cache recovery."""

import hashlib
import importlib
import io
import json
import zipfile

import httpx
import pytest
from test_acceptance_harness import main, make_runner

runtime = importlib.import_module("dsgpt_acceptance_test.ollama_runtime")


def archive_spec(files):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    data = data.getvalue()
    return data, {
        "version": "fixture",
        "url": "https://publisher.invalid/cli.zip",
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def test_fresh_install_reuses_verified_cache_and_repairs_damaged_files(tmp_path, monkeypatch):
    data, spec = archive_spec({"ollama.exe": b"test CLI", "lib/ollama/cuda.dll": b"test GPU"})
    monkeypatch.setattr(runtime, "OLLAMA", spec)
    requests = []

    def fetch(request):
        requests.append(request)
        return httpx.Response(200, content=data)

    with httpx.Client(transport=httpx.MockTransport(fetch)) as client:
        exe = runtime.install(client, tmp_path)
        assert exe.read_bytes() == b"test CLI"
        assert runtime.installed_ok(exe.parent, spec)
        assert runtime.install(client, tmp_path) == exe
        (exe.parent / "lib/ollama/cuda.dll").write_bytes(b"damaged")
        (exe.parent / "extra.dll").write_bytes(b"unwanted")
        assert not runtime.installed_ok(exe.parent, spec)
        runtime.install(client, tmp_path)
        assert runtime.installed_ok(exe.parent, spec)
        assert len(requests) == 1  # Repair reuses the publisher-verified archive.


@pytest.mark.parametrize("honor_range", [True, False])
def test_download_resumes_saved_bytes_or_restarts_if_server_ignores_range(tmp_path, honor_range):
    data, spec = archive_spec({"ollama.exe": b"test CLI"})
    target = tmp_path / "engine.zip"
    target.with_suffix(".partial").write_bytes(data[:20])

    def fetch(request):
        assert request.headers["Range"] == "bytes=20-"
        return httpx.Response(
            206 if honor_range else 200,
            headers={"Content-Range": f"bytes 20-{len(data) - 1}/{len(data)}"}
            if honor_range
            else {},
            content=data[20:] if honor_range else data,
        )

    with httpx.Client(transport=httpx.MockTransport(fetch)) as client:
        runtime.download(client, target, spec, lambda _: None)
    assert target.read_bytes() == data


def test_bad_publisher_checksum_is_never_extracted(tmp_path, monkeypatch):
    data, spec = archive_spec({"ollama.exe": b"test CLI"})
    spec["sha256"] = "0" * 64
    monkeypatch.setattr(runtime, "OLLAMA", spec)
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=data))
    ) as client:
        with pytest.raises(ValueError, match="checksum mismatch"):
            runtime.install(client, tmp_path)
    assert not (tmp_path / "ollama-fixture").exists()


@pytest.mark.parametrize(
    "name", ["../escaped.exe", "C:/bad.exe", "NUL.txt", "lib/../bad", "bad.exe:stream"]
)
def test_unsafe_archive_does_not_replace_working_cache(tmp_path, monkeypatch, name):
    data, spec = archive_spec({"ollama.exe": b"test CLI", name: b"bad"})
    monkeypatch.setattr(runtime, "OLLAMA", spec)
    old = tmp_path / "ollama-fixture"
    old.mkdir()
    (old / "ollama.exe").write_bytes(b"old CLI")
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=data))
    ) as client:
        with pytest.raises(ValueError, match="Unsafe path"):
            runtime.install(client, tmp_path)
    assert (old / "ollama.exe").read_bytes() == b"old CLI"


@pytest.mark.parametrize("gpu_bytes", [1234, 0])
def test_gpu_check_samples_active_model_before_unload_and_keeps_failure_evidence(
    tmp_path, monkeypatch, gpu_bytes
):
    runner = make_runner(tmp_path)
    runner.models = [
        {"id": "model", "name": "local", "runtime_model": "local", "expected_digest": "a" * 64}
    ]
    monkeypatch.setattr(runner, "submit", lambda *a: (None, None, {"id": "run"}))
    states = iter(["running", "completed"])
    active = False

    def api(*args):
        nonlocal active
        status = next(states)
        active = status == "running"
        return {"status": status}

    def residency(request):
        return httpx.Response(
            200,
            json={
                "models": [
                    {"digest": "a" * 64, "size_vram": gpu_bytes},
                    {"digest": "b" * 64, "size_vram": 99999},
                ]
                if active
                else []
            },
        )

    monkeypatch.setattr(runner, "api", api)
    monkeypatch.setattr(main.time, "sleep", lambda _: None)
    runner.http.close()
    runner.http = httpx.Client(transport=httpx.MockTransport(residency))
    try:
        if gpu_bytes:
            assert runner.local_models()["models"][0]["gpu_resident_bytes"] == gpu_bytes
        else:
            with pytest.raises(AssertionError, match="No GPU residency"):
                runner.local_models()
        record = json.loads((runner.share / "local-model-inference.json").read_text())["models"][0]
        assert record["resident_samples"] == 1 and record["gpu_resident_bytes"] == gpu_bytes
        assert record["completed_through_dsgpt"]
    finally:
        runner.http.close()


@pytest.mark.parametrize("success", [False, True])
def test_model_pull_retries_same_model_and_requires_terminal_success(
    tmp_path, monkeypatch, success
):
    runner = make_runner(tmp_path)
    calls = []

    def serve(req):
        calls.append(json.loads(req.content)["model"])
        return httpx.Response(
            200,
            json={"status": "success"}
            if success and len(calls) == 2
            else {"error": "interrupted transfer"},
        )

    monkeypatch.setattr(main.time, "sleep", lambda _: None)
    with httpx.Client(transport=httpx.MockTransport(serve)) as runner.http:
        if success:
            runner.pull_local_model()
        else:
            with pytest.raises(RuntimeError, match="three attempts"):
                runner.pull_local_model()
    assert calls == ["qwen3:1.7b"] * (2 if success else 3)
