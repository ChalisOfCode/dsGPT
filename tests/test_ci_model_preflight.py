"""Resource/ownership regressions; these fixtures are not real-model acceptance."""

import hashlib
import importlib.util
import io
import os
import subprocess
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    "ci_model_preflight",
    Path(__file__).resolve().parents[1] / "scripts/prepare_complex_model_ci.py",
)
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


def test_memory_admission_uses_the_most_restrictive_cgroup_ancestor(tmp_path, monkeypatch):
    proc, groups = tmp_path / "proc", tmp_path / "cgroup"
    (proc / "self").mkdir(parents=True)
    (proc / "self/cgroup").write_text("0::/child/inner\n")
    for name, limit, used in [
        ("", "8000", 2000),
        ("child", "max", 1000),
        ("child/inner", "12000", 1000),
    ]:
        p = groups / name
        p.mkdir(parents=True, exist_ok=True)
        (p / "memory.max").write_text(limit)
        (p / "memory.current").write_text(str(used))
    monkeypatch.setattr(ci.psutil, "virtual_memory", lambda: SimpleNamespace(available=20000))
    record = ci.available_memory(proc, groups)
    assert record["effective_available_bytes"] == 6000
    assert ci.require_memory(record, 5000, reserve_bytes=1000)["required_available_bytes"] == 6000
    with pytest.raises(RuntimeError, match="Insufficient memory"):
        ci.require_memory(record, 5001, reserve_bytes=1000)


@pytest.mark.parametrize("membership", ["0::/../escape\n", "1:memory:/old\n", "0::/missing\n"])
def test_unverifiable_memory_limits_do_not_fall_back_to_host_memory(tmp_path, membership):
    (tmp_path / "proc/self").mkdir(parents=True)
    (tmp_path / "proc/self/cgroup").write_text(membership)
    (tmp_path / "groups").mkdir()
    with pytest.raises(RuntimeError):
        ci.available_memory(tmp_path / "proc", tmp_path / "groups")


@pytest.mark.skipif(os.name != "posix", reason="Procfs ownership is Linux-specific")
def test_procfs_namespace_mismatch_is_rejected_before_spawning(tmp_path, monkeypatch):
    (tmp_path / "self").symlink_to(str(os.getpid() + 1))
    monkeypatch.setattr(ci.subprocess, "Popen", lambda *_a, **_k: pytest.fail("Spawned a process"))
    with pytest.raises(RuntimeError, match="namespace mismatch"):
        ci.require_process_namespace(tmp_path)


def test_identity_recording_failure_stops_only_the_created_popen_child(monkeypatch):
    calls = []

    class Child:
        def poll(self):
            return None

        def terminate(self):
            calls.append("terminate")

        def wait(self, timeout):
            calls.append("wait")
            if calls.count("wait") == 1:
                raise subprocess.TimeoutExpired("fixture", timeout)

        def kill(self):
            calls.append("kill")

    monkeypatch.setattr(ci.os, "killpg", lambda *_: pytest.fail("Signalled an unverified group"))
    ci.stop_owned_daemon(Child(), None)
    assert calls == ["terminate", "wait", "kill", "wait"]


@pytest.mark.parametrize(
    "name",
    [
        "lib/ollama/cuda_v12/libcublas.so",
        "lib/ollama/libvulkan.so",
        "lib/ollama/rocm/libamdhip64.so",
    ],
)
def test_cpu_install_does_not_extract_gpu_libraries(name):
    assert not ci.cpu_member(name)


@pytest.mark.skipif(os.name != "posix", reason="Linux executable decompressor fixture")
def test_cpu_extraction_keeps_required_libraries_and_validates_skipped_paths(tmp_path, monkeypatch):
    unpacker = tmp_path / "zstd-fixture"
    unpacker.write_text(
        f"#!{sys.executable}\nimport sys\n"
        "sys.stdout.buffer.write(open(sys.argv[-1], 'rb').read())\n"
    )
    unpacker.chmod(0o755)
    monkeypatch.setattr(ci.shutil, "which", lambda _: str(unpacker))

    def archive(path, entries):
        with tarfile.open(path, "w") as target:
            for name, data in entries:
                member = tarfile.TarInfo(name)
                member.size = len(data)
                target.addfile(member, io.BytesIO(data))
        monkeypatch.setattr(ci, "ARCHIVE_SHA256", hashlib.sha256(path.read_bytes()).hexdigest())

    source = tmp_path / "source.tar"
    archive(
        source,
        [
            ("bin/ollama", b"test executable"),
            ("lib/ollama/libggml-cpu.so", b"test CPU library"),
            ("lib/ollama/cuda_v12/large.so", b"omitted GPU library"),
        ],
    )
    out = tmp_path / "runtime"
    report = ci.extract_archive(source, out, tmp_path / "extract.log", 10, cpu_only=True)
    assert (out / "bin/ollama").read_bytes() == b"test executable"
    assert (out / "lib/ollama/libggml-cpu.so").is_file()
    assert not (out / "lib/ollama/cuda_v12/large.so").exists()
    assert report["cpu_only"] is True
    archive(source, [("../unselected-gpu/escape", b"unsafe")])
    with pytest.raises(RuntimeError, match="escapes"):
        ci.extract_archive(source, tmp_path / "rejected", tmp_path / "bad.log", 10, cpu_only=True)
