import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

spec = importlib.util.spec_from_file_location(
    "media_agent_runner", Path(__file__).parents[1] / "scripts/run_live_media_agent.py"
)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_owned_runtime_drops_inherited_model_settings():
    environment, controlled = runner.server_environment(
        {
            "PATH": "/usr/bin",
            "OLLAMA_HOST": "http://shared.example:11434",
            "OLLAMA_NUM_PARALLEL": "8",
            "LLAMA_ARG_CACHE_RAM": "2048",
            "LLAMA_UNREVIEWED_OPTION": "unexpected",
        },
        Path("/test/models"),
        12345,
    )
    assert environment["PATH"] == "/usr/bin"
    assert "LLAMA_UNREVIEWED_OPTION" not in environment
    assert controlled == {
        "OLLAMA_HOST": "127.0.0.1:12345",
        "OLLAMA_MODELS": "/test/models",
        "OLLAMA_NUM_PARALLEL": "1",
        "OLLAMA_MAX_LOADED_MODELS": "1",
        "OLLAMA_CONTEXT_LENGTH": "16384",
        "LLAMA_ARG_CTX_CHECKPOINTS": "2",
        "LLAMA_ARG_CACHE_RAM": "0",
        "GOMAXPROCS": "4",
    }


def test_owned_child_oom_priority_is_explicit_and_does_not_touch_parent(tmp_path):
    child_setting = tmp_path / "oom_score_adj"
    child_setting.write_text("0")
    evidence_read, evidence_write = runner.os.pipe()
    try:
        observed = runner.prefer_owned_oom_victim(child_setting, evidence_fd=evidence_write)
        assert observed == 1000
        assert runner.os.read(evidence_read, 16) == b"1000"
    finally:
        runner.os.close(evidence_read)
    assert child_setting.read_text() == "1000"


