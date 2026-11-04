"""Actual Docker repair/build/artifact acceptance on a capable local host.

The agent actions are deliberate test fixtures. No LLM-quality claim is made.
Generated C/Java is compiled only inside the production checked container boundary.
On this restricted development host, the script reports the access blocker.
"""

import argparse
import hashlib
import io
import json
import struct
import tempfile
import time
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from dsgpt.api import create_app
from dsgpt.config import Model, Settings
from dsgpt.sandbox import SandboxError, docker_binary

BAD = '#include <stdio.h>\nint main(void) { puts("DSGPT_ISOLATED_BUILD") return 0; }\n'
GOOD = BAD.replace('BUILD") return', 'BUILD"); return')


class DeliberateAgent:
    def __init__(self, target):
        if target == "apk":
            root = Path(__file__).resolve().parents[1] / "execution/android-fixture"
            sources = {
                name: (root / name).read_text()
                for name in (
                    "AndroidManifest.xml",
                    "MainActivity.java",
                    "res/values/strings.xml",
                )
            }
            source_path = "MainActivity.java"
            bad = sources[source_path]
            good = bad.replace(
                'text.setText("DSGPT_ISOLATED_APK")', 'text.setText("DSGPT_ISOLATED_APK");'
            )
            argv = ["python3", "-I", "/opt/dsgpt/build-android-fixture.py"]
            artifact = "fixture.apk"
        else:
            source_path, bad, good = "hello.c", BAD, GOOD
            sources = {source_path: bad}
            argv = ["x86_64-w64-mingw32-gcc", "hello.c", "-o", "hello.exe"]
            artifact = "hello.exe"
        command = {
            "tool": "run",
            "argv": argv,
            "artifacts": [artifact],
            "summary": "Compile current source",
        }
        self.actions = iter(
            [
                *[
                    {
                        "tool": "write_file",
                        "path": path,
                        "content": content,
                        "summary": "Write fixture with deliberate syntax error",
                    }
                    for path, content in sources.items()
                ],
                command,
                {
                    "tool": "write_file",
                    "path": source_path,
                    "content": good,
                    "expected_sha256": hashlib.sha256(bad.encode()).hexdigest(),
                    "summary": "Fix error",
                },
                command,
                {
                    "tool": "finish",
                    "summary": "Collected binary; native device execution is untested",
                },
            ]
        )

    async def stream(self, model, messages, response_schema=None):
        yield {"kind": "delta", "data": {"text": json.dumps(next(self.actions))}}


