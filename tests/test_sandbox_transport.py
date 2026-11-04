import copy
import hashlib
import io
import json
import os
import tarfile

import pytest

from dsgpt.sandbox import PIDS_LIMIT, DockerSandbox, SandboxError
from dsgpt.storage import uid

IMAGE = "sha256:" + "a" * 64
OWNER = "b" * 32


@pytest.mark.parametrize("existing", [None, b"{}\n", b"{}\r\n"])
def test_empty_docker_configuration_survives_windows_newlines(tmp_path, monkeypatch, existing):
    from dsgpt import sandbox as module

    binary = tmp_path / "docker.exe"
    binary.write_bytes(b"trusted fixture binary")
    monkeypatch.setattr(module, "docker_binary", lambda: binary)
    directory = tmp_path / "sandbox-docker-config"
    if existing is not None:
        directory.mkdir()
        (directory / "config.json").write_bytes(existing)
    first = DockerSandbox(tmp_path, IMAGE, OWNER)
    assert (first.configuration / "config.json").read_bytes() == (existing or b"{}\n")
    DockerSandbox(tmp_path, IMAGE, OWNER)
    (directory / "config.json").write_bytes(b'{"credsStore":"desktop"}\r\n')
    with pytest.raises(SandboxError, match="unsafe_sandbox_storage"):
        DockerSandbox(tmp_path, IMAGE, OWNER)


def instance(tmp_path):
    sandbox = object.__new__(DockerSandbox)
    sandbox.image, sandbox.owner_id = IMAGE, OWNER
    sandbox.configuration = tmp_path
    return sandbox


def container(execution):
    return {
        "Image": IMAGE,
        "Config": {
            "User": "1000:1000",
            "Labels": {
                "org.dsgpt.owner": OWNER,
                "org.dsgpt.execution": execution,
            },
        },
        "HostConfig": {
            "NetworkMode": "none",
            "ReadonlyRootfs": True,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges"],
            "IpcMode": "none",
            "CgroupnsMode": "private",
            "Runtime": "runc",
            "Memory": 4 * 1024**3,
            "MemorySwap": 4 * 1024**3,
            "NanoCpus": 2000000000,
            "PidsLimit": PIDS_LIMIT,
            "Tmpfs": {"/work": "rw", "/tmp": "rw"},
        },
    }


@pytest.mark.parametrize(
    "key,value",
    [
        ("NetworkMode", "host"),
        ("Privileged", True),
        ("ReadonlyRootfs", False),
        ("CapAdd", ["SYS_ADMIN"]),
        ("CapDrop", []),
        ("SecurityOpt", ["seccomp=unconfined"]),
        ("PidMode", "host"),
        ("IpcMode", "host"),
        ("CgroupnsMode", "host"),
        ("UsernsMode", "host"),
        ("UTSMode", "host"),
        ("Runtime", "nvidia"),
        ("Binds", ["/:/host"]),
        ("Devices", [{"PathOnHost": "/dev/sda"}]),
        ("DeviceRequests", [{"Count": -1}]),
        ("PortBindings", {"8000/tcp": []}),
        ("VolumesFrom", ["other"]),
        ("Mounts", [{"Type": "bind"}]),
        ("Memory", 0),
        ("MemorySwap", -1),
        ("NanoCpus", 0),
        ("PidsLimit", -1),
        ("Tmpfs", {"/work": "rw"}),
    ],
)
def test_effective_container_policy_rejects_unsafe_configuration(tmp_path, key, value):
    sandbox, execution = instance(tmp_path), uid()
    approved = container(execution)
    sandbox.validate_container(approved, execution)
    invalid = copy.deepcopy(approved)
    invalid["HostConfig"][key] = value
    with pytest.raises(SandboxError, match="sandbox_policy_mismatch"):
        sandbox.validate_container(invalid, execution)


async def test_create_checks_effective_policy_before_start_and_never_pulls(tmp_path, monkeypatch):
    sandbox, execution = instance(tmp_path), uid()
    calls = []

    async def checked(arguments, **kwargs):
        calls.append(arguments)
        return b"container"

    async def inspect(name):
        return container(execution)

    monkeypatch.setattr(sandbox, "checked", checked)
    monkeypatch.setattr(sandbox, "inspect", inspect)
    await sandbox.create(execution)
    create = calls[0]
    assert create[:2] == ["container", "create"]
    assert "--pull=never" in create and "--network=none" in create
    assert "--read-only" in create and "--cap-drop=ALL" in create
    assert "--runtime=runc" in create
    assert "--privileged" not in create and not any(a.startswith("--volume") for a in create)
    assert create[-4:] == [IMAGE, "-I", "-c", "import time; time.sleep(1800)"]
    assert calls[1][:2] == ["container", "start"]

    async def unsafe(name):
        result = container(execution)
        result["HostConfig"]["Privileged"] = True
        return result

    calls.clear()
    monkeypatch.setattr(sandbox, "inspect", unsafe)
    with pytest.raises(SandboxError):
        await sandbox.create(execution)
    assert len(calls) == 1


