"""Own one temporary local inference server and run fresh media-agent acceptance.

This runner never installs or pulls a model. --dry-run prints the intended command
and controlled settings without starting either the server or the model harness.
Server and harness logs live beside the fresh acceptance directory in .runner/.
"""

import argparse
import hashlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

import httpx

CGROUP_EVENTS = ("low", "high", "max", "oom", "oom_kill", "oom_group_kill")
CGROUP_STAT = (
    "anon",
    "file",
    "shmem",
    "kernel",
    "kernel_stack",
    "pagetables",
    "file_mapped",
    "file_dirty",
    "file_writeback",
    "slab",
)
OWNED_OOM_SCORE_ADJ = 1000


def prefer_owned_oom_victim(path=Path("/proc/self/oom_score_adj"), *, evidence_fd=None):
    """Runs in the owned child before exec; Linux runners inherit this priority."""
    path.write_text(str(OWNED_OOM_SCORE_ADJ), encoding="ascii")
    observed = int(path.read_text(encoding="ascii").strip())
    if observed != OWNED_OOM_SCORE_ADJ:
        raise RuntimeError("Owned child OOM priority protection was not applied")
    if evidence_fd is not None:
        os.write(evidence_fd, str(observed).encode("ascii"))
        os.close(evidence_fd)
    return observed


def resource_snapshot(disk_path, cgroup=Path("/sys/fs/cgroup")):
    """Bounded, aggregate resource evidence; no unrelated process information."""
    errors = {}

    def read(name, fields=None, unlimited=False):
        try:
            with (cgroup / name).open(encoding="ascii") as source:
                value = source.read(16385)
            if len(value) > 16384:
                raise ValueError("Cgroup file exceeds bounded read")
            if fields is None:
                if unlimited and value.strip() == "max":
                    return "max"
                number = int(value.strip())
                if number < 0:
                    raise ValueError("Negative cgroup value")
                return number
            selected = {}
            for line in value.splitlines():
                parts = line.split()
                if len(parts) != 2:
                    raise ValueError("Malformed cgroup counter")
                if parts[0] in fields:
                    number = int(parts[1])
                    if number < 0 or parts[0] in selected:
                        raise ValueError("Invalid cgroup counter")
                    selected[parts[0]] = number
            if not selected:
                raise ValueError("No selected cgroup counters")
            if fields is CGROUP_EVENTS and any(key not in selected for key in ("oom", "oom_kill")):
                raise ValueError("Missing OOM counters")
            return selected
        except (OSError, ValueError) as exc:
            errors[name] = type(exc).__name__
            return None

    result = {
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "memory_current_bytes": read("memory.current"),
        "memory_max_bytes": read("memory.max", unlimited=True),
        "memory_events": read("memory.events", fields=CGROUP_EVENTS),
        "memory_stat_bytes": read("memory.stat", fields=CGROUP_STAT),
        "disk_available_bytes": None,
    }
    try:
        result["disk_available_bytes"] = shutil.disk_usage(disk_path).free
    except OSError as exc:
        errors["disk_available_bytes"] = type(exc).__name__
    result.update(complete=not errors, errors=errors)
    return result


def oom_counter_delta(before, after):
    """Unknown/reset counters remain null; they must never look like zero OOMs."""
    first = before.get("memory_events") or {}
    last = after.get("memory_events") or {}
    return {
        key: last[key] - first[key]
        if key in first and key in last and last[key] >= first[key]
        else None
        for key in ("oom", "oom_kill", "oom_group_kill")
    }


def free_loopback_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def server_environment(inherited, models, port, runtime="ollama"):
    clean = {
        key: value for key, value in inherited.items() if not key.startswith(("OLLAMA_", "LLAMA_"))
    }
    controlled = {
        "LLAMA_ARG_CTX_CHECKPOINTS": "2",
        "LLAMA_ARG_CACHE_RAM": "0",
        "GOMAXPROCS": "4",
    }
    if runtime == "ollama":
        controlled.update(
            OLLAMA_HOST=f"127.0.0.1:{port}",
            OLLAMA_MODELS=str(models),
            OLLAMA_NUM_PARALLEL="1",
            OLLAMA_MAX_LOADED_MODELS="1",
            OLLAMA_CONTEXT_LENGTH="16384",
        )
    clean.update(controlled)
    return clean, controlled


def stop_owned_process(process):
    """Signal only a process group created by this wrapper, never a shared server."""
    if process is None or process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait(timeout=15)
    except ProcessLookupError:
        process.wait(timeout=15)