def run(args, report):
    try:
        docker_binary()
    except SandboxError as exc:
        report.update(blocked=True, blocker=str(exc))
        return 2
    if not args.image:
        raise SystemExit("Supply --image with the reviewed, locally installed sha256 image ID")
    with tempfile.TemporaryDirectory(prefix="dsgpt-isolated-acceptance-") as directory:
        model = Model(
            "fixture", "Integration fixture", "ollama", "http://127.0.0.1:11434", "fixture"
        )
        app = create_app(
            Settings(
                Path(directory),
                {model.id: model},
                allowed_hosts=("testserver",),
                sandbox_image=args.image,
            ),
            DeliberateAgent(args.target),
        )
        credential = app.state.auth.initialize_owner()
        with TestClient(app, headers={"Authorization": "Bearer " + credential["token"]}) as client:
            response = client.post("/v1/work/sandbox/probe")
            report["probe"] = response.json()
            if response.status_code != 200:
                report.update(blocked=True, blocker="sandbox_probe_failed")
            else:
                report["actual_container_execution"] = True
                task = client.post(
                    "/v1/work/tasks",
                    json={
                        "title": f"Isolated {args.target} build acceptance",
                        "requirements": "Compile fixture",
                        "model_id": model.id,
                        "build_target": args.target,
                    },
                ).json()
                client.post(
                    f"/v1/work/tasks/{task['id']}/actions",
                    json={"action": "start", "revision": task["revision"]},
                ).raise_for_status()
                deadline = time.monotonic() + 240
                while time.monotonic() < deadline:
                    current = client.get(f"/v1/work/tasks/{task['id']}").json()
                    if current["status"] in {"completed", "blocked"}:
                        break
                    time.sleep(0.05)
                steps = client.get(f"/v1/work/tasks/{task['id']}/steps").json()
                report["steps"] = steps
                report["task_status"] = current["status"]
                response = client.get(f"/v1/work/tasks/{task['id']}/executions")
                response.raise_for_status()
                executions = []
                for receipt in sorted(response.json(), key=lambda row: row["step"]):
                    response = client.get(f"/v1/work/tasks/{task['id']}/executions/{receipt['id']}")
                    response.raise_for_status()
                    executions.append(response.json())
                report["executions"] = executions
                # Agent steps intentionally contain only short excerpts. Acceptance
                # consumes the bounded full receipts through the authenticated API.
                commands = [receipt["result"] or {} for receipt in executions]
                report["actual_compiler_execution"] = any("exit_code" in c for c in commands)
                report["injected_compiler_error_observed"] = bool(
                    commands
                    and commands[0].get("exit_code", 0) > 0
                    and ("MainActivity.java:" if args.target == "apk" else "hello.c:")
                    in commands[0].get("stderr", "")
                    and "error:" in commands[0].get("stderr", "")
                )
                artifacts = client.get(f"/v1/work/tasks/{task['id']}/artifacts").json()
                matching = [a for a in artifacts if a["path"].endswith("." + args.target)]
                if len(matching) == 1:
                    artifact = matching[0]
                    response = client.get(f"/v1/work/tasks/{task['id']}/artifacts/{artifact['id']}")
                    response.raise_for_status()
                    output = args.output.with_suffix("." + args.target)
                    output.write_bytes(response.content)
                    report["artifact"] = {
                        "file": output.name,
                        "sha256": artifact["sha256"],
                        "bytes": artifact["bytes"],
                    }
                    data = response.content
                    report["artifact"]["download_hash_verified"] = (
                        hashlib.sha256(data).hexdigest() == artifact["sha256"]
                        and len(data) == artifact["bytes"]
                    )
                    if args.target == "apk":
                        with zipfile.ZipFile(io.BytesIO(data)) as archive:
                            report["artifact"]["apk_structure_verified"] = (
                                archive.testzip() is None
                                and archive.read("classes.dex").startswith(b"dex\n")
                                and archive.read("AndroidManifest.xml").startswith(
                                    b"\x03\x00\x08\x00"
                                )
                                and "resources.arsc" in archive.namelist()
                            )
                        assert commands[-1]["omitted_output_bytes"] == 0
                        verified = json.loads(commands[-1]["stdout"].strip().splitlines()[-1])
                        report["guest_signature_verification"] = verified
                        report["binary_format_verified"] = bool(
                            report["artifact"]["apk_structure_verified"]
                            and verified.get("apksigner_verified") is True
                            and verified.get("zipalign_verified") is True
                            and verified.get("sha256") == artifact["sha256"]
                        )
                    else:
                        offset = struct.unpack_from("<I", data, 0x3C)[0]
                        report["binary_format_verified"] = (
                            data[:2] == b"MZ"
                            and data[offset : offset + 4] == b"PE\x00\x00"
                            and struct.unpack_from("<H", data, offset + 4)[0] == 0x8664
                        )
                report["passed"] = bool(
                    current["status"] == "completed"
                    and len(commands) == 2
                    and report["injected_compiler_error_observed"]
                    and commands[1].get("exit_code") == 0
                    and len(matching) == 1
                    and report["artifact"]["download_hash_verified"]
                    and report["binary_format_verified"]
                    and all(e["cleanup_pending"] == 0 for e in executions)
                )
    return 0 if report["passed"] else 1


def main(args):
    report = {
        "actual_container_execution": False,
        "actual_compiler_execution": False,
        "agent": "deliberate deterministic fixture, not LLM",
        "passed": False,
        "native_windows_execution": False,
        "native_android_execution": False,
        "build_target": args.target,
        "artifact": None,
    }
    try:
        return run(args, report)
    except Exception as exc:
        report["passed"] = False
        report["error"] = type(exc).__name__ + ": " + str(exc)
        return 1
    finally:
        args.output.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({k: v for k, v in report.items() if k not in {"steps", "executions"}}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--image")
    parser.add_argument("--target", choices=("exe", "apk"), default="exe")
    parser.add_argument("--output", type=Path, required=True)
    raise SystemExit(main(parser.parse_args()))