def test_dry_run_never_launches_server_or_harness(tmp_path, monkeypatch, capsys):
    dummy = tmp_path / "existing-runtime"
    dummy.touch()
    args = SimpleNamespace(
        runtime="ollama",
        model="original-model",
        speculative_mtp=False,
        probe_only=False,
        ollama=dummy,
        worker_python=dummy,
        sample_wav=dummy,
        models=tmp_path,
        output=tmp_path / "fresh-result",
        source_commit="frozen-source",
        max_seconds=7200,
        cases=["short", "long"],
        dry_run=True,
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("Dry run must not launch any process")

    monkeypatch.setattr(runner.subprocess, "Popen", forbidden)
    assert runner.main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["dry_run"]
    assert not report["server_started"]
    assert not report["harness_started"]
    assert report["owned_server_oom_score_adj_requested"] == 1000
    assert not args.output.exists()
    assert not args.output.with_name("fresh-result.runner").exists()
    assert report["harness_command"][-2:] == ["short", "long"]
    assert report["request_options"] == {"num_thread": 4, "num_batch": 64, "use_mmap": True}


def cgroup_fixture(folder):
    for name, value in {
        "memory.current": "3026038784\n",
        "memory.max": "8589934592\n",
        "memory.events": "low 0\nhigh 0\nmax 42\noom 3\noom_kill 2\noom_group_kill 0\n",
        "memory.stat": "anon 1024\nfile 2048\nshmem 512\nunknown_kernel_counter 9\n",
    }.items():
        (folder / name).write_text(value)


def test_resource_snapshot_parses_bounded_cgroup_counters_and_delta(tmp_path):
    cgroup_fixture(tmp_path)
    before = runner.resource_snapshot(tmp_path, tmp_path)
    assert before["complete"]
    assert before["memory_current_bytes"] == 3026038784
    assert before["memory_max_bytes"] == 8589934592
    assert before["memory_stat_bytes"] == {"anon": 1024, "file": 2048, "shmem": 512}
    assert before["disk_available_bytes"] >= 0
    (tmp_path / "memory.events").write_text("oom 4\noom_kill 3\noom_group_kill 0\n")
    (tmp_path / "memory.max").write_text("max\n")
    after = runner.resource_snapshot(tmp_path, tmp_path)
    assert after["memory_max_bytes"] == "max"
    assert runner.oom_counter_delta(before, after) == {"oom": 1, "oom_kill": 1, "oom_group_kill": 0}


def test_resource_snapshot_missing_or_oversized_is_unknown_not_zero(tmp_path):
    cgroup_fixture(tmp_path)
    (tmp_path / "memory.events").write_text("oom 3\n" + "x" * 16385)
    (tmp_path / "memory.current").unlink()
    snapshot = runner.resource_snapshot(tmp_path, tmp_path)
    assert not snapshot["complete"]
    assert snapshot["memory_current_bytes"] is None
    assert snapshot["memory_events"] is None
    assert snapshot["errors"] == {
        "memory.current": "FileNotFoundError",
        "memory.events": "ValueError",
    }
    assert all(value is None for value in runner.oom_counter_delta(snapshot, snapshot).values())
    assert (
        runner.oom_counter_delta(
            {"memory_events": {"oom_kill": 3}}, {"memory_events": {"oom_kill": 2}}
        )["oom_kill"]
        is None
    )


def test_mtp_is_default_off_and_only_uses_the_same_model_draft_head():
    args = SimpleNamespace(
        runtime="llama.cpp",
        llama_server=Path("server"),
        native_model=Path("native.gguf"),
        model="same-9b",
        chat_template_file=Path("official.jinja"),
        speculative_mtp=False,
    )
    baseline = runner.server_command(args, 12345)
    assert not any("spec" in option for option in baseline)
    args.speculative_mtp = True
    speculative = runner.server_command(args, 12345)
    assert speculative == baseline + ["--spec-type", "draft-mtp", "--spec-draft-n-max", "1"]
    assert "--spec-draft-model" not in speculative
    assert "--spec-synth" not in speculative
    assert speculative[speculative.index("--ctx-size") + 1] == "16384"
    assert speculative[speculative.index("--model") + 1] == "native.gguf"


@pytest.mark.parametrize("correct", [True, False])
def test_bounded_probe_checks_actual_answer_without_claiming_media_completion(
    tmp_path, monkeypatch, correct
):
    requests = []
    client_class = httpx.Client

    def handle(request):
        requests.append(json.loads(request.content))
        numbers = list(range(1, 25 if correct else 24))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps({"numbers": numbers})}}],
                "usage": {"completion_tokens": 60},
                "timings": {"predicted_ms": 120000},
            },
        )

    monkeypatch.setattr(
        runner.httpx,
        "Client",
        lambda **kwargs: client_class(**kwargs, transport=httpx.MockTransport(handle)),
    )
    result = runner.run_native_probe(
        SimpleNamespace(
            model="same-9b",
            output=tmp_path / "new-probe",
            speculative_mtp=True,
        ),
        "http://127.0.0.1:12345",
    )
    assert result["passed"] is correct
    assert result["media_acceptance"] is False
    assert result["usage"]["completion_tokens"] == 60
    assert len(requests) == 1
    assert requests[0]["max_tokens"] == 128
    assert requests[0]["temperature"] == 0
    assert requests[0]["chat_template_kwargs"] == {"enable_thinking": False}


@pytest.mark.parametrize("extra_newline", [False, True])
def test_live_template_check_detects_terminal_newline_difference(monkeypatch, extra_newline):
    client_class = httpx.Client
    expected = "assistant\n<think>\n\n</think>\n\n"
    template_audit = {
        "scope": "text fixture",
        "fixtures": [
            {
                "messages": [{"role": "user", "content": "hello"}],
                "rendered_prompt": expected,
                "rendered_prompt_sha256": runner.hashlib.sha256(expected.encode()).hexdigest(),
            }
        ],
    }
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, json={"prompt": expected + ("\n" if extra_newline else "")}
        )
    )
    monkeypatch.setattr(
        runner.httpx, "Client", lambda **kwargs: client_class(**kwargs, transport=transport)
    )
    result = runner.verify_runtime_template("http://127.0.0.1:12345", template_audit)
    assert result["passed"] is not extra_newline