def harness_command(args, endpoint):
    command = [
        sys.executable,
        "-I",
        str(Path(__file__).with_name("live_media_agent.py")),
        "--sample-wav",
        str(args.sample_wav),
        "--output",
        str(args.output),
        "--source-commit",
        args.source_commit,
        "--runtime",
        args.runtime,
        "--model",
        args.model,
        "--execution",
        "reviewed-local",
        "--worker-python",
        str(args.worker_python),
        "--endpoint",
        endpoint,
        "--context",
        "16384",
        "--threads",
        "4",
        "--output-tokens",
        "2048",
        "--max-steps",
        "30",
        "--max-seconds",
        str(args.max_seconds),
        "--cases",
        *args.cases,
    ]
    if args.runtime == "llama.cpp":
        command.extend(
            [
                "--native-model",
                str(args.native_model),
                "--conversion-audit",
                str(args.conversion_audit),
                "--original-gguf-sha256",
                args.original_gguf_sha256,
                "--original-model-tag",
                args.original_model_tag,
            ]
        )
    return command


def server_command(args, port):
    if args.runtime == "ollama":
        return [str(args.ollama), "serve"]
    command = [
        str(args.llama_server),
        "--model",
        str(args.native_model),
        "--alias",
        args.model,
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--ctx-size",
        "16384",
        "--parallel",
        "1",
        "--threads",
        "4",
        "--threads-batch",
        "4",
        "--gpu-layers",
        "0",
        "--batch-size",
        "64",
        "--ubatch-size",
        "64",
        "--no-repack",
        "--load-mode",
        "mmap",
        "--offline",
        "--no-webui",
        "--jinja",
        "--chat-template-file",
        str(args.chat_template_file),
        "--context-shift",
        "--keep",
        "4",
        "--temp",
        "1",
        "--top-k",
        "20",
        "--top-p",
        "0.95",
    ]
    if args.speculative_mtp:
        command.extend(["--spec-type", "draft-mtp", "--spec-draft-n-max", "1"])
    return command


def verify_runtime_template(endpoint, template_audit):
    """Read-only rendering checks inside the owned server's network namespace."""
    results = []
    with httpx.Client(base_url=endpoint, trust_env=False, timeout=10) as client:
        for index, fixture in enumerate(template_audit["fixtures"]):
            response = client.post(
                "/apply-template",
                json={
                    "messages": fixture["messages"],
                    "add_generation_prompt": True,
                    "chat_template_kwargs": {"enable_thinking": False},
                },
            )
            response.raise_for_status()
            actual = response.json()["prompt"]
            matches = actual == fixture["rendered_prompt"]
            results.append(
                {
                    "fixture": index,
                    "passed": matches,
                    "actual_sha256": hashlib.sha256(actual.encode()).hexdigest(),
                    "expected_sha256": fixture["rendered_prompt_sha256"],
                }
            )
    return {
        "passed": bool(results) and all(item["passed"] for item in results),
        "scope": template_audit["scope"],
        "fixtures": results,
    }


def run_native_probe(args, endpoint):
    """Small performance/grammar probe, never a media completion or task rescue."""
    prompt = (
        "Return a JSON object with a single field, numbers, containing every integer "
        "from 1 through 24 in ascending order."
    )
    request = {
        "model": args.model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 128,
        "temperature": 0,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "bounded_numbers_probe",
                "strict": True,
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["numbers"],
                    "properties": {
                        "numbers": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "minItems": 24,
                            "maxItems": 24,
                        }
                    },
                },
            },
        },
    }
    report = {
        "passed": False,
        "model_driven": True,
        "media_acceptance": False,
        "request": request,
        "speculative_mtp": args.speculative_mtp,
    }
    args.output.mkdir()
    output = args.output / "probe.json"
    output.write_text(json.dumps(report, indent=2) + "\n")
    started = time.monotonic()
    try:
        with httpx.Client(base_url=endpoint, trust_env=False, timeout=600) as client:
            response = client.post("/v1/chat/completions", json=request)
            response.raise_for_status()
            body = response.json()
        content = body["choices"][0]["message"]["content"]
        report.update(
            visible_response=content, usage=body.get("usage"), runtime_timings=body.get("timings")
        )
        report["passed"] = json.loads(content) == {"numbers": list(range(1, 25))}
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)[:300]}
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    output.write_text(json.dumps(report, indent=2) + "\n")
    return report


