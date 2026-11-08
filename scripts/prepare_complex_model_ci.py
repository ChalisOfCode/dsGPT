"""Prepare a pinned, owned Ollama daemon for disposable Linux acceptance CI.

Preparation verifies downloads, model identity and a real cold-load inference.
That probe is not application/media acceptance. An optional command after -- runs
with its original argument vector.
Successful preparation leaves the owned daemon available to later job steps.
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
import tarfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import psutil

RUNTIME_VERSION = "0.40.13"
ARCHIVE_URL = (
    "https://github.com/ollama/ollama/releases/download/v0.40.13/ollama-linux-amd64.tar.zst"
)
ARCHIVE_SHA256 = "c9490e0f520be21271d969e6703f012268b1d39f8b70dd58854e5bfef7a75bb6"
ARCHIVE_BYTES = 1525346571
MODEL_TAG = "huihui_ai/qwen3.5-abliterated:9b"
MODEL_SHA256 = "92a443adb124f5e805bbdee23fdb38fcd22a7bf00a1016b53f764e741369c600"
MODEL_GGUF_SHA256 = "afb54ad43a39f947407f5cabc59856348d70e072baa5c62d436332157c151bcd"
MODEL_GGUF_BYTES = 6594462816
MAX_EXTRACTED_BYTES = 12 * 1024**3
MAX_ARCHIVE_MEMBERS = 100_000


def require_process_namespace(proc=Path("/proc")):
    """Refuse unsafe process ownership checks before spawning an inference daemon."""
    pid = os.getpid()
    try:
        require(os.readlink(proc / "self") == str(pid), "Procfs PID namespace mismatch")

        def identity(path):
            with path.open(encoding="ascii") as stream:
                raw = stream.read(4097)
            require(len(raw) <= 4096, "Procfs identity exceeded its bound")
            fields = raw[raw.rfind(")") + 2 :].split()
            return (int(raw.split(" (", 1)[0]), int(fields[2]), int(fields[3]), int(fields[19]))

        own = identity(proc / "self/stat")
        numeric = identity(proc / str(pid) / "stat")
        require(own == numeric and own[0] == pid, "Procfs self/numeric identity mismatch")
        require(
            own[1] == os.getpgrp() and own[2] == os.getsid(0),
            "Procfs process group/session mismatch",
        )
        descriptors = list((proc / str(pid) / "fd").iterdir())
        require(bool(descriptors), "Own process descriptors unavailable")
        os.readlink(descriptors[0])
        with (proc / "net/tcp").open(encoding="ascii") as stream:
            require("local_address" in stream.readline(4096), "TCP ownership metadata unavailable")
    except (OSError, ValueError, IndexError) as error:
        raise RuntimeError("Cannot verify owned processes in this PID namespace") from error
    return {"pid_namespace_verified": True}


def available_memory(proc=Path("/proc"), cgroup=Path("/sys/fs/cgroup")):
    """Account for every mounted v2 ancestor limit, not just host MemAvailable."""
    host = psutil.virtual_memory().available
    membership = (proc / "self/cgroup").read_text(encoding="ascii")
    matches = [line[3:] for line in membership.splitlines() if line.startswith("0::")]
    require(len(matches) == 1, "Cannot establish unified cgroup membership")
    relative = PurePosixPath(matches[0])
    require(relative.is_absolute() and ".." not in relative.parts, "Invalid cgroup membership")
    current = cgroup.joinpath(*relative.parts[1:])
    require(current.is_dir(), "Current cgroup is not visible in the mounted hierarchy")
    limits = []
    for group in (current, *current.parents):
        if not group.is_relative_to(cgroup):
            break
        limit_path = group / "memory.max"
        if not limit_path.exists():
            continue
        raw = limit_path.read_text(encoding="ascii").strip()
        used = int((group / "memory.current").read_text(encoding="ascii"))
        require(used >= 0, "Invalid cgroup memory usage")
        if raw != "max":
            maximum = int(raw)
            require(maximum > 0, "Invalid cgroup memory limit")
            limits.append(max(0, maximum - used))
    return {
        "host_available_bytes": host,
        "ancestor_available_bytes": limits,
        "effective_available_bytes": min([host, *limits]),
    }


def oom_snapshot(proc=Path("/proc"), cgroup=Path("/sys/fs/cgroup")):
    """Read every visible ancestor counter; missing evidence never means zero OOMs."""
    membership = (proc / "self/cgroup").read_text(encoding="ascii")
    paths = [line[3:] for line in membership.splitlines() if line.startswith("0::")]
    require(len(paths) == 1, "Cannot establish OOM counter hierarchy")
    relative = PurePosixPath(paths[0])
    require(relative.is_absolute() and ".." not in relative.parts, "Invalid OOM hierarchy")
    current = cgroup.joinpath(*relative.parts[1:])
    require(current.is_dir(), "OOM hierarchy is not visible")
    counters = {}
    for group in (current, *current.parents):
        if not group.is_relative_to(cgroup):
            break
        path = group / "memory.events"
        if path.exists():
            with path.open(encoding="ascii") as stream:
                raw = stream.read(4097)
            require(len(raw) <= 4096, "OOM counters exceeded bound")
            values = dict(line.split() for line in raw.splitlines())
            require({"oom", "oom_kill"} <= values.keys(), "Incomplete OOM counters")
            values = {key: int(values[key]) for key in ("oom", "oom_kill")}
            require(all(value >= 0 for value in values.values()), "Negative OOM counter")
            counters[str(group.relative_to(cgroup))] = values
    require(bool(counters), "No OOM counters available")
    return counters


def verify_no_oom(before, after):
    require(bool(before) and before.keys() == after.keys(), "OOM hierarchy changed or missing")
    for scope, counters in before.items():
        require(set(counters) == {"oom", "oom_kill"}, "Incomplete prior OOM counters")
        require(counters == after[scope], "OOM counters increased or reset during cold load")
    return {"verified": True, "counter_scopes": sorted(before), "increases": 0}


def require_memory(record, model_bytes, reserve_bytes=4 * 1024**3):
    require(isinstance(model_bytes, int) and model_bytes > 0, "Missing model byte size")
    needed = model_bytes + reserve_bytes
    require(
        record["effective_available_bytes"] >= needed,
        "Insufficient memory for the pinned model/context; no paid or smaller-model fallback",
    )
    return {
        "required_available_bytes": needed,
        "model_bytes": model_bytes,
        "reserve_bytes": reserve_bytes,
        "exact_peak_memory_verified": False,
    }


def cpu_member(name):
    path = PurePosixPath(name)
    if str(path) == "bin/ollama":
        return True
    return (
        len(path.parts) == 3
        and path.parts[:2] == ("lib", "ollama")
        and (
            path.name.startswith(
                ("libllama", "libggml-base", "libggml-cpu", "libggml.so", "libgomp.so", "libmtmd")
            )
            or path.name in {"llama-server", "llama-quantize"}
            or path.name.endswith(("_LICENSE", "_NOTICE"))
        )
    )


def now():
    return datetime.now(UTC).isoformat()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def persist(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + str(os.getpid()))
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def file_digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def open_release_download(request):
    """Retry only transient HTTP responses before any archive bytes are written."""
    for attempt in range(3):
        try:
            return urllib.request.urlopen(request, timeout=60)
        except urllib.error.HTTPError as error:
            if error.code not in {502, 503, 504} or attempt == 2:
                raise
            error.close()
            time.sleep(2 ** attempt)


def download_archive(path, timeout):
    started = time.monotonic()
    request = urllib.request.Request(ARCHIVE_URL, headers={"Accept-Encoding": "identity"})
    received = 0
    with open_release_download(request) as response, path.open("xb") as output:
        require(response.status == 200, "Runtime download did not return HTTP 200")
        require(response.geturl().startswith("https://"), "Runtime redirect was not HTTPS")
        declared = response.headers.get("Content-Length")
        if declared is not None:
            require(int(declared) == ARCHIVE_BYTES, "Runtime download size header differs from pin")
        while True:
            require(time.monotonic() - started < timeout, "Runtime download timed out")
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            received += len(chunk)
            require(received <= ARCHIVE_BYTES, "Runtime download exceeds pinned size")
            output.write(chunk)
        output.flush()
        os.fsync(output.fileno())
        final_url = response.geturl()
    require(
        received == ARCHIVE_BYTES and path.stat().st_size == ARCHIVE_BYTES,
        "Runtime download has the wrong size",
    )
    digest = file_digest(path)
    require(digest == ARCHIVE_SHA256, "Runtime download SHA256 differs from pin")
    return {
        "url": ARCHIVE_URL,
        "final_url": final_url,
        "bytes": received,
        "sha256": digest,
        "verified_before_extraction": True,
    }


def archive_target(root, name):
    require(
        isinstance(name, str) and "\x00" not in name and "\\" not in name, "Invalid archive path"
    )
    relative = PurePosixPath(name)
    require(
        not relative.is_absolute() and ".." not in relative.parts,
        "Archive path escapes the owned runtime directory",
    )
    target = root.joinpath(*relative.parts)
    require(target.resolve().is_relative_to(root), "Archive parent link escapes runtime directory")
    return target


def extract_archive(archive, root, log, timeout, *, cpu_only=False):
    """Extract only verified tar content, validating paths, links, types and limits."""
    require(file_digest(archive) == ARCHIVE_SHA256, "Archive changed before extraction")
    zstd = shutil.which("zstd")
    require(zstd is not None, "Prepared Linux CI must provide the zstd executable")
    root.mkdir(mode=0o700)
    root = root.resolve()
    total, members = 0, 0
    hardlinks = []
    started = time.monotonic()
    with log.open("wb") as errors:
        decompressor = subprocess.Popen(
            [zstd, "-d", "-c", "--", str(archive)],
            stdout=subprocess.PIPE,
            stderr=errors,
            stdin=subprocess.DEVNULL,
        )
        try:
            with tarfile.open(fileobj=decompressor.stdout, mode="r|") as source:
                for member in source:
                    require(time.monotonic() - started < timeout, "Runtime extraction timed out")
                    members += 1
                    require(members <= MAX_ARCHIVE_MEMBERS, "Runtime archive has too many members")
                    target = archive_target(root, member.name)
                    if cpu_only and not member.isdir() and not cpu_member(member.name):
                        continue
                    if target == root:
                        require(member.isdir(), "Invalid archive root member")
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    require(target.parent.resolve().is_relative_to(root), "Unsafe archive parent")
                    if member.isdir():
                        require(not target.is_symlink(), "Archive directory is a link")
                        target.mkdir(mode=0o755, exist_ok=True)
                    elif member.isreg():
                        total += member.size
                        require(
                            0 <= member.size
                            and total <= (256 * 1024**2 if cpu_only else MAX_EXTRACTED_BYTES),
                            "Runtime extraction exceeds its byte limit",
                        )
                        require(
                            not target.exists() and not target.is_symlink(),
                            "Duplicate runtime archive file",
                        )
                        extracted = source.extractfile(member)
                        require(extracted is not None, "Archive file contents are missing")
                        with extracted, target.open("xb") as output:
                            remaining = member.size
                            while remaining:
                                require(
                                    time.monotonic() - started < timeout,
                                    "Runtime extraction timed out",
                                )
                                chunk = extracted.read(min(1024 * 1024, remaining))
                                require(bool(chunk), "Truncated archive file")
                                output.write(chunk)
                                remaining -= len(chunk)
                        target.chmod(0o755 if member.mode & 0o111 else 0o644)
                    elif member.issym():
                        link = PurePosixPath(member.linkname)
                        require(
                            not link.is_absolute()
                            and "\\" not in member.linkname
                            and "\x00" not in member.linkname,
                            "Invalid runtime symlink",
                        )
                        require(
                            (target.parent / member.linkname).resolve().is_relative_to(root),
                            "Runtime symlink escapes owned directory",
                        )
                        require(
                            not target.exists() and not target.is_symlink(),
                            "Duplicate runtime symlink",
                        )
                        target.symlink_to(member.linkname)
                    elif member.islnk():
                        linked = archive_target(root, member.linkname)
                        hardlinks.append((target, linked))
                    else:
                        raise RuntimeError("Runtime archive contains an unsupported special file")
            # Drain tar padding so zstd can validate its complete frame and exit.
            while decompressor.stdout.read(1024 * 1024):
                require(time.monotonic() - started < timeout, "Runtime extraction timed out")
            require(decompressor.wait(timeout=30) == 0, "Runtime zstd decompression failed")
            for target, linked in hardlinks:
                require(
                    linked.resolve().is_relative_to(root)
                    and linked.is_file()
                    and not linked.is_symlink(),
                    "Unsafe or missing runtime hardlink target",
                )
                require(target.parent.resolve().is_relative_to(root), "Unsafe hardlink parent")
                require(not target.exists() and not target.is_symlink(), "Duplicate hardlink")
                os.link(linked, target)
        finally:
            if decompressor.stdout is not None:
                decompressor.stdout.close()
            if decompressor.poll() is None:
                decompressor.kill()
                decompressor.wait(timeout=10)
    return {
        "regular_file_bytes": total,
        "members": members,
        "path_and_link_checks": True,
        "cpu_only": cpu_only,
    }


def process_start_ticks(pid):
    # The executable name in /proc/stat may contain spaces; fields after ')' are fixed.
    return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]


def owns_listener(pid, port):
    expected = "0100007F:" + format(port, "04X")
    inodes = set()
    for line in Path("/proc/net/tcp").read_text().splitlines()[1:]:
        fields = line.split()
        if fields[1] == expected and fields[3] == "0A":
            inodes.add(fields[9])
    if not inodes:
        return False
    for descriptor in Path(f"/proc/{pid}/fd").iterdir():
        try:
            linked = os.readlink(descriptor)
        except FileNotFoundError:
            continue
        if linked in {"socket:[" + inode + "]" for inode in inodes}:
            return True
    return False


def api(origin, path, timeout, body=None):
    request = urllib.request.Request(
        origin + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    # Loopback traffic must never be routed through an environment proxy.
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
        request, timeout=timeout
    ) as response:
        data = response.read(4 * 1024 * 1024 + 1)
        require(len(data) <= 4 * 1024 * 1024, "Ollama metadata response exceeds limit")
        return json.loads(data)


def wait_ready(process, origin, port, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        require(process.poll() is None, "Owned Ollama daemon exited before readiness")
        if owns_listener(process.pid, port):
            try:
                version = api(origin, "/api/version", 3)
                require(
                    version.get("version") == RUNTIME_VERSION, "Ollama API version differs from pin"
                )
                return version
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
                pass
        time.sleep(0.25)
    raise RuntimeError("Owned Ollama daemon did not become ready before timeout")


def stop_owned_daemon(process, identity):
    if process is None or process.poll() is not None:
        return
    if identity is None:
        # A Popen child exists but identity recording failed. Only stop that child;
        # do not signal a guessed process group or a PID loaded from a file.
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
        return
    require(
        process_start_ticks(process.pid) == identity["start_ticks"]
        and os.getpgid(process.pid) == process.pid,
        "Daemon identity changed; refusing to signal an unverified process",
    )
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True, help="New owned runtime directory")
    parser.add_argument("--output", type=Path, required=True, help="Provenance/failure JSON report")
    parser.add_argument("--port", type=int, default=11435)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--readiness-timeout", type=int, default=120)
    parser.add_argument("--download-timeout", type=int, default=1800)
    parser.add_argument("--pull-timeout", type=int, default=1800)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    args.directory, args.output = args.directory.resolve(), args.output.resolve()
    origin = "http://127.0.0.1:" + str(args.port)
    report = {
        "status": "preparing",
        "passed": False,
        "started_at": now(),
        "endpoint": origin,
        "runtime_version_expected": RUNTIME_VERSION,
        "archive_pin": {"url": ARCHIVE_URL, "sha256": ARCHIVE_SHA256, "bytes": ARCHIVE_BYTES},
        "model_pin": {"tag": MODEL_TAG, "sha256": MODEL_SHA256},
        "actual_model_inference_by_preparer": False,
        "harness_arguments_modified": False,
    }
    process, identity, owned = None, None, False
    exit_code = 1
    try:
        require(sys.platform.startswith("linux"), "This helper requires disposable Linux CI")
        report["ownership_prerequisite"] = require_process_namespace()
        require(1 <= args.port <= 65535 and 1 <= args.threads <= 64, "Invalid port or thread count")
        require(
            min(args.readiness_timeout, args.download_timeout, args.pull_timeout) > 0,
            "Timeouts must be positive",
        )
        args.directory.mkdir(parents=True, mode=0o700, exist_ok=False)
        owned = True
        persist(args.output, report)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reserved:
            reserved.bind(("127.0.0.1", args.port))
        require(shutil.which("zstd") is not None, "Prepared Linux CI must provide zstd")
        archive = args.directory / "ollama-linux-amd64.tar.zst"
        report["archive"] = download_archive(archive, args.download_timeout)
        report["stage"] = "verified_runtime_extraction"
        persist(args.output, report)
        report["extraction"] = extract_archive(
            archive,
            args.directory / "runtime",
            args.directory / "extraction.log",
            900,
            cpu_only=True,
        )
        archive.unlink()
        report["verified_archive_removed"] = True
        binary = args.directory / "runtime/bin/ollama"
        require(
            binary.is_file() and binary.resolve().is_relative_to(args.directory / "runtime"),
            "Verified runtime is missing its owned Ollama executable",
        )
        report["binary_sha256"] = file_digest(binary)
        settings = {
            "OLLAMA_HOST": "127.0.0.1:" + str(args.port),
            "OLLAMA_MODELS": str(args.directory / "models"),
            "OLLAMA_NUM_PARALLEL": "1",
            "OLLAMA_MAX_LOADED_MODELS": "1",
            "LLAMA_ARG_CTX_CHECKPOINTS": "2",
            "LLAMA_ARG_CACHE_RAM": "0",
            "OMP_NUM_THREADS": str(args.threads),
            "OPENBLAS_NUM_THREADS": str(args.threads),
        }
        report["server_environment"] = settings
        report["thread_settings"] = {
            "requested_threads": args.threads,
            "scope": (
                "Daemon OpenMP/BLAS hints; inference num_thread remains "
                "the harness request's setting"
            ),
        }
        environment = {**os.environ, **settings}
        with (args.directory / "ollama.log").open("ab", buffering=0) as log:
            process = subprocess.Popen(
                [str(binary), "serve"],
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        identity = {
            "pid": process.pid,
            "start_ticks": process_start_ticks(process.pid),
            "binary": str(binary),
            "binary_sha256": report["binary_sha256"],
            "endpoint": origin,
            "created_at": now(),
            "owner": "prepare_complex_model_ci",
        }
        persist(args.directory / "ollama.pid.json", identity)
        report["daemon"] = identity
        report["runtime_version"] = wait_ready(process, origin, args.port, args.readiness_timeout)
        report["stage"] = "pulling_pinned_model"
        persist(args.output, report)
        pulled = api(origin, "/api/pull", args.pull_timeout, {"model": MODEL_TAG, "stream": False})
        require(pulled.get("status") == "success", "Ollama model pull did not report success")
        require(
            process.poll() is None and owns_listener(process.pid, args.port),
            "Owned daemon listener was lost during model preparation",
        )
        matches = [
            model
            for model in api(origin, "/api/tags", 30).get("models", [])
            if model.get("name") == MODEL_TAG
        ]
        require(len(matches) == 1, "Pulled model tag is missing or ambiguous")
        model = matches[0]
        report["observed_model"] = {key: model.get(key) for key in ("name", "digest", "size")}
        require(
            str(model.get("digest", "")).removeprefix("sha256:") == MODEL_SHA256,
            "Pulled model digest differs from the pinned acceptance model",
        )
        report["model"] = {key: model.get(key) for key in ("name", "digest", "size", "details")}
        weights = args.directory / "models/blobs" / ("sha256-" + MODEL_GGUF_SHA256)
        require(weights.is_file() and not weights.is_symlink(), "Pinned model weights missing")
        require(weights.stat().st_size == MODEL_GGUF_BYTES, "Pinned model weight size differs")
        require(file_digest(weights) == MODEL_GGUF_SHA256, "Pinned model weight bytes differ")
        report["weight_identity"] = {"sha256": MODEL_GGUF_SHA256, "bytes": MODEL_GGUF_BYTES}
        report["resources"] = available_memory()
        report["memory_admission"] = require_memory(report["resources"], model.get("size"))
        report["stage"] = "cold_load_preflight"
        report["oom_before"] = oom_snapshot()
        report["actual_model_inference_by_preparer"] = True
        persist(args.output, report)
        probe = api(
            origin,
            "/api/generate",
            600,
            {
                "model": MODEL_TAG,
                "prompt": "Reply with OK only.",
                "stream": False,
                "think": False,
                "keep_alive": 0,
                "options": {
                    "num_ctx": 16384,
                    "num_predict": 64,
                    "num_thread": args.threads,
                    "num_batch": 64,
                    "temperature": 0,
                },
            },
        )
        require(
            probe.get("done") is True
            and probe.get("model") == MODEL_TAG
            and probe.get("response", "").strip() == "OK",
            "Cold-load inference did not return the expected answer from the pinned model",
        )
        deadline = time.monotonic() + 30
        while api(origin, "/api/ps", 10).get("models") and time.monotonic() < deadline:
            time.sleep(0.25)
        require(
            not api(origin, "/api/ps", 10).get("models"),
            "Preflight model did not unload before toolchain compilation",
        )
        report["oom_after"] = oom_snapshot()
        report["oom_check"] = verify_no_oom(report["oom_before"], report["oom_after"])
        report["cold_load_preflight"] = {
            "passed": True,
            "unloaded": True,
            "context": 16384,
            "eval_count": probe.get("eval_count"),
            "load_duration": probe.get("load_duration"),
            "scope": "Runtime cold load only; does not establish application/media acceptance",
        }
        report["stage"] = "ready"
        persist(args.output, report)
        if command:
            started = time.monotonic()
            result = subprocess.run(command, check=False)
            report["harness"] = {
                "argv": command,
                "returncode": result.returncode,
                "seconds": round(time.monotonic() - started, 3),
            }
            require(result.returncode == 0, "Unmodified acceptance harness command failed")
        report.update(status="completed", passed=True, daemon_left_running=True)
        exit_code = 0
    except BaseException as exc:
        report.update(status="failed", error=type(exc).__name__ + ": " + str(exc))
        if isinstance(exc, KeyboardInterrupt):
            exit_code = 130
        try:
            stop_owned_daemon(process, identity)
            report["owned_daemon_stopped_on_failure"] = process is not None
        except Exception as cleanup:
            report["cleanup_error"] = type(cleanup).__name__ + ": " + str(cleanup)
        # Never remove an existing directory or signal a process found in somebody else's PID file.
        report["created_owned_directory"] = owned
        if owned:
            archive = args.directory / "ollama-linux-amd64.tar.zst"
            try:
                if archive.is_file() and not archive.is_symlink():
                    archive.unlink()
                    report["download_archive_removed_after_failure"] = True
            except OSError as cleanup:
                report["archive_cleanup_error"] = str(cleanup)
    finally:
        report["finished_at"] = now()
        try:
            persist(args.output, report)
        except OSError as error:
            # A full disk must not turn an unsuccessful preparation into a silent pass.
            exit_code = 1
            report.update(passed=False, status="failed", report_write_error=str(error))
            try:
                stop_owned_daemon(process, identity)
                report["daemon_left_running"] = False
            except Exception as cleanup:
                report["cleanup_error"] = type(cleanup).__name__ + ": " + str(cleanup)
            print(json.dumps(report), file=sys.stderr)
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "endpoint": origin,
                "report": str(args.output),
                "error": report.get("error"),
            }
        )
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
