"""Narrow local Docker transport. Generated commands run only inside checked containers.

No host shell, remote daemon, bind mounts, Docker socket mount, GPU, network, image
pull, privileged mode, or provider credentials are exposed to project code.
"""

import asyncio
import hashlib
import io
import json
import os
import re
import stat
import tarfile
from pathlib import Path, PurePosixPath

from .project_tools import MAX_PROJECT_BYTES, safe_path

OUTPUT_BYTES = 262144
ARTIFACT_BYTES = 256 * 1024**2
PIDS_LIMIT = 256
MEMORY_BYTES = 4 * 1024**3
WORK_BYTES = 1024**3


class SandboxError(Exception):
    pass


def docker_binary():
    paths = (
        [
            Path(os.environ.get("LOCALAPPDATA", ""))
            / "Programs/DockerDesktop/resources/bin/docker.exe",
            Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
            / "Docker/Docker/resources/bin/docker.exe",
        ]
        if os.name == "nt"
        else [Path("/usr/bin/docker"), Path("/usr/local/bin/docker")]
    )
    for path in paths:
        if path.is_file():
            return path.resolve()
    raise SandboxError("docker_cli_not_installed")


def source_archive(files, *, input_limit=MAX_PROJECT_BYTES):
    out = io.BytesIO()
    total = 0
    with tarfile.open(fileobj=out, mode="w") as archive:
        for row in files:
            name = safe_path(row["path"])
            data = row["content"]
            if isinstance(data, str):
                data = data.encode()
            total += len(data)
            if total > input_limit or hashlib.sha256(data).hexdigest() != row["sha256"]:
                raise SandboxError("project_snapshot_invalid")
            entry = tarfile.TarInfo(name)
            entry.size, entry.mode, entry.uid, entry.gid, entry.mtime = (
                len(data),
                0o600,
                1000,
                1000,
                0,
            )
            archive.addfile(entry, io.BytesIO(data))
    return out.getvalue()


def artifact_bytes(archive, expected):
    if len(archive) > ARTIFACT_BYTES + 65536:
        raise SandboxError("artifact_too_large")
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as reader:
            entries = iter(reader)
            entry = next(entries, None)
            if entry is None or next(entries, None) is not None:
                raise SandboxError("artifact_not_regular_file")
            if (
                not entry.isfile()
                or entry.name != PurePosixPath(expected).name
                or entry.size > ARTIFACT_BYTES
                or entry.size < 1
                or entry.sparse is not None
            ):
                raise SandboxError("artifact_not_regular_file")
            return reader.extractfile(entry).read(ARTIFACT_BYTES + 1)
    except (tarfile.TarError, OSError) as exc:
        raise SandboxError("artifact_invalid_archive") from exc


# This trusted fixture checks effective guest settings as well as API metadata.
# It does not purport to prove that a kernel or Docker implementation has no bugs.
PROBE = r"""import json,os,pathlib
lines=pathlib.Path('/proc/self/status').read_text().splitlines()
s={k:v.strip() for k,v in (line.split(':',1) for line in lines if ':' in line)}
assert os.getuid()==1000 and os.getgid()==1000
assert int(s['CapEff'],16)==0 and int(s['CapBnd'],16)==0
assert s['NoNewPrivs']=='1' and s['Seccomp']=='2'
assert not pathlib.Path('/var/run/docker.sock').exists()
assert set(os.listdir('/sys/class/net'))=={'lo'}
assert not list(pathlib.Path('/dev').glob('nvidia*'))
cg=pathlib.Path('/sys/fs/cgroup')
assert (cg/'memory.max').read_text().strip()=='4294967296'
assert (cg/'pids.max').read_text().strip()=='256'
quota,period=(cg/'cpu.max').read_text().split()
assert int(quota)==2*int(period)
try:
 pathlib.Path('/root-write-probe').write_text('denied')
except OSError: pass
else: raise AssertionError('root is writable')
pathlib.Path('/work/probe.txt').write_text('isolated work directory')
assert pathlib.Path('/work/probe.txt').read_text()=='isolated work directory'
print(json.dumps({'uid':os.getuid(),'capabilities':'none','network':'loopback_only',
'no_new_privileges':True,'seccomp':True,'root_write_denied':True,
'workspace_writable':True,'resource_limits':True,'gpu':False}))
"""