def wait_ready(server, endpoint, runtime="ollama", model=None):
    deadline = time.monotonic() + (180 if runtime == "llama.cpp" else 60)
    with httpx.Client(base_url=endpoint, trust_env=False, timeout=2) as client:
        while time.monotonic() < deadline:
            if server.poll() is not None:
                raise RuntimeError("Owned inference server exited before becoming ready")
            try:
                response = client.get("/health" if runtime == "llama.cpp" else "/api/version")
                response.raise_for_status()
                version = response.json()
                if server.poll() is None:
                    if runtime == "llama.cpp":
                        models = client.get("/v1/models")
                        models.raise_for_status()
                        props = client.get("/props")
                        props.raise_for_status()
                        if model not in {item["id"] for item in models.json().get("data", [])}:
                            raise RuntimeError("Owned native server is not serving the exact alias")
                        if (
                            props.json().get("default_generation_settings", {}).get("n_ctx")
                            != 16384
                        ):
                            raise RuntimeError("Owned native server is not serving context 16384")
                        return {"health": version, "models": models.json(), "props": props.json()}
                    return version
            except (httpx.HTTPError, ValueError):
                pass
            time.sleep(0.25)
    raise TimeoutError("Owned inference server did not become ready within its startup limit")


def main(args):
    for name in (
        "ollama",
        "models",
        "llama_server",
        "native_model",
        "conversion_audit",
        "chat_template_file",
        "template_audit",
        "sample_wav",
        "worker_python",
        "output",
    ):
        if getattr(args, name, None) is not None:
            setattr(args, name, getattr(args, name).absolute())
    if args.output.exists():
        raise ValueError("Acceptance output must be new; existing tasks are never resumed")
    runner = args.output.with_name(args.output.name + ".runner")
    if runner.exists():
        raise ValueError("Runner evidence directory already exists; choose a fresh output")
    needed = [args.sample_wav, args.worker_python]
    if args.runtime == "ollama":
        if not args.models or not args.models.is_dir():
            raise ValueError("Provide the existing Ollama model store")
        needed.append(args.ollama)
    else:
        needed.extend(
            [args.llama_server, args.native_model, args.conversion_audit, args.chat_template_file]
        )
    if any(not path or not path.is_file() for path in needed):
        raise ValueError("Provide the existing runtime, model/audit, sample and worker Python")
    if args.max_seconds < 1:
        raise ValueError("Maximum case duration must be positive")
    if (args.speculative_mtp or args.probe_only) and args.runtime != "llama.cpp":
        raise ValueError(
            "The MTP experiment and bounded probe require the native llama.cpp runtime"
        )
    port = free_loopback_port()
    endpoint = f"http://127.0.0.1:{port}"
    environment, controlled = server_environment(os.environ, args.models, port, args.runtime)
    command = harness_command(args, endpoint)
    report = {
        "source_commit": args.source_commit,
        "endpoint": endpoint,
        "server_command": server_command(args, port),
        "inference_backend": args.runtime,
        "speculative_mtp": args.speculative_mtp,
        "speculative_draft_max": 1 if args.speculative_mtp else None,
        "probe_only": args.probe_only,
        "server_environment": controlled,
        "harness_command": command,
        "request_options": {"num_thread": 4, "num_batch": 64, "use_mmap": True},
        "dry_run": args.dry_run,
        "server_started": False,
        "harness_started": False,
        "owned_server_oom_score_adj_requested": OWNED_OOM_SCORE_ADJ,
        "oom_priority_verification": "Owned child /proc/self readback through a private pipe",
        "execution_boundary": "reviewed-local; not Docker isolation evidence",
    }
    if args.dry_run:
        print(json.dumps(report, indent=2))
        return 0
    if not sys.platform.startswith("linux"):
        raise ValueError("This owned runner requires Linux OOM priority protection")
    if args.runtime == "llama.cpp":
        if not args.template_audit or not args.template_audit.is_file():
            raise ValueError("Native acceptance requires the matching template audit")
        template_audit = json.loads(args.template_audit.read_bytes())
        if (
            template_audit.get("passed") is not True
            or template_audit.get("template_sha256")
            != hashlib.sha256(args.chat_template_file.read_bytes()).hexdigest()
        ):
            raise ValueError("The native chat template does not match its passing audit")
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
        ):
            raise ValueError("Native file must match the passing independent conversion audit")
        report["native_copy"] = {
            "sha256": native_sha,
            "audit_sha256": hashlib.sha256(audit_bytes).hexdigest(),
            "original_model_tag": args.original_model_tag,
            "source_gguf_sha256": args.original_gguf_sha256,
            "scope": "Native text-only same active weights; not Ollama-environment evidence",
        }
        report["chat_template"] = {
            "path": str(args.chat_template_file),
            "sha256": hashlib.sha256(args.chat_template_file.read_bytes()).hexdigest(),
        }
    runner.mkdir(parents=True)
    server = harness = None
    result = 1
    started = time.monotonic()
    try:
        with (runner / "server.log").open("xb") as server_log:
            report["resources_before_launch"] = resource_snapshot(runner)
            (runner / "runner.json").write_text(json.dumps(report, indent=2) + "\n")
            score_read, score_write = os.pipe()
            try:
                try:
                    server = subprocess.Popen(
                        report["server_command"],
                        stdin=subprocess.DEVNULL,
                        stdout=server_log,
                        stderr=subprocess.STDOUT,
                        env=environment,
                        start_new_session=os.name == "posix",
                        preexec_fn=partial(prefer_owned_oom_victim, evidence_fd=score_write),
                        pass_fds=(score_write,),
                    )
                finally:
                    os.close(score_write)
                report["owned_server_oom_score_adj_observed"] = int(
                    os.read(score_read, 16).decode("ascii")
                )
            finally:
                os.close(score_read)
            report.update(server_started=True, server_pid=server.pid)
            if report["owned_server_oom_score_adj_observed"] != OWNED_OOM_SCORE_ADJ:
                raise RuntimeError("Owned inference server OOM priority protection was not applied")
            report["runtime_version"] = wait_ready(server, endpoint, args.runtime, args.model)
            if args.runtime == "llama.cpp":
                report["runtime_template_audit"] = verify_runtime_template(endpoint, template_audit)
                if not report["runtime_template_audit"]["passed"]:
                    raise RuntimeError("Live native template does not match the reviewed renderer")
            print(
                f"Owned {args.runtime} server ready at {endpoint}; "
                + ("starting bounded probe" if args.probe_only else "starting fresh acceptance"),
                flush=True,
            )
            if args.probe_only:
                report["probe"] = run_native_probe(args, endpoint)
                result = 0 if report["probe"]["passed"] else 1
            else:
                with (runner / "harness.log").open("xb") as harness_log:
                    harness = subprocess.Popen(
                        command,
                        stdin=subprocess.DEVNULL,
                        stdout=harness_log,
                        stderr=subprocess.STDOUT,
                        start_new_session=os.name == "posix",
                    )
                    report.update(harness_started=True, harness_pid=harness.pid)
                    (runner / "runner.json").write_text(json.dumps(report, indent=2) + "\n")
                    result = harness.wait(timeout=args.max_seconds * len(args.cases) + 180)
                    report["harness_exit_code"] = result
    except (Exception, KeyboardInterrupt) as exc:
        result = 1
        report["wrapper_error"] = {"type": type(exc).__name__, "message": str(exc)[:300]}
    finally:
        try:
            stop_owned_process(harness)
        finally:
            stop_owned_process(server)
        report["resources_after_cleanup"] = resource_snapshot(runner)
        report["oom_counter_delta"] = oom_counter_delta(
            report.get("resources_before_launch", {}), report["resources_after_cleanup"]
        )
        log_path = runner / "server.log"
        log_lines = log_path.read_text(errors="replace").splitlines() if log_path.exists() else []
        report["speculative_metric_log_lines"] = [
            line for line in log_lines if "draft acceptance" in line
        ][-16:]
        report.update(
            elapsed_seconds=round(time.monotonic() - started, 3),
            server_stopped=server is not None and server.poll() is not None,
            harness_stopped=harness is not None and harness.poll() is not None,
        )
        if args.probe_only:
            report["probe_resource_check_passed"] = (
                report.get("resources_before_launch", {}).get("complete") is True
                and report["resources_after_cleanup"]["complete"] is True
                and all(value == 0 for value in report["oom_counter_delta"].values())
                and report["server_stopped"]
            )
            report["bounded_probe_passed"] = (
                report.get("probe", {}).get("passed") is True
                and report["probe_resource_check_passed"]
            )
            result = 0 if report["bounded_probe_passed"] else 1
        (runner / "runner.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)
    return result


def interrupted(signum, frame):
    raise KeyboardInterrupt(f"Received signal {signum}; cleaning up owned processes")


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ollama", type=Path)
    parser.add_argument("--models", type=Path)
    parser.add_argument("--runtime", choices=["ollama", "llama.cpp"], default="ollama")
    parser.add_argument("--model", default="huihui_ai/qwen3.5-abliterated:9b")
    parser.add_argument("--llama-server", type=Path)
    parser.add_argument("--native-model", type=Path)
    parser.add_argument("--conversion-audit", type=Path)
    parser.add_argument("--chat-template-file", type=Path)
    parser.add_argument("--template-audit", type=Path)
    parser.add_argument("--speculative-mtp", action="store_true")
    parser.add_argument("--probe-only", action="store_true")
    parser.add_argument("--original-gguf-sha256")
    parser.add_argument("--original-model-tag", default="huihui_ai/qwen3.5-abliterated:9b")
    parser.add_argument("--sample-wav", type=Path, required=True)
    parser.add_argument("--worker-python", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument(
        "--cases", nargs="+", choices=["short", "medium", "long"], default=["short", "long"]
    )
    parser.add_argument("--max-seconds", type=int, default=7200)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, interrupted)
    raise SystemExit(main(arguments()))