async def test_agent_arguments_are_after_cli_option_terminator_and_cleanup_runs(
    tmp_path, monkeypatch
):
    sandbox, execution = instance(tmp_path), uid()
    calls, cleaned = [], []

    async def create(identifier):
        return sandbox.name(identifier)

    async def checked(arguments, **kwargs):
        calls.append(arguments)
        return b""

    async def cli(arguments, **kwargs):
        calls.append(arguments)
        return 0, b"ok", b"", 0

    async def cleanup(identifier):
        cleaned.append(identifier)

    monkeypatch.setattr(sandbox, "create", create)
    monkeypatch.setattr(sandbox, "checked", checked)
    monkeypatch.setattr(sandbox, "cli", cli)
    monkeypatch.setattr(sandbox, "cleanup", cleanup)
    argv = ["--privileged", "--user=root", "some command; touch /host"]
    result = await sandbox.execute(execution, [], argv, [], 10)
    assert calls[-1] == [
        "container",
        "exec",
        "--workdir=/work",
        "--",
        sandbox.name(execution),
        *argv,
    ]
    assert result["stdout"] == "ok" and cleaned == [execution]


async def test_cleanup_never_removes_an_unrelated_container(tmp_path, monkeypatch):
    sandbox, execution = instance(tmp_path), uid()
    calls = []

    async def checked(arguments, **kwargs):
        calls.append(arguments)
        return sandbox.name(execution).encode()

    async def inspect(name):
        value = container(execution)
        value["Config"]["Labels"]["org.dsgpt.owner"] = "other"
        return value

    monkeypatch.setattr(sandbox, "checked", checked)
    monkeypatch.setattr(sandbox, "inspect", inspect)
    with pytest.raises(SandboxError, match="sandbox_identity_mismatch"):
        await sandbox.cleanup(execution)
    assert not any("rm" in c for c in calls)


async def test_tmpfs_artifact_is_streamed_in_guest_with_links_rejected(tmp_path, monkeypatch):
    sandbox, execution = instance(tmp_path), uid()
    calls, cleaned = [], []
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as writer:
        member = tarfile.TarInfo("-output.bin")
        member.size = 7
        writer.addfile(member, io.BytesIO(b"payload"))
    payload = archive.getvalue()

    async def create(identifier):
        return sandbox.name(identifier)

    async def checked(arguments, **kwargs):
        calls.append(arguments)
        if "--create" in arguments:
            return payload
        return b""

    async def cli(arguments, **kwargs):
        return 0, b"", b"", 0

    async def cleanup(identifier):
        cleaned.append(identifier)

    monkeypatch.setattr(sandbox, "create", create)
    monkeypatch.setattr(sandbox, "checked", checked)
    monkeypatch.setattr(sandbox, "cli", cli)
    monkeypatch.setattr(sandbox, "cleanup", cleanup)
    result = await sandbox.execute(execution, [], ["compiler"], ["out/-output.bin"], 10)
    assert result["artifacts"][0]["content"] == b"payload"
    assert calls[-1][:4] == ["container", "exec", "--", sandbox.name(execution)]
    assert calls[-1][-4:] == ["--directory", "/work/out", "--", "-output.bin"]
    assert "--no-recursion" in calls[-1] and not any("cp" in call for call in calls)
    assert cleaned == [execution]
    linked = io.BytesIO()
    with tarfile.open(fileobj=linked, mode="w") as writer:
        member = tarfile.TarInfo("-output.bin")
        member.type, member.linkname = tarfile.SYMTYPE, "/etc/passwd"
        writer.addfile(member)
    payload = linked.getvalue()
    with pytest.raises(SandboxError, match="artifact_not_regular_file"):
        await sandbox.execute(execution, [], ["compiler"], ["out/-output.bin"], 10)
    assert cleaned == [execution, execution]
    assert not list(tmp_path.iterdir())


@pytest.mark.skipif(
    os.name == "nt", reason="POSIX fixture executable; Windows CLI acceptance separate"
)
async def test_real_trusted_cli_fixture_bounds_output_strips_secrets_and_times_out(
    tmp_path, monkeypatch
):
    sandbox = instance(tmp_path)
    fixture = tmp_path / "fixture-docker"
    fixture.write_text(
        "#!/usr/bin/python3\nimport json,os,sys,time\n"
        "if sys.argv[-1]=='wait': time.sleep(60)\n"
        "print(json.dumps({'args':sys.argv[1:],'environment':dict(os.environ)}))\n"
        "if sys.argv[-1]=='flood': print('x'*10000)\n"
    )
    fixture.chmod(0o700)
    sandbox.executable = fixture
    sandbox.executable_sha256 = hashlib.sha256(fixture.read_bytes()).hexdigest()
    sandbox.endpoint = "unix:///var/run/docker.sock"
    monkeypatch.setenv("DOCKER_HOST", "tcp://remote.invalid:2375")
    monkeypatch.setenv("PRIVATE_TEST_SECRET", "must-not-reach-cli")
    code, out, error, omitted = await sandbox.cli(["fixture"], limit=20000)
    value = json.loads(out)
    assert code == 0 and not error and not omitted
    assert value["args"][:2] == ["--host", "unix:///var/run/docker.sock"]
    assert "PRIVATE_TEST_SECRET" not in value["environment"]
    assert "DOCKER_HOST" not in value["environment"]
    _, out, _, omitted = await sandbox.cli(["flood"], limit=512)
    assert len(out) == 512 and omitted > 9000
    with pytest.raises(TimeoutError):
        await sandbox.cli(["wait"], timeout=0.05)
    fixture.write_text("changed")
    with pytest.raises(SandboxError, match="docker_cli_changed"):
        await sandbox.cli(["fixture"])