class DockerSandbox:
    def __init__(self, directory, image, owner_id):
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", image):
            raise ValueError("Sandbox image must be a locally installed immutable image ID")
        if not re.fullmatch(r"[a-f0-9]{32}", owner_id):
            raise ValueError("Invalid sandbox owner identity")
        self.image, self.owner_id = image, owner_id
        self.executable = docker_binary()
        self.executable_sha256 = hashlib.file_digest(
            self.executable.open("rb"), "sha256"
        ).hexdigest()
        self.configuration = directory / "sandbox-docker-config"
        if self.configuration.is_symlink():
            raise SandboxError("unsafe_sandbox_storage")
        self.configuration.mkdir(mode=0o700, exist_ok=True)
        path = self.configuration / "config.json"
        if not path.exists():
            # Binary output keeps the exact allowlisted bytes on Windows too.
            with path.open("xb") as file:
                file.write(b"{}\n")
            if os.name != "nt":
                path.chmod(0o600)
        if path.is_symlink() or path.read_bytes() not in (b"{}\n", b"{}\r\n"):
            raise SandboxError("unsafe_sandbox_storage")
        self.endpoint = (
            "npipe:////./pipe/docker_engine" if os.name == "nt" else "unix:///var/run/docker.sock"
        )

    def name(self, execution_id):
        if not re.fullmatch(r"[a-f0-9-]{36}", execution_id):
            raise SandboxError("invalid_execution_identity")
        return "dsgpt-" + self.owner_id[:12] + "-" + execution_id

    async def cli(self, arguments, data=None, timeout=30, limit=OUTPUT_BYTES):
        # Configuration is trusted owner state. No incoming API or model value can
        # alter the executable, daemon endpoint, flags, environment, or host paths.
        info = self.executable.stat()
        if (
            not stat.S_ISREG(info.st_mode)
            or hashlib.file_digest(self.executable.open("rb"), "sha256").hexdigest()
            != self.executable_sha256
        ):
            raise SandboxError("docker_cli_changed")
        environment = {k: os.environ[k] for k in ("SystemRoot", "WINDIR") if k in os.environ}
        environment.update(PATH=os.defpath, LANG="C", LC_ALL="C")
        process = await asyncio.create_subprocess_exec(
            str(self.executable),
            "--host",
            self.endpoint,
            "--config",
            str(self.configuration),
            *arguments,
            stdin=asyncio.subprocess.PIPE if data is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.configuration,
            env=environment,
            **({"creationflags": 0x08000000} if os.name == "nt" else {}),
        )

        async def read(stream, cap):
            result, omitted = bytearray(), 0
            while block := await stream.read(16384):
                available = max(0, cap - len(result))
                result.extend(block[:available])
                omitted += max(0, len(block) - available)
            return bytes(result), omitted

        async def write():
            if data is not None:
                try:
                    process.stdin.write(data)
                    await process.stdin.drain()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    process.stdin.close()

        readers = [
            asyncio.create_task(read(process.stdout, limit)),
            asyncio.create_task(read(process.stderr, OUTPUT_BYTES)),
            asyncio.create_task(write()),
        ]
        try:
            async with asyncio.timeout(timeout):
                out, error, _ = await asyncio.gather(*readers)
                code = await process.wait()
                return code, out[0], error[0], out[1] + error[1]
        except BaseException:
            if process.returncode is None:
                process.kill()
            await process.wait()
            for reader in readers:
                reader.cancel()
            await asyncio.gather(*readers, return_exceptions=True)
            raise

    async def checked(self, arguments, **kwargs):
        code, out, error, omitted = await self.cli(arguments, **kwargs)
        if code:
            raise SandboxError("docker_operation_failed")
        if omitted:
            raise SandboxError("docker_response_too_large")
        return out

    async def inspect(self, name):
        value = json.loads(await self.checked(["container", "inspect", name]))
        if not isinstance(value, list) or len(value) != 1:
            raise SandboxError("docker_protocol_error")
        return value[0]

    def validate_container(self, value, execution_id):
        host, config = value["HostConfig"], value["Config"]
        tmpfs = host.get("Tmpfs") or {}
        if (
            value["Image"] != self.image
            or config.get("User") != "1000:1000"
            or config.get("Labels", {}).get("org.dsgpt.owner") != self.owner_id
            or config.get("Labels", {}).get("org.dsgpt.execution") != execution_id
            or host.get("NetworkMode") != "none"
            or host.get("Privileged")
            or not host.get("ReadonlyRootfs")
            or host.get("CapAdd")
            or set(host.get("CapDrop") or []) != {"ALL"}
            or "no-new-privileges" not in (host.get("SecurityOpt") or [])
            or any("unconfined" in x for x in host.get("SecurityOpt", []))
            or host.get("PidMode")
            or host.get("IpcMode") != "none"
            or host.get("CgroupnsMode") != "private"
            or host.get("UsernsMode") == "host"
            or host.get("UTSMode")
            or host.get("Runtime") != "runc"
            or host.get("Binds")
            or host.get("Devices")
            or host.get("DeviceRequests")
            or host.get("VolumesFrom")
            or host.get("PortBindings")
            or host.get("Mounts")
            or config.get("Volumes")
            or value.get("Mounts")
            or host.get("Memory") != MEMORY_BYTES
            or host.get("MemorySwap") != MEMORY_BYTES
            or host.get("NanoCpus") != 2000000000
            or host.get("PidsLimit") != PIDS_LIMIT
            or set(tmpfs) != {"/work", "/tmp"}
        ):
            raise SandboxError("sandbox_policy_mismatch")

    async def create(self, execution_id):
        name = self.name(execution_id)
        await self.checked(
            [
                "container",
                "create",
                "--name",
                name,
                "--label",
                "org.dsgpt.owner=" + self.owner_id,
                "--label",
                "org.dsgpt.execution=" + execution_id,
                "--pull=never",
                "--network=none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--pids-limit=" + str(PIDS_LIMIT),
                "--cpus=2",
                "--memory=" + str(MEMORY_BYTES),
                "--memory-swap=" + str(MEMORY_BYTES),
                "--user=1000:1000",
                "--ipc=none",
                "--cgroupns=private",
                "--runtime=runc",
                "--init",
                "--no-healthcheck",
                "--log-driver=none",
                "--workdir=/work",
                "--tmpfs=/work:rw,nosuid,nodev,exec,size="
                + str(WORK_BYTES)
                + ",uid=1000,gid=1000,mode=700",
                "--tmpfs=/tmp:rw,nosuid,nodev,exec,size=268435456,uid=1000,gid=1000,mode=700",
                "--env=TMPDIR=/tmp",
                "--entrypoint=python3",
                self.image,
                "-I",
                "-c",
                "import time; time.sleep(1800)",
            ]
        )
        self.validate_container(await self.inspect(name), execution_id)
        await self.checked(["container", "start", name])
        return name

    async def cleanup(self, execution_id):
        name = self.name(execution_id)
        # Only touch containers bearing both recorded identities. Name collisions or
        # a daemon failure never justify deleting an unrelated container.
        containers = await self.checked(
            [
                "container",
                "ls",
                "--all",
                "--filter",
                "name=^/" + name + "$",
                "--format",
                "{{.Names}}",
            ]
        )
        if not containers.strip():
            return
        value = await self.inspect(name)
        labels = value["Config"].get("Labels") or {}
        if (
            labels.get("org.dsgpt.owner") != self.owner_id
            or labels.get("org.dsgpt.execution") != execution_id
        ):
            raise SandboxError("sandbox_identity_mismatch")
        await self.checked(["container", "rm", "--force", "--volumes", name])

    async def execute(
        self,
        execution_id,
        files,
        argv,
        artifact_paths,
        timeout,
        *,
        broker=None,
        input_limit=MAX_PROJECT_BYTES,
    ):
        name = self.name(execution_id)
        result = None
        bridge = None
        try:
            await self.create(execution_id)
            # This extraction is inside an empty, nonprivileged container tmpfs.
            await self.checked(
                ["container", "exec", "-i", "--", name, "tar", "-xf", "-", "-C", "/work"],
                data=source_archive(files, input_limit=input_limit),
            )
            if broker:
                bridge = asyncio.create_task(broker(name))
            code, out, error, omitted = await self.cli(
                ["container", "exec", "--workdir=/work", "--", name, *argv],
                timeout=timeout,
            )
            artifacts = []
            if code == 0:
                for path in artifact_paths:
                    safe_path(path)
                    artifact = PurePosixPath(path)
                    # Docker's archive/cp API cannot read tmpfs contents reliably.
                    # Stream one non-recursive archive from inside the same checked
                    # guest namespace; never extract it onto the host.
                    data = await self.checked(
                        [
                            "container",
                            "exec",
                            "--",
                            name,
                            "tar",
                            "--format=ustar",
                            "--create",
                            "--file=-",
                            "--no-recursion",
                            "--directory",
                            str(PurePosixPath("/work") / artifact.parent),
                            "--",
                            artifact.name,
                        ],
                        limit=ARTIFACT_BYTES + 65536,
                        timeout=60,
                    )
                    content = artifact_bytes(data, path)
                    artifacts.append(
                        {
                            "path": path,
                            "content": content,
                            "sha256": hashlib.sha256(content).hexdigest(),
                        }
                    )
            result = {
                "exit_code": code,
                "stdout": out.decode("utf-8", errors="replace"),
                "stderr": error.decode("utf-8", errors="replace"),
                "omitted_output_bytes": omitted,
                "artifacts": artifacts,
            }
        except TimeoutError:
            raise SandboxError("sandbox_command_timeout") from None
        finally:
            if bridge:
                bridge.cancel()
                await asyncio.gather(bridge, return_exceptions=True)
            cleanup = asyncio.create_task(self.cleanup(execution_id))
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                await asyncio.gather(cleanup, return_exceptions=True)
                raise
        return result

    async def probe(self, execution_id):
        info = json.loads(await self.checked(["info", "--format", "{{json .}}"]))
        if info.get("OSType") != "linux" or not any(
            "seccomp" in v for v in info.get("SecurityOptions", [])
        ):
            raise SandboxError("linux_seccomp_docker_required")
        image = json.loads(await self.checked(["image", "inspect", self.image]))[0]
        if image["Id"] != self.image or image.get("Config", {}).get("Volumes"):
            raise SandboxError("sandbox_image_invalid")
        result = await self.execute(execution_id, [], ["python3", "-I", "-c", PROBE], [], 30)
        if result["exit_code"] != 0 or result["omitted_output_bytes"]:
            raise SandboxError("sandbox_probe_failed")
        evidence = json.loads(result["stdout"])
        required = {
            "uid": 1000,
            "capabilities": "none",
            "network": "loopback_only",
            "no_new_privileges": True,
            "seccomp": True,
            "root_write_denied": True,
            "workspace_writable": True,
            "resource_limits": True,
            "gpu": False,
        }
        if evidence != required:
            raise SandboxError("sandbox_probe_failed")
        return {
            "checks": evidence,
            "docker_version": info.get("ServerVersion"),
            "image_id": self.image,
            "docker_cli_sha256": self.executable_sha256,
        }
