"""Run with the bundled private Python: -I -m dsgpt_acceptance --kit <directory>."""

import argparse
import contextlib
import hashlib
import html
import io
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import httpx

from .cdp import CDP
from .ollama_runtime import OLLAMA
from .ollama_runtime import install as install_ollama
from .setup import (
    Blocked,
    RestartRequired,
    adb_devices,
    adb_guidance,
    docker_locations,
    elevated,
    google_usb_inventory,
    pairing_endpoints,
    powershell,
    ps_quote,
    resume_after_reboot,
    wait_ready,
    wireless_endpoint,
    wireless_serial,
)

PACKAGE = "com.dsgpt.mobile.acceptance"
FIXTURE = "acceptance-fixture"


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def command(argv, timeout=60, **kwargs):
    kwargs.setdefault("creationflags", getattr(subprocess, "CREATE_NO_WINDOW", 0))
    started = time.monotonic()
    with subprocess.Popen(
        [str(v) for v in argv], stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs
    ) as child:
        try:
            while True:
                remaining = timeout - (time.monotonic() - started)
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(str(argv[0]), timeout)
                try:
                    out, err = child.communicate(timeout=min(30, remaining))
                    return subprocess.CompletedProcess(argv, child.returncode, out, err)
                except subprocess.TimeoutExpired:
                    if timeout > 60:
                        print(
                            "  Still working; elapsed "
                            + str(round(time.monotonic() - started))
                            + " seconds",
                            flush=True,
                        )
        except BaseException:
            child.kill()
            child.communicate()
            raise


def executable(name, candidates=()):
    found = shutil.which(name)
    return found or next((str(p) for p in candidates if p.is_file()), None)


class Runner:
    def __init__(self, args):
        self.args = args
        self.kit = args.kit.resolve()
        self.id = uuid.uuid4().hex
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "dsGPT-Acceptance"
        self.root = (args.output or base / self.id).resolve()
        self.root.mkdir(parents=True, exist_ok=False)
        self.private = self.root / "private"
        self.private.mkdir()
        self.share = self.root / "report"
        self.share.mkdir()
        self.secrets = []
        self.children = []
        self.cleanup = []
        self.http = httpx.Client(trust_env=False, follow_redirects=False, timeout=20)
        self.report = {
            "format": 1,
            "run": self.id,
            "started": datetime.now(UTC).isoformat(),
            "system": platform.system(),
            "checks": [],
            "finished": False,
            "scope": "Synthetic acceptance data; no personal chats collected",
            "quality_limit": "Fixture checks do not establish model answer quality",
        }
        self.backend = None
        self.token = None
        self.models = []
        self.phone = None
        self.tailnet = None
        self.needs_restart = False
        self.phone_states = []
        self.local_work_evidence = None
        self.save()
        if os.name == "nt":
            # Resolve the current SID without putting the account name into a shared log.
            sid = command(["whoami", "/user", "/fo", "csv", "/nh"]).stdout.decode(errors="replace")
            match = re.search(r"S-1-5-[0-9-]+", sid)
            if (
                not match
                or command(
                    [
                        "icacls",
                        self.private,
                        "/inheritance:r",
                        "/grant:r",
                        "*" + match[0] + ":(OI)(CI)F",
                    ]
                ).returncode
            ):
                raise RuntimeError("Could not restrict the private test directory")

    def clean(self, value):
        text = json.dumps(value, ensure_ascii=False)
        for secret in sorted(
            self.secrets + [str(self.private), str(Path.home())], key=len, reverse=True
        ):
            if secret:
                # Match JSON escaping as well as plain text.
                text = text.replace(json.dumps(secret, ensure_ascii=False)[1:-1], "[redacted]")
        text = re.sub(r"[A-Za-z0-9_.-]+\.ts\.net", "[tailnet-host]", text)
        return json.loads(text)

    def save(self):
        safe = self.clean(self.report)
        target = self.share / "report.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(safe, indent=2), encoding="utf-8")
        temporary.replace(target)
        rows = "".join(
            "<tr><td>"
            + html.escape(c["name"])
            + "</td><td>"
            + c["status"]
            + "</td><td>"
            + html.escape(json.dumps(c.get("detail", "")))
            + "</td></tr>"
            for c in safe["checks"]
        )
        (self.share / "Read-this-report.html").write_text(
            '<!doctype html><meta charset="utf-8">'
            "<title>dsGPT acceptance report</title>"
            "<style>body{font:16px system-ui;max-width:1100px;margin:36px auto;padding:0 20px}"
            "td,th{border:1px solid #bbb;padding:10px;text-align:left}"
            "table{border-collapse:collapse}"
            "h1{color:#164b62}</style><h1>dsGPT acceptance report</h1><p>"
            + ("Finished. " if safe["finished"] else "In progress or interrupted. ")
            + "PASS means this check executed successfully. BLOCKED needs the stated prerequisite. "
            "FAIL means a check ran and failed. "
            "REVIEW is a release decision or human observation.</p>"
            "<p>Share the dsGPT-report ZIP, not the private folder. "
            "No upload happens automatically.</p>"
            "<table><tr><th>Check</th><th>Result</th><th>Evidence / next action</th></tr>"
            + rows
            + "</table>",
            encoding="utf-8",
        )
        archive = self.root / "dsGPT-report.zip"
        temporary = archive.with_suffix(".tmp")
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as z:
            for path in sorted(self.share.rglob("*")):
                if path.is_file() and path.suffix in {".json", ".html", ".txt", ".zip"}:
                    z.write(path, path.relative_to(self.share))
        temporary.replace(archive)

    def check(self, name, function):
        print(f"\nRUNNING  {name}", flush=True)
        row = {"name": name, "status": "RUNNING"}
        self.report["checks"].append(row)
        self.save()
        started = time.monotonic()
        try:
            row.update(status="PASS", detail=function() or {})
        except RestartRequired as exc:
            self.needs_restart = True
            row.update(status="BLOCKED", detail=str(exc))
            raise
        except Blocked as exc:
            row.update(status="BLOCKED", detail=str(exc))
        except (AssertionError, subprocess.TimeoutExpired) as exc:
            row.update(
                status="FAIL",
                detail=str(exc)
                if isinstance(exc, AssertionError)
                else "Time limit exceeded; other independent checks continue",
            )
        except Exception as exc:
            # Raw transport errors can contain account paths/URLs; retain them locally only.
            with (self.private / "errors.txt").open("a", encoding="utf-8") as f:
                f.write(name + ": " + repr(exc) + "\n")
            row.update(
                status="FAIL",
                detail=type(exc).__name__
                + "; check could not finish. The result is preserved for review.",
            )
        finally:
            row["seconds"] = round(time.monotonic() - started, 2)
            self.save()
            print(
                f"{row['status']:8} {name}: {self.clean(row.get('detail', 'Interrupted'))}",
                flush=True,
            )

    def spawn(self, argv, env=None):
        log = (self.private / f"process-{len(self.children)}.txt").open("wb")
        try:
            child = subprocess.Popen(
                [str(v) for v in argv],
                stdout=log,
                stderr=log,
                stdin=subprocess.DEVNULL,
                env=env,
                cwd=self.private,
            )
        finally:
            log.close()
        self.children.append(child)
        return child

    @staticmethod
    def stop(child):
        if child and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=10)

    def api(self, method, path, body=None, token=None, expected=200):
        if self.backend is None or self.backend.poll() is not None:
            raise Blocked("The isolated backend must start successfully first.")
        response = self.http.request(
            method,
            self.origin + path,
            json=body,
            headers={"Authorization": "Bearer " + (token or self.token)},
        )
        require(
            response.status_code == expected,
            f"API {method} {path.split('?')[0]} expected {expected}, got {response.status_code}",
        )
        return response.json()

    def integrity(self):
        manifest = json.loads((self.kit / "kit-manifest.json").read_text())
        for name, record in manifest["files"].items():
            path = self.kit / name
            require(path.resolve().is_relative_to(self.kit) and path.is_file(), "Kit file missing")
            require(
                path.stat().st_size == record["bytes"] and digest(path) == record["sha256"],
                "Kit integrity check failed: " + name,
            )
        self.report["source_commit"] = manifest["source_commit"]
        return {
            "verified_files": len(manifest["files"]),
            "source_commit": manifest["source_commit"],
        }

    def inventory(self):
        import psutil

        result = {
            "architecture": platform.machine(),
            "os_release": platform.release(),
            "ram_gib": round(psutil.virtual_memory().total / 1024**3, 1),
            "free_disk_gib": round(shutil.disk_usage(self.root).free / 1024**3, 1),
        }
        smi = executable(
            "nvidia-smi", [Path(os.environ.get("WINDIR", "C:/Windows")) / "System32/nvidia-smi.exe"]
        )
        self.smi = smi
        if smi:
            r = command(
                [
                    smi,
                    "--query-gpu=name,driver_version,memory.total,memory.used,temperature.gpu",
                    "--format=csv,noheader,nounits",
                ]
            )
            require(r.returncode == 0, "NVIDIA driver query failed")
            result["gpu"] = r.stdout.decode(errors="replace").strip()
        else:
            result["gpu"] = "NVIDIA driver query unavailable"
        return result

    def resume_setup(self, enable):
        resume_after_reboot(self.kit, enable, wireless=getattr(self.args, "wireless", False))

    def vendor_install(self, package):
        """Install missing fixed prerequisites; Windows still owns UAC and reboot consent."""
        if self.args.ci or os.name != "nt":
            raise Blocked("Automatic Windows installation is disabled in CI/on this OS.")
        require(
            package
            in {
                "Docker.DockerDesktop",
                "Microsoft.EdgeWebView2Runtime",
                "Microsoft.VCRedist.2015+.x64",
                "Tailscale.Tailscale",
            },
            "Unexpected prerequisite installer",
        )
        self.resume_setup(True)
        print(
            "Installing missing " + package + " automatically. "
            "Approve a Windows permission prompt if one appears.",
            flush=True,
        )
        winget = executable("winget")
        if winget:
            argv = [
                winget,
                "install",
                "--id",
                package,
                "--exact",
                "--source",
                "winget",
                "--silent",
                "--no-upgrade",
                "--accept-source-agreements",
                "--accept-package-agreements",
                "--disable-interactivity",
            ]
            if package == "Docker.DockerDesktop":
                # WinGet agreements alone do not accept Docker's first-run terms or backend.
                argv += [
                    "--override",
                    "install --user --quiet --accept-license --backend=wsl-2",
                ]
        else:
            publishers = {
                "Docker.DockerDesktop": (
                    "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe",
                    "Docker",
                    ["install", "--user", "--quiet", "--accept-license", "--backend=wsl-2"],
                ),
                "Tailscale.Tailscale": (
                    "https://pkgs.tailscale.com/stable/tailscale-setup-latest.exe",
                    "Tailscale",
                    ["/quiet", "/norestart"],
                ),
                "Microsoft.EdgeWebView2Runtime": (
                    "https://go.microsoft.com/fwlink/p/?LinkId=2124703",
                    "Microsoft Corporation",
                    ["/silent", "/install"],
                ),
                "Microsoft.VCRedist.2015+.x64": (
                    "https://aka.ms/vs/17/release/vc_redist.x64.exe",
                    "Microsoft Corporation",
                    ["/install", "/quiet", "/norestart"],
                ),
            }
            url, publisher, flags = publishers[package]
            installer = self.private / (package + "-Setup.exe")
            print("Downloading the official " + publisher + " installer...", flush=True)
            total, last = 0, 0
            with self.http.stream("GET", url, follow_redirects=True, timeout=120) as response:
                response.raise_for_status()
                with installer.open("wb") as stream:
                    for block in response.iter_bytes(1024 * 1024):
                        total += len(block)
                        require(total <= 4 * 1024**3, "Installer exceeds download size limit")
                        stream.write(block)
                        if time.monotonic() - last > 5:
                            print("  Downloaded " + str(total // 1024**2) + " MB", flush=True)
                            last = time.monotonic()
            signature = powershell(
                command,
                "$s=Get-AuthenticodeSignature -LiteralPath " + ps_quote(installer) + "; "
                "if ($s.Status -eq 'Valid' -and $s.SignerCertificate.Subject -match "
                + ps_quote(r"(?:^|,\s*)O=" + re.escape(publisher) + r"(?:[,\s]|$)")
                + ") { exit 0 } else { exit 1 }",
            )
            require(
                signature.returncode == 0,
                publisher + " publisher signature could not be verified; installer was not run",
            )
            argv = [str(installer), *flags]
        child = subprocess.Popen(argv)
        started, last = time.monotonic(), 0
        while child.poll() is None:
            if time.monotonic() - last > 30:
                print(
                    "  Installing "
                    + package
                    + " unattended; only Windows permission may be needed.",
                    flush=True,
                )
                last = time.monotonic()
            if time.monotonic() - started > 1800:
                raise Blocked(
                    package + " installer is still running. Leave it to finish; "
                    "rerun the kit afterwards."
                )
            time.sleep(1)
        code = child.returncode & 0xFFFFFFFF
        if code in {1641, 3010, 0x8A150109, 0x8A15010A, 0x8A15010B}:
            raise RestartRequired(
                "Windows needs a restart to finish installing "
                + package
                + ". Save your work and restart. This kit will reopen after "
                "you sign in; installed dependencies are reused."
            )
        require(
            code in {0, 0x8A150061, 0x8A15010D},
            package
            + " installer exited with code "
            + hex(code)
            + ". Setup did not finish; see the installer message above.",
        )

    def model_tags(self):
        try:
            response = self.http.get("http://127.0.0.1:11434/api/tags", timeout=3)
            response.raise_for_status()
            value = response.json()
            if isinstance(value.get("models"), list):
                return value
        except (httpx.HTTPError, ValueError):
            pass
        return None

    def pull_local_model(self):
        # Small reproducible acceptance model; does not replace/import the user's other models.
        name = "qwen3:1.7b"
        print(
            "Downloading " + name + " (about 1.4 GB) for real local inference and repair. "
            "This is an acceptance model, not a quality recommendation. No cloud inference.",
            flush=True,
        )
        completed, last = False, 0
        with self.http.stream(
            "POST",
            "http://127.0.0.1:11434/api/pull",
            json={"model": name, "stream": True},
            timeout=300,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                event = json.loads(line)
                require(not event.get("error"), "Local model download failed; rerun to resume it")
                completed = event.get("status") == "success"
                if time.monotonic() - last > 5 or completed:
                    total, done = event.get("total", 0), event.get("completed", 0)
                    progress = f" {round(done * 100 / total)}%" if total else ""
                    print(
                        "  Model download: " + str(event.get("status", "working"))[:100] + progress,
                        flush=True,
                    )
                    last = time.monotonic()
        require(completed, "Local model download ended before verification; rerun to resume")

    def verified_models(self, entries):
        models = []
        entries = sorted(
            entries,
            key=lambda v: (
                "qwen3.5" not in v.get("name", ""),
                "abliterated" not in v.get("name", ""),
                v.get("size", 0),
            ),
        )
        for item in entries:
            name = item.get("name", "")
            if "cloud" in name.lower() or "://" in name or not item.get("size"):
                continue
            response = self.http.post("http://127.0.0.1:11434/api/show", json={"model": name})
            response.raise_for_status()
            info = response.json()
            if info.get("remote_host") or info.get("remote_model") or not info.get("model_info"):
                continue
            if ("capabilities" in info and "completion" not in info["capabilities"]) or not (
                re.fullmatch(r"[a-f0-9]{64}", item.get("digest", "").removeprefix("sha256:"))
            ):
                continue
            models.append(
                {
                    "id": f"acceptance-local-{len(models)}",
                    "name": name,
                    "runtime": "ollama",
                    "endpoint": "http://127.0.0.1:11434",
                    "runtime_model": name,
                    "context": 8192,
                    "output_tokens": 1024,
                    "abliterated": "abliterated" in name.lower(),
                    "expected_digest": item["digest"].removeprefix("sha256:"),
                }
            )
            if len(models) == 2:
                break
        return models

    def install_ollama_runtime(self):
        if self.args.ci or os.name != "nt":
            raise Blocked("Automatic Windows runtime setup is disabled in CI/on this OS.")
        cache = Path(os.environ["LOCALAPPDATA"]) / "dsGPT-Acceptance/dependencies"
        result = install_ollama(self.http, cache, lambda message: print(message, flush=True))
        self.report["local_runtime_setup"] = {
            "strategy": "standalone_cli",
            "version": OLLAMA["version"],
            "publisher_archive_sha256": OLLAMA["sha256"],
            "desktop_app_launched": False,
            "account_required": False,
        }
        self.save()
        return str(result)

    def discover_models(self):
        print(
            "Preparing local inference automatically. "
            "No Ollama account or setup clicks are needed.",
            flush=True,
        )
        tags = self.model_tags()
        self.report["local_runtime_setup"] = {
            "strategy": "existing_local_server" if tags is not None else "existing_cli",
            "desktop_app_launched": False,
            "account_required": False,
        }
        if tags is None:
            candidates = [
                Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Ollama/ollama.exe",
                Path(os.environ.get("ProgramFiles", "")) / "Ollama/ollama.exe",
            ]
            ollama = executable("ollama", candidates)
            if not ollama:
                ollama = self.install_ollama_runtime()
            require(bool(ollama), "Automatic setup did not produce the Ollama engine")
            # A loopback-only server, with cloud models disabled for the process we own.
            env = dict(os.environ, OLLAMA_HOST="127.0.0.1:11434", OLLAMA_NO_CLOUD="1")
            self.spawn([ollama, "serve"], env)
            tags = wait_ready(
                lambda: (self.model_tags(), "Waiting for the local Ollama server."),
                "Starting local inference",
                ci=self.args.ci,
            )
        self.models = self.verified_models(tags["models"])
        downloaded = False
        if not self.models and not self.args.ci:
            self.pull_local_model()
            tags = self.model_tags()
            self.models = self.verified_models(tags["models"] if tags else [])
            downloaded = True
        if not self.models:
            raise Blocked(
                "No verified local model is available; automatic downloads are off in CI."
            )
        return {
            "models": [m["name"] for m in self.models],
            "hosted_inference": False,
            "downloaded_acceptance_model": downloaded,
        }

    def tailscale_setup(self):
        self.tailscale = executable(
            "tailscale", [Path(os.environ.get("ProgramFiles", "")) / "Tailscale/tailscale.exe"]
        )
        if not self.tailscale:
            self.vendor_install("Tailscale.Tailscale")
            self.tailscale = executable(
                "tailscale", [Path(os.environ.get("ProgramFiles", "")) / "Tailscale/tailscale.exe"]
            )
        require(bool(self.tailscale), "Tailscale installation did not produce its CLI")
        started = False
        opened = set()

        def probe():
            nonlocal started
            result = command([self.tailscale, "status", "--json"], 15)
            try:
                status = json.loads(result.stdout)
            except ValueError:
                status = {}
            auth_url = status.get("AuthURL", "")
            if (
                re.fullmatch(r"https://login\.tailscale\.com/[A-Za-z0-9/?=&_.%-]+", auth_url)
                and auth_url not in opened
            ):
                import webbrowser

                self.secrets.append(auth_url)
                webbrowser.open(auth_url)
                opened.add(auth_url)
            state = status.get("BackendState", "Unavailable")
            dns = (status.get("Self") or {}).get("DNSName", "").rstrip(".")
            if state == "Running" and re.fullmatch(r"[\w.-]+\.ts\.net", dns):
                self.tailnet = dns
                return True, "PC Tailscale is connected."
            if not started:
                # set --accept-routes etc. is deliberately avoided; keep existing network choices.
                if state == "Stopped":
                    self.spawn([self.tailscale, "up", "--timeout=30s"])
                elif state in {"NeedsLogin", "NoState"}:
                    self.spawn([self.tailscale, "up", "--timeout=30s"])
                    ui = Path(self.tailscale).with_name("tailscale-ipn.exe")
                    if ui.is_file():
                        subprocess.Popen(
                            [str(ui)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                        )
                started = True
            return None, (
                "PC Tailscale state: " + state + ". Open its tray icon > Connect/Log in "
                "if requested. On the Pixel, Tailscale must also say Connected "
                "using the same account. This window keeps checking."
            )

        wait_ready(probe, "Private connection setup", ci=self.args.ci)
        return {"pc_connected": True, "phone_route": "checked separately by the phone test"}

    def start_backend(self):
        from dsgpt.security import Auth
        from dsgpt.storage import Store

        if not self.token:
            data = self.private / "backend"
            self.token = Auth(Store(data)).initialize_owner()["token"]
            self.secrets.append(self.token)
            self.backend_port = port()
            self.origin = f"http://127.0.0.1:{self.backend_port}"
            hosts = ["127.0.0.1", "localhost", "[::1]"]
            self.tailscale = executable(
                "tailscale", [Path(os.environ.get("ProgramFiles", "")) / "Tailscale/tailscale.exe"]
            )
            if self.tailscale:
                try:
                    status = json.loads(command([self.tailscale, "status", "--json"], 15).stdout)
                    dns = status.get("Self", {}).get("DNSName", "").rstrip(".")
                    if status.get("BackendState") == "Running" and re.fullmatch(
                        r"[\w.-]+\.ts\.net", dns
                    ):
                        self.tailnet = dns
                        hosts.append(dns)
                except (ValueError, subprocess.TimeoutExpired):
                    pass
            self.config = self.private / "backend-config.json"
            self.config.write_text(
                json.dumps(
                    {
                        "data": str(data),
                        "port": self.backend_port,
                        "hosts": hosts,
                        "models": [
                            {
                                "id": FIXTURE,
                                "name": "Acceptance fixture",
                                "runtime": "ollama",
                                "endpoint": "http://127.0.0.1:11434",
                                "runtime_model": "fixture",
                            },
                            *self.models,
                        ],
                    }
                ),
                encoding="utf-8",
            )
        self.backend = self.spawn(
            [sys.executable, "-I", "-m", "dsgpt_acceptance", "--backend", self.config]
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                models = self.api("GET", "/v1/models")
                return {"model_count": len(models), "data": "separate synthetic database"}
            except httpx.TransportError:
                time.sleep(0.2)
        raise AssertionError("Isolated backend failed to start within 30 seconds")

    def submit(self, model=FIXTURE, content="Reply with ACCEPTANCE only."):
        chat = self.api(
            "POST", "/v1/conversations", {"title": "Acceptance synthetic chat"}, expected=201
        )
        body = {"request_id": str(uuid.uuid4()), "content": content, "model_id": model}
        path = f"/v1/conversations/{chat['id']}/messages"
        run = self.api("POST", path, body, expected=202)
        return chat, body, run

    def wait_run(self, run, timeout=60, on_poll=None):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            item = self.api("GET", f"/v1/runs/{run['id']}")
            if on_poll:
                on_poll(item)
            if item["status"] in {"completed", "failed", "cancelled", "interrupted"}:
                return item
            time.sleep(0.25)
        raise AssertionError("Generation exceeded its acceptance time limit")

    def run_evidence(self, run):
        """Replay only terminal-run counters; never copy answer or reasoning text."""
        from dsgpt.diagnostic_details import ERROR_HELP, METRICS
        from dsgpt.hardware import number

        result = {k: run.get(k) for k in ("id", "status", "created_at", "updated_at")}
        code = run.get("error_code")
        result["error_code"] = (
            code if code in ERROR_HELP else "unclassified_failure" if code else None
        )
        result["metrics"], result["warnings"] = {}, []
        if run["status"] not in {"completed", "failed", "cancelled", "interrupted"}:
            return result
        with self.http.stream(
            "GET",
            self.origin + f"/v1/runs/{run['id']}/events",
            headers={"Authorization": "Bearer " + self.token},
        ) as response:
            require(response.status_code == 200, "Run evidence replay failed")
            kind = None
            for line in response.iter_lines():
                if line.startswith("event: "):
                    kind = line[7:]
                elif line.startswith("data: ") and kind in {"metrics", "timing", "warning"}:
                    data = json.loads(line[6:])
                    if kind == "warning":
                        if data.get("code") in ERROR_HELP:
                            result["warnings"].append(data["code"])
                    else:
                        for key in METRICS:
                            value = number(data.get(key), 1e18)
                            if value is not None:
                                result["metrics"][key] = value
        return result

    def backend_checks(self):
        chat, body, run = self.submit()
        path = f"/v1/conversations/{chat['id']}"
        require(
            self.api("POST", path + "/messages", body, expected=202)["id"] == run["id"],
            "Idempotent message submission duplicated a run",
        )
        # Open and drop a real SSE connection; generation must continue independently.
        with self.http.stream(
            "GET",
            self.origin + f"/v1/runs/{run['id']}/events",
            headers={"Authorization": "Bearer " + self.token},
        ) as response:
            require(response.status_code == 200, "SSE stream rejected")
            require(
                any(line.startswith("data:") for line in response.iter_lines()), "No streamed event"
            )
        require(self.wait_run(run)["status"] == "completed", "Disconnected stream lost the reply")
        messages = self.api("GET", path + "/messages")
        require(
            len(messages) == 2 and "ACCEPTANCE" in messages[1]["content"],
            "Reply was lost or duplicated",
        )
        chat = self.api("GET", path)
        patched = self.api(
            "PATCH",
            path,
            {
                "revision": chat["revision"],
                "title": "ACCEPTANCE-RENAMED",
                "pinned": True,
                "hidden": True,
            },
        )
        self.api("PATCH", path, {"revision": chat["revision"], "title": "stale"}, expected=409)
        require(not self.api("GET", "/v1/conversations?q=ACCEPTANCE-RENAMED"), "Hidden chat leaked")
        require(
            self.api("GET", "/v1/conversations?hidden=true&q=ACCEPTANCE-RENAMED")[0]["pinned"],
            "Hidden pinned chat was not searchable",
        )
        self.stop(self.backend)
        self.start_backend()
        require(
            self.api("GET", path)["revision"] == patched["revision"], "Restart lost chat revision"
        )
        require(self.api("GET", path + "/messages") == messages, "Restart changed saved history")
        _, _, cancel = self.submit()
        self.api("POST", f"/v1/runs/{cancel['id']}/cancel")
        require(self.wait_run(cancel)["status"] == "cancelled", "Cancellation failed")
        code = self.api("POST", "/v1/pairings", {"scopes": ["chat", "diagnostics"]})["code"]
        self.secrets.append(code)
        device = self.api(
            "POST", "/v1/pairings/redeem", {"code": code, "name": "Acceptance device"}
        )
        self.secrets.append(device["token"])
        self.api("GET", "/v1/device", token=device["token"])
        device_id = self.api("GET", "/v1/device", token=device["token"])["id"]
        self.api("POST", "/v1/pairings/redeem", {"code": code, "name": "Duplicate"}, expected=401)
        self.api("DELETE", "/v1/devices/" + device_id)
        self.api("GET", "/v1/device", token=device["token"], expected=401)
        self.collect_backend_diagnostics()
        return {
            "stream_disconnect_continues": True,
            "duplicate_suppressed": True,
            "history_survives_restart": True,
            "pin_rename_hide_search_conflict": True,
            "cancel": True,
            "pair_replay_revoke": True,
            "reviewed_export_no_credentials": True,
        }

    def collect_backend_diagnostics(self):
        self.api("POST", "/v1/diagnostics/snapshots", expected=201)
        preview = self.api("POST", "/v1/diagnostics/exports/preview", {})
        response = self.http.get(
            self.origin + f"/v1/diagnostics/exports/{preview['id']}",
            params={"sha256": preview["sha256"]},
            headers={"Authorization": "Bearer " + self.token},
        )
        require(response.status_code == 200, "Reviewed diagnostics export failed")
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            text = b"\n".join(z.read(n) for n in z.namelist())
            require(
                all(s.encode() not in text for s in self.secrets),
                "Credential leaked into diagnostics",
            )
        (self.share / "backend-diagnostics.zip").write_bytes(response.content)
        return {"refreshed_after_tests": True, "credentials_excluded": True}

    def local_models(self):
        if not self.models:
            raise Blocked(
                "A verified local Ollama model is required; other tests use a labeled fixture."
            )
        evidence = []
        try:
            for model in self.models:
                started = time.monotonic()
                observed = {
                    "model": model["name"],
                    "gpu_resident_bytes": 0,
                    "resident_samples": 0,
                    "sampling_errors": 0,
                    "completed_through_dsgpt": False,
                    "measurement": "peak during the dsGPT generation, before automatic unload",
                }
                evidence.append(observed)

                def sample(item, model=model, observed=observed):
                    try:
                        response = self.http.get("http://127.0.0.1:11434/api/ps", timeout=3)
                        response.raise_for_status()
                        for local in response.json().get("models", []):
                            digest = local.get("digest", "").removeprefix("sha256:")
                            if digest != model["expected_digest"]:
                                continue
                            observed["resident_samples"] += 1
                            observed["gpu_resident_bytes"] = max(
                                observed["gpu_resident_bytes"], local.get("size_vram", 0)
                            )
                    except (httpx.HTTPError, ValueError, TypeError):
                        observed["sampling_errors"] += 1

                _, _, run = self.submit(
                    model["id"], "Reply with the number that equals two plus two. Be brief."
                )
                item = self.wait_run(run, 300, on_poll=sample)
                observed.update(
                    seconds=round(time.monotonic() - started, 2),
                    completed_through_dsgpt=item["status"] == "completed",
                    error_code=item.get("error_code"),
                )
                require(
                    observed["completed_through_dsgpt"],
                    "Real local inference failed: " + str(item.get("error_code")),
                )
            require(
                any(r["gpu_resident_bytes"] > 0 for r in evidence),
                "No GPU residency was observed during inference; see local-model-inference.json",
            )
            return {
                "models": evidence,
                "scope": "Smoke benchmark; not broad model-quality qualification",
            }
        finally:
            (self.share / "local-model-inference.json").write_text(
                json.dumps(self.clean({"models": evidence}), indent=2), encoding="utf-8"
            )

    def native_client(self):
        if os.name != "nt":
            raise Blocked("Native client checks require Windows.")
        if not self.backend:
            raise Blocked("The isolated backend must be available.")
        target = self.kit / "client/dsGPT.exe"
        require(target.is_file(), "Windows client missing from kit")
        webviews = [
            Path(os.environ.get(var, "")) / "Microsoft/EdgeWebView/Application"
            for var in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")
        ]
        if not any(any(root.glob("*/msedgewebview2.exe")) for root in webviews):
            self.vendor_install("Microsoft.EdgeWebView2Runtime")
        debug_port = port()
        env = dict(
            os.environ,
            DSGPT_ACCEPTANCE_RUN_ID=self.id,
            DSGPT_ACCEPTANCE_PROFILE=str(self.private / ("webview-" + self.id)),
            WEBVIEW2_USER_DATA_FOLDER=str(self.private / ("webview-" + self.id)),
            WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=f"--remote-debugging-port={debug_port} "
            "--remote-debugging-address=127.0.0.1",
        )
        client = None
        cdp = None

        def open_client():
            # Do not connect a new check to a WebView that is still closing.
            debug_port = port()
            env["DSGPT_ACCEPTANCE_DEBUG_PORT"] = str(debug_port)
            env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = (
                f"--remote-debugging-port={debug_port} --remote-debugging-address=127.0.0.1"
            )
            child = self.spawn([target], env)
            deadline = time.monotonic() + 50
            while time.monotonic() < deadline:
                try:
                    pages = self.http.get(f"http://127.0.0.1:{debug_port}/json/list").json()
                    page = next(
                        v
                        for v in pages
                        if v.get("type") == "page"
                        and ("tauri" in v.get("url", "") or "localhost" in v.get("url", ""))
                    )
                    connection = CDP(page["webSocketDebuggerUrl"])
                    if (
                        connection.evaluate("typeof window.__TAURI_INTERNALS__?.invoke")
                        == "function"
                    ):
                        return child, connection
                    connection.close()
                except (httpx.HTTPError, ValueError, StopIteration, OSError):
                    pass
                time.sleep(0.3)
            self.stop(child)
            raise Blocked(
                "Windows client/WebView2 could not open. Install Microsoft Edge WebView2 "
                "Runtime if missing, allow this preview to run, then rerun."
            )

        def invoke(name, args=None):
            return cdp.evaluate(
                "window.__TAURI_INTERNALS__.invoke("
                + json.dumps(name)
                + ","
                + json.dumps(args or {})
                + ")"
            )

        def wait_ui(expression):
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                if cdp.evaluate(expression):
                    return
                time.sleep(0.2)
            raise AssertionError("Native client UI did not reach the expected state")

        def stage(name):
            # Fixed labels only: no expressions, credentials, URLs or page content.
            self.report["native_client_stage"] = name
            self.save()

        try:
            stage("open_isolated_webview")
            client, cdp = open_client()
            stage("credential_roundtrip")
            invoke("connect", {"origin": self.origin, "token": self.token})
            require(
                invoke("restore_connection") == self.origin, "Credential Manager write/read failed"
            )
            require(
                invoke("api_request", {"path": "/v1/models", "method": "GET", "body": None}),
                "Native authenticated request failed",
            )
            cdp.close()
            cdp = None
            self.stop(client)
            time.sleep(1)
            stage("restore_after_restart")
            client, cdp = open_client()
            require(
                invoke("restore_connection") == self.origin, "Credential lost across app restart"
            )
            require(
                invoke("api_request", {"path": "/v1/conversations", "method": "GET", "body": None})
                is not None,
                "Native request failed after reopening",
            )
            require(cdp.evaluate("document.body.innerText.length") > 50, "Client UI did not render")
            stage("submit_chat_through_ui")
            wait_ui("!!document.querySelector('textarea[aria-label=Message]')")
            cdp.evaluate(
                "document.querySelector('button[aria-label=\"New chat\"]').click()"
            )
            cdp.evaluate(
                "(() => { const s=document.querySelector('select[aria-label=Model]'); "
                "Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value')"
                ".set.call(s,'acceptance-fixture'); "
                "s.dispatchEvent(new Event('change',{bubbles:true})); })()"
            )
            cdp.evaluate(
                "(() => { const t=document.querySelector('textarea[aria-label=Message]'); "
                "Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value')"
                ".set.call(t,'Synthetic Windows UI acceptance'); "
                "t.dispatchEvent(new Event('input',{bubbles:true})); })()"
            )
            wait_ui(
                "!!document.querySelector('button[aria-label=\"Send ↑\"]:not(:disabled)')"
            )
            cdp.evaluate(
                "document.querySelector('button[aria-label=\"Send ↑\"]:not(:disabled)').click()"
            )
            wait_ui(
                "[...document.querySelectorAll('article')].some(a => "
                "a.innerText.includes('ACCEPTANCE'))"
            )
            stage("revoke_acceptance_credential")
            invoke("disconnect")
            require(invoke("restore_connection") is None, "Acceptance credential cleanup failed")
            stage("completed")
            return {
                "real_webview": True,
                "credential_manager_roundtrip": True,
                "credential_restored_after_restart": True,
                "native_authenticated_requests": True,
                "real_ui_message_submission_and_reply": True,
                "production_credential_untouched": True,
            }
        finally:
            if cdp:
                with contextlib.suppress(Exception):
                    invoke("disconnect")
                cdp.close()
            self.stop(client)

    def live_script(self, name, args=(), timeout=900, evidence_name=None):
        label = evidence_name or name
        output = self.private / (label + ".json")
        result = command(
            [
                sys.executable,
                "-I",
                self.kit / "scripts" / (name + ".py"),
                *args,
                "--output",
                output,
            ],
            timeout,
            cwd=self.private,
        )
        raw = result.stdout + result.stderr
        (self.private / (label + ".log")).write_bytes(raw)
        (self.share / (label + "-log.txt")).write_text(
            self.clean(raw[-32768:].decode(errors="replace")), encoding="utf-8"
        )
        require(
            result.returncode == 0 and output.is_file(),
            label + " failed; sanitized command output is in the report",
        )
        payload = json.loads(output.read_text())
        require(payload.get("passed"), name + " did not report success")
        safe = self.clean(payload)
        (self.share / (label + ".json")).write_text(json.dumps(safe, indent=2), encoding="utf-8")
        return {"evidence": label + ".json", "passed": True}

    def docker_cli(self, args, timeout=60):
        endpoint = (
            "npipe:////./pipe/docker_engine" if os.name == "nt" else "unix:///var/run/docker.sock"
        )
        environment = {
            key: os.environ[key]
            for key in (
                "SystemRoot",
                "WINDIR",
                "ProgramFiles",
                "ProgramFiles(x86)",
                "TEMP",
                "TMP",
                "PATHEXT",
                "SYSTEMDRIVE",
            )
            if key in os.environ
        }
        environment.update(PATH=os.defpath, LANG="C", LC_ALL="C")
        return command(
            [self.docker, "--config", self.private / "docker-config", "--host", endpoint, *args],
            timeout,
            env=environment,
        )

    def docker_ready(self):
        candidates = [root / "resources/bin/docker.exe" for root in docker_locations()]
        docker = executable("docker", candidates)
        if not docker:
            self.vendor_install("Docker.DockerDesktop")
            docker = executable("docker", candidates)
        require(bool(docker), "Docker installer finished but its executable was not found")
        os.environ["PATH"] = str(Path(docker).parent) + os.pathsep + os.environ.get("PATH", "")
        self.docker = docker
        (self.private / "docker-config").mkdir(exist_ok=True)
        (self.private / "docker-config/config.json").write_bytes(b"{}\n")
        initial = self.docker_cli(["info", "--format", "{{.OSType}}"], 20)
        if initial.returncode and os.name == "nt":
            self.resume_setup(True)
            wsl = command(["wsl.exe", "--status"], 30)
            if wsl.returncode:
                print(
                    "Preparing Windows Subsystem for Linux for Docker. "
                    "Approve the Windows permission prompt if asked.",
                    flush=True,
                )
                result = elevated(command, "wsl.exe", ["--install", "--no-distribution"], 1800)
                if result.returncode in {0, 1641, 3010}:
                    raise RestartRequired(
                        "Windows Linux support was installed. Save work and "
                        "restart Windows; this kit will reopen after sign-in."
                    )
                raise Blocked(
                    "Windows Linux setup did not complete (exit "
                    + str(result.returncode)
                    + "). Check its installer window."
                )
            desktop = next(
                (
                    root / "Docker Desktop.exe"
                    for root in docker_locations()
                    if (root / "Docker Desktop.exe").is_file()
                ),
                None,
            )
            if desktop:
                subprocess.Popen(
                    [str(desktop)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
        switched = False

        def ready():
            nonlocal switched
            info = self.docker_cli(["info", "--format", "{{.OSType}}"], 15)
            if info.returncode == 0 and info.stdout.strip() == b"linux":
                return True, "Docker Linux engine is ready."
            if info.returncode == 0 and info.stdout.strip() == b"windows" and not switched:
                switcher = next(
                    (
                        root / "DockerCli.exe"
                        for root in docker_locations()
                        if (root / "DockerCli.exe").is_file()
                    ),
                    None,
                )
                if switcher:
                    command([switcher, "-SwitchLinuxEngine"], 120)
                switched = True
            return None, (
                "Waiting for Docker's Linux engine. A Docker account is not required. "
                "The installer configures the local engine automatically. "
                "No Docker account is needed for these checks. "
                "If Windows requests a restart, save work and restart; the kit "
                "reopens after sign-in. Keep this window open otherwise."
            )

        wait_ready(ready, "Docker startup", ci=self.args.ci, timeout=180)
        return {"linux_containers": True}

    def docker_setup(self):
        self.docker_ready()
        tag = "dsgpt-acceptance-toolchain:" + self.report.get("source_commit", "local")[:12]
        result = self.docker_cli(["image", "inspect", "--format", "{{.Id}}", tag])
        if result.returncode:
            print("Building the isolated toolchain; first run may download several GB.", flush=True)
            result = self.docker_cli(
                [
                    "build",
                    "--build-arg",
                    "DSGPT_BASE_IMAGE=python@sha256:2ed6491b93cd49272ee6de2b5a38440c3448360322c089fc23e370722d74179d",
                    "-t",
                    tag,
                    "-f",
                    self.kit / "execution/Dockerfile",
                    self.kit / "execution",
                ],
                1800,
            )
            (self.private / "docker-build.log").write_bytes(result.stdout + result.stderr)
            require(result.returncode == 0, "Docker toolchain build failed")
        image = (
            self.docker_cli(["image", "inspect", "--format", "{{.Id}}", tag])
            .stdout.decode()
            .strip()
        )
        require(bool(re.fullmatch(r"sha256:[a-f0-9]{64}", image)), "Invalid Docker image identity")
        self.image = image
        return {"linux_containers": True, "image": image, "cache_kept_for_reruns": tag}

    def docker_script(self, name, extra=()):
        if not getattr(self, "image", None):
            raise Blocked("The Docker toolchain must be ready first.")
        return self.live_script(name, ["--image", self.image, *extra])

    def android_build(self):
        if not getattr(self, "image", None):
            raise Blocked("The Linux Docker toolchain must be available first.")
        tag = "dsgpt-acceptance-android:" + self.report["source_commit"][:12]
        result = self.docker_cli(["image", "inspect", "--format", "{{.Id}}", tag])
        if result.returncode:
            context = self.private / "android-toolchain"
            inputs = self.private / "android-inputs.json"
            result = command(
                [
                    sys.executable,
                    "-B",
                    "-I",
                    self.kit / "scripts/prepare_android_toolchain.py",
                    "--directory",
                    context,
                    "--output",
                    inputs,
                ],
                600,
            )
            require(result.returncode == 0, "Pinned Android SDK input download failed")
            result = self.docker_cli(
                [
                    "build",
                    "--build-arg",
                    "DSGPT_BASE_IMAGE=python@sha256:2ed6491b93cd49272ee6de2b5a38440c3448360322c089fc23e370722d74179d",
                    "-t",
                    tag,
                    "-f",
                    context / "Android.Dockerfile",
                    context,
                ],
                1800,
            )
            (self.private / "android-build.log").write_bytes(result.stdout + result.stderr)
            require(result.returncode == 0, "Android Docker toolchain build failed")
        image = (
            self.docker_cli(["image", "inspect", "--format", "{{.Id}}", tag])
            .stdout.decode()
            .strip()
        )
        return self.live_script(
            "live_isolated_build",
            ["--image", image, "--target", "apk"],
            evidence_name="live_apk_build",
        )

    def local_work(self):
        if not self.models or not getattr(self, "image", None):
            raise Blocked("A verified local model and Linux Docker toolchain are required.")
        config = json.loads(self.config.read_text())
        config["image"] = self.image
        self.config.write_text(json.dumps(config), encoding="utf-8")
        self.stop(self.backend)
        self.start_backend()
        self.api("POST", "/v1/work/sandbox/probe")
        model = self.models[0]["id"]
        requirements = (
            "Repair and compile the existing hello.c as a Windows EXE. First compile unchanged "
            "to observe the real error. Every compile MUST use run with argv "
            '["sh", "-c", "sleep 45; x86_64-w64-mingw32-gcc hello.c -o hello.exe"] '
            'and artifacts ["hello.exe"]. The sleep is required for a concurrency test. '
            "After observing the error, correct the missing semicolon using write_file and "
            "the current expected_sha256. Compile again and finish after collecting the EXE. "
            "Preserve DSGPT_ACCEPTANCE_BUILD. Do not repeat a successful build."
        )
        task = self.api(
            "POST",
            "/v1/work/tasks",
            {
                "title": "Synthetic local model compiler repair",
                "requirements": requirements,
                "model_id": model,
                "build_target": "exe",
                "source_files": [
                    {
                        "name": "hello.c",
                        "text": "#include <stdio.h>\n"
                        'int main(void){puts("DSGPT_ACCEPTANCE_BUILD") return 0;}\n',
                    }
                ],
            },
            expected=201,
        )
        path = "/v1/work/tasks/" + task["id"]
        self.api("POST", path + "/actions", {"action": "start", "revision": task["revision"]})
        concurrent = {"attempted": False, "completed_during_build": False}
        started = time.monotonic()
        progress = None
        try:
            while time.monotonic() - started < 900:
                task = self.api("GET", path)
                current = (task["status"], (task.get("session") or {}).get("step", 0))
                if current != progress:
                    print(f"  Local Work: {current[0]}, step {current[1]}", flush=True)
                    progress = current
                executions = self.api("GET", path + "/executions")
                active = next((v for v in executions if v["status"] == "running"), None)
                if active and not concurrent["attempted"]:
                    concurrent = self.chat_during_build(model, path, active)
                if task["status"] in {"completed", "blocked", "stopped"} or current[1] > 24:
                    break
                time.sleep(0.5)
            steps = self.api("GET", path + "/steps")
            commands = [v["result"] for v in steps if v["action"].get("tool") == "run"]
            results = {
                "completed": task["status"] == "completed",
                "real_compile_error": bool(commands and commands[0].get("exit_code", 0) > 0),
                "repaired_compile": bool(len(commands) >= 2 and commands[-1].get("exit_code") == 0),
            }
            artifacts = self.api("GET", path + "/artifacts")
            results["artifact_verified"] = False
            if artifacts:
                artifact = artifacts[0]
                response = self.http.get(
                    self.origin + path + "/artifacts/" + artifact["id"],
                    headers={"Authorization": "Bearer " + self.token},
                )
                results["artifact_verified"] = (
                    response.status_code == 200
                    and response.content.startswith(b"MZ")
                    and hashlib.sha256(response.content).hexdigest() == artifact["sha256"]
                )
            self.local_work_evidence = {
                "checks": {
                    **results,
                    "chat_completed_during_build": concurrent["completed_during_build"],
                },
                "seconds": round(time.monotonic() - started, 2),
                "model": self.models[0]["name"],
                "synthetic_task": True,
                "task_status": task["status"],
                "session": self.clean(task.get("session")),
                # Only this runner-created synthetic task; never general user Work.
                "steps": self.clean(steps[-25:]),
                "concurrent_chat": concurrent,
            }
            (self.share / "local-model-work.json").write_text(
                json.dumps(
                    self.local_work_evidence,
                    indent=2,
                ),
                encoding="utf-8",
            )
            require(
                all(results.values()),
                "Local model repair failed: "
                + ", ".join(key for key, passed in results.items() if not passed)
                + "; see local-model-work.json",
            )
            return results
        finally:
            task = self.api("GET", path)
            if task["status"] not in {"completed", "stopped"}:
                self.api(
                    "POST", path + "/actions", {"action": "stop", "revision": task["revision"]}
                )

    def chat_during_build(self, model, path, active):
        result = {
            "attempted": True,
            "completed_during_build": False,
            "build_execution_id": active["id"],
            "build_status_before": active["status"],
            "build_created_at": active.get("created_at"),
        }
        started = time.monotonic()
        run = None
        try:
            _, _, run = self.submit(model, "Reply with READY only.")
            result["run_id"] = run["id"]
            reply = self.wait_run(run, 300)
            # Take the overlap observation before replaying metrics, which takes extra time.
            after = self.api("GET", path + "/executions/" + active["id"])
            result.update(
                run_status=reply["status"],
                error_code=reply.get("error_code"),
                build_status_after=after["status"],
                build_updated_at=after.get("updated_at"),
                completed_during_build=reply["status"] == "completed"
                and after["status"] == "running",
            )
            result["run"] = self.run_evidence(reply)
        except (AssertionError, httpx.HTTPError, ValueError):
            # A failed Chat probe must not discard an independently successful repair.
            result["probe_error"] = "chat_probe_or_evidence_failed"
            if run:
                with contextlib.suppress(AssertionError, httpx.HTTPError):
                    self.api("POST", f"/v1/runs/{run['id']}/cancel")
        result["seconds"] = round(time.monotonic() - started, 3)
        return result

    def local_work_chat(self):
        if not self.local_work_evidence:
            raise Blocked("The local model repair test did not produce concurrency evidence.")
        result = self.local_work_evidence["concurrent_chat"]
        if not result["attempted"]:
            raise Blocked(
                "The local model did not start a compiler execution to test Chat against."
            )
        require(
            result["completed_during_build"] and not result.get("probe_error"),
            "Concurrent Chat did not pass: "
            + (
                result.get("probe_error")
                or result.get("error_code")
                or result.get("run_status", "unknown")
            )
            + "; see concurrent_chat in local-model-work.json and final backend diagnostics",
        )
        return result

    def adb(self, *args, timeout=60):
        return command([self.adb_bin, *(["-s", self.phone] if self.phone else []), *args], timeout)

    def wireless_pairing(self):
        def connected():
            devices = adb_devices(command([self.adb_bin, "devices", "-l"], 15).stdout)
            return any(state == "device" and wireless_serial(serial) for serial, state in devices)

        if connected():
            return
        if self.args.ci or not sys.stdin.isatty():
            raise Blocked(
                "Wireless debugging needs Android pairing in an interactive window first."
            )
        print(
            "Wireless phone testing: keep the PC and Pixel on your home network.\n"
            "On the Pixel open Settings > System > Developer options > Wireless debugging.\n"
            "Turn it on and approve your home network. USB is not needed for this option.\n"
            "If this PC is already under Paired devices, enter C to connect.\n"
            "Otherwise press Enter to pair this PC now. Enter S to skip.",
            flush=True,
        )
        choice = input("Pair [Enter], connect existing [C], skip [S]: ").strip().lower()
        if choice == "s":
            raise Blocked("Wireless phone setup skipped by user.")

        def endpoint(prompt):
            while True:
                value = input(prompt).strip()
                if value.lower() == "s":
                    raise Blocked("Wireless phone setup skipped by user.")
                try:
                    result = wireless_endpoint(value)
                    self.secrets.extend([result, result.rpartition(":")[0]])
                    return result
                except ValueError:
                    print("Enter the IP address and port shown on your phone, or S to skip.")

        if choice != "c":
            import getpass

            while True:
                print(
                    "On the Pixel tap Pair device with pairing code. Keep that popup open.",
                    flush=True,
                )
                code = getpass.getpass("Six-digit Wi-Fi pairing code (hidden): ").strip()
                if code.lower() == "s":
                    raise Blocked("Wireless pairing skipped by user.")
                if not re.fullmatch(r"[0-9]{6}", code):
                    print("Use the six digits from the phone's pairing popup.")
                    continue
                self.secrets.append(code)
                discovered = pairing_endpoints(
                    command([self.adb_bin, "mdns", "services"], 15).stdout
                )
                pair_address = (
                    discovered[0]
                    if len(discovered) == 1
                    else endpoint("Pairing popup IP address & port: ")
                )
                self.secrets.append(pair_address)
                try:
                    result = subprocess.run(
                        [self.adb_bin, "pair", pair_address],
                        input=(code + "\n").encode(),
                        capture_output=True,
                        timeout=30,
                    )
                except subprocess.TimeoutExpired:
                    print("Pairing timed out. Keep the phone's pairing popup open and try again.")
                    continue
                if result.returncode == 0 and b"Successfully paired" in result.stdout:
                    print("Paired. Looking for the phone automatically...", flush=True)
                    for _ in range(5):
                        if connected():
                            return
                        time.sleep(2)
                    break
                print(
                    "Pairing did not finish. Reopen the pairing popup and use its current "
                    "address, port and code; expired codes cannot be reused.",
                    flush=True,
                )
        # Networks which block mDNS still work with the phone's explicit TLS connection port.
        while True:
            address = endpoint(
                "Main Wireless debugging screen IP address & port (different from pairing popup): "
            )
            result = command([self.adb_bin, "connect", address], 20)
            if result.returncode == 0 and b"connected to" in result.stdout.lower():
                return
            print(
                "Wireless connection did not finish. Check the main screen's current port "
                "and home Wi-Fi, then try again (or S to skip).",
                flush=True,
            )

    def phone_detect(self):
        self.phone = None
        candidate = self.kit / "platform-tools/adb.exe"
        self.adb_bin = (
            str(candidate) if os.name == "nt" and candidate.is_file() else executable("adb")
        )
        if not self.adb_bin:
            raise Blocked("Bundled Android platform tools are missing; extract the complete kit.")
        wireless = getattr(self.args, "wireless", False)
        print(
            "Checking Android wireless debugging; no USB cable is required."
            if wireless
            else "Checking the Pixel. If it already says 'USB debugging connected', "
            "a new authorization prompt may not be needed.",
            flush=True,
        )
        # Starting ADB is what requests authorization, not simply enabling the phone toggle.
        started = self.adb("start-server", timeout=20)
        require(started.returncode == 0, "ADB could not start on this PC")
        if wireless:
            self.wireless_pairing()
        repair_attempted = False
        reconnect_attempted = False

        def probe():
            nonlocal repair_attempted, reconnect_attempted
            result = command([self.adb_bin, "devices", "-l"], 15)
            devices = adb_devices(result.stdout)
            if wireless:
                devices = [(serial, state) for serial, state in devices if wireless_serial(serial)]
            states = [state for _, state in devices]
            snapshot = {
                "states": states,
                "device_count": len(devices),
                "adb_exit": result.returncode,
            }
            if not self.phone_states or self.phone_states[-1] != snapshot:
                self.phone_states.append(snapshot)
                (self.share / "phone-connection.json").write_text(
                    json.dumps({"observations": self.phone_states}, indent=2), encoding="utf-8"
                )
                self.save()
            if len(devices) == 1 and devices[0][1] == "device":
                selected = devices[0][0]
                self.secrets.append(selected)
                ready = command([self.adb_bin, "-s", selected, "shell", "echo", "DSGPT_READY"], 15)
                if ready.returncode == 0 and ready.stdout.strip() == b"DSGPT_READY":
                    return selected, "Authorized Pixel connection verified."
            if "offline" in states and not reconnect_attempted:
                command([self.adb_bin, "reconnect", "offline"], 15)
                reconnect_attempted = True
            if (
                not devices
                and not repair_attempted
                and os.name == "nt"
                and not self.args.ci
                and not wireless
            ):
                repair_attempted = True
                inventory = google_usb_inventory(command)
                try:
                    details = json.loads(inventory.stdout)
                except ValueError:
                    details = {"inventory_available": False}
                self.report["usb_driver"] = details
                driver = self.kit / "usb_driver/android_winusb.inf"
                if driver.is_file():
                    print(
                        "Installing the bundled Google USB driver for matching devices. "
                        "Approve the Windows permission prompt. Detection resumes automatically.",
                        flush=True,
                    )
                    installed = elevated(
                        command, "pnputil.exe", ["/add-driver", str(driver), "/install"]
                    )
                    self.report["usb_driver"]["installer_exit"] = installed.returncode
                    if installed.returncode in {1641, 3010}:
                        self.resume_setup(True)
                        raise RestartRequired(
                            "Windows needs a restart for the Google USB driver. "
                            "Save work and restart; the kit will reopen."
                        )
            detail = (
                "Keep Wireless debugging enabled on the Pixel and both devices on the "
                "same home network. Reconnect using the main screen's current port if "
                "Android changes it."
                if wireless and not devices
                else adb_guidance(devices)
            )
            if result.returncode:
                detail = (
                    "ADB could not list devices (exit " + str(result.returncode) + "). " + detail
                )
            return None, detail

        self.phone = wait_ready(probe, "Pixel connection", ci=self.args.ci)
        self.phone_transport = (
            "wireless debugging" if wireless_serial(self.phone) else "USB debugging"
        )
        return {
            "authorized_shell_verified": True,
            "device_count": 1,
            "debug_transport": self.phone_transport,
        }

    def phone_setup(self):
        # Re-detect here too: the cable or authorization may have changed during downloads.
        self.phone_detect()
        prior = self.adb("shell", "pm", "path", PACKAGE).stdout.strip()
        if not prior:
            self.cleanup.append(lambda: self.adb("uninstall", PACKAGE))
        for name in ("app-debug.apk", "app-debug-androidTest.apk"):
            result = self.adb("install", "-r", "-t", self.kit / "android" / name, timeout=120)
            require(
                result.returncode == 0 and b"Success" in result.stdout,
                "Acceptance APK install rejected. Existing app/data were preserved.",
            )
        if not prior:
            self.cleanup.append(lambda: self.adb("uninstall", PACKAGE + ".test"))
        return {
            "android_api": self.adb("shell", "getprop", "ro.build.version.sdk")
            .stdout.decode()
            .strip(),
            "model": self.adb("shell", "getprop", "ro.product.model").stdout.decode().strip(),
            "separate_application_id": PACKAGE,
        }

    def instrument(self, class_name, extra=()):
        if not self.phone:
            raise Blocked("The Pixel must authorize this PC for USB or wireless debugging first.")
        result = self.adb(
            "shell",
            "am",
            "instrument",
            "-w",
            "-r",
            "-e",
            "class",
            "com.dsgpt.mobile." + class_name,
            *extra,
            PACKAGE + ".test/androidx.test.runner.AndroidJUnitRunner",
            timeout=150,
        )
        raw = result.stdout.decode(errors="replace")
        (self.private / (class_name + ".log")).write_text(raw, encoding="utf-8")
        (self.share / (class_name + "-log.txt")).write_text(self.clean(raw), encoding="utf-8")
        require(
            result.returncode == 0
            and re.search(r"^OK \(1 test\)\s*$", raw, re.M)
            and "INSTRUMENTATION_CODE: -1" in raw
            and "FAILURES!!!" not in raw,
            "Android instrumentation failed: " + class_name,
        )

    def phone_file(self, name):
        result = self.adb("exec-out", "run-as", PACKAGE, "cat", "files/" + name)
        require(result.returncode == 0 and result.stdout, "Phone report collection failed")
        return result.stdout

    def phone_diagnostics(self):
        from dsgpt.diagnostics import MobileSnapshot

        self.instrument("DiagnosticsInstrumentedTest")
        raw = self.phone_file("diagnostic-emulator.json")
        snapshot = MobileSnapshot.model_validate_json(raw)
        require(
            snapshot.frames_observed > 0 and snapshot.memory_bytes > 0,
            "Physical phone metrics missing",
        )
        require(snapshot.backend_reachability == "unreachable", "Offline failure was not recorded")
        (self.share / "pixel-offline.json").write_bytes(raw)
        return {
            "real_android_lifecycle": True,
            "frames_observed": snapshot.frames_observed,
            "memory_bytes": snapshot.memory_bytes,
            "failure_captured": True,
        }

    def phone_connected(self, tailnet=False):
        from dsgpt.diagnostics import MobileSnapshot

        if not self.phone:
            raise Blocked(
                "An authorized Pixel debugging connection is required first (USB or wireless)."
            )
        serve = None
        reverse = None
        if tailnet:
            self.tailscale_setup()
            backend_config = json.loads(self.config.read_text())
            if self.tailnet not in backend_config["hosts"]:
                backend_config["hosts"].append(self.tailnet)
                self.config.write_text(json.dumps(backend_config), encoding="utf-8")
                self.stop(self.backend)
                self.start_backend()
            status = command([self.tailscale, "serve", "status", "--json"], 15)
            require(
                status.returncode == 0, "Could not inspect existing Tailscale Serve configuration"
            )
            config = json.loads(status.stdout or b"{}")
            used = json.dumps(config)
            selected = next((p for p in (18443, 18444, 18445) if str(p) not in used), None)
            if not selected:
                raise Blocked(
                    "Acceptance Tailscale ports are already used; existing routes were preserved."
                )
            # Foreground serve owns an ephemeral session; stopping only this child removes it.
            serve = self.spawn([self.tailscale, "serve", "--https=" + str(selected), self.origin])
            origin = f"https://{self.tailnet}:{selected}"
            serve_log = self.private / f"process-{len(self.children) - 1}.txt"
            opened = set()

            def ready():
                try:
                    if self.http.get(origin + "/v1/device", timeout=5).status_code == 401:
                        return True, "Private HTTPS endpoint is ready."
                except httpx.HTTPError:
                    pass
                raw = serve_log.read_text(errors="replace") if serve_log.is_file() else ""
                # Only the vendor's own capability-consent URLs may be opened automatically.
                for url in re.findall(r"https://login\.tailscale\.com/[A-Za-z0-9/?=&_.%-]+", raw):
                    if url not in opened:
                        import webbrowser

                        self.secrets.append(url)
                        webbrowser.open(url)
                        opened.add(url)
                return None, (
                    "Tailscale HTTPS is starting. If a Tailscale page opened, enable "
                    "HTTPS there. Keep Tailscale Connected on both devices."
                )

            phone_ui_opened = False

            def phone_ready():
                nonlocal phone_ui_opened
                self.instrument(
                    "AcceptanceInstrumentedTest", ["-e", "phase", "probe", "-e", "origin", origin]
                )
                if json.loads(self.phone_file("acceptance-route.json")).get("ready"):
                    return True, "The Pixel reached this PC through private HTTPS."
                if not phone_ui_opened:
                    installed = self.adb("shell", "pm", "path", "com.tailscale.ipn")
                    if installed.stdout.strip():
                        self.adb(
                            "shell",
                            "monkey",
                            "-p",
                            "com.tailscale.ipn",
                            "-c",
                            "android.intent.category.LAUNCHER",
                            "1",
                        )
                    else:
                        self.adb(
                            "shell",
                            "am",
                            "start",
                            "-a",
                            "android.intent.action.VIEW",
                            "-d",
                            "market://details?id=com.tailscale.ipn",
                        )
                    phone_ui_opened = True
                return None, (
                    "The PC is ready; the Pixel cannot reach it over Tailscale yet. "
                    "On the phone, finish Tailscale setup using the same account "
                    "and tap Connect. Allow Android's VPN prompt if it appears. "
                    "If both say Connected, check that your tailnet allows this route."
                )

            try:
                wait_ready(ready, "Private HTTPS connection", ci=self.args.ci)
                wait_ready(phone_ready, "Pixel private connection", ci=self.args.ci)
            except BaseException:
                self.stop(serve)
                raise
        else:
            reverse = port()
            result = self.adb(
                "reverse", "--no-rebind", f"tcp:{reverse}", f"tcp:{self.backend_port}"
            )
            require(result.returncode == 0, "Could not create an owned USB reverse connection")
            origin = f"http://127.0.0.1:{reverse}"
        try:
            if not tailnet:
                self.instrument(
                    "AcceptanceInstrumentedTest", ["-e", "phase", "probe", "-e", "origin", origin]
                )
                require(
                    json.loads(self.phone_file("acceptance-route.json")).get("ready"),
                    "Pixel could not reach the owned USB test endpoint",
                )
            code = self.api("POST", "/v1/pairings", {"scopes": ["chat", "diagnostics"]})["code"]
            self.secrets.append(code)
            self.instrument(
                "AcceptanceInstrumentedTest", ["-e", "origin", origin, "-e", "pairing", code]
            )
            raw = self.phone_file("acceptance-phone.json")
            MobileSnapshot.model_validate_json(raw)
            evidence = json.loads(self.phone_file("acceptance-result.json"))
            # Force-stop and reinstall the same signed APK, preserving this test app's data.
            self.adb("shell", "am", "force-stop", PACKAGE)
            update = self.adb("install", "-r", self.kit / "android/app-debug.apk", timeout=120)
            require(
                update.returncode == 0 and b"Success" in update.stdout,
                "Acceptance app update failed",
            )
            self.instrument("AcceptanceInstrumentedTest", ["-e", "phase", "restore"])
            self.api("DELETE", "/v1/devices/" + evidence.pop("device_id"))
            prefix = "pixel-tailnet" if tailnet else "pixel-adb"
            (self.share / (prefix + ".json")).write_bytes(raw)
            (self.share / (prefix + ".zip")).write_bytes(self.phone_file("acceptance-phone.zip"))
            return {
                **evidence,
                "transport": "actual Tailscale HTTPS" if tailnet else "ADB loopback test transport",
                "keystore_restored_after_process_exit_and_update": True,
            }
        finally:
            if reverse:
                self.adb("reverse", "--remove", f"tcp:{reverse}")
            self.stop(serve)

    def finish(self):
        cleanup_failures = 0
        for cleanup in reversed(self.cleanup):
            try:
                result = cleanup()
                if getattr(result, "returncode", 0):
                    cleanup_failures += 1
            except Exception:
                cleanup_failures += 1
        for child in reversed(self.children):
            try:
                self.stop(child)
            except Exception:
                cleanup_failures += 1
        self.report["checks"].append(
            {
                "name": "Remove owned temporary processes and phone packages",
                "status": "FAIL" if cleanup_failures else "PASS",
                "detail": {"cleanup_failures": cleanup_failures},
            }
        )
        if not self.needs_restart and not self.args.ci:
            with contextlib.suppress(OSError):
                self.resume_setup(False)
        self.http.close()
        self.report["finished"] = True
        self.report["ended"] = datetime.now(UTC).isoformat()
        self.save()
        destination = None
        if os.name == "nt":
            # Resolve redirected/OneDrive Desktop using the OS, not a guessed folder.
            found = command(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    "[Environment]::GetFolderPath('Desktop')",
                ]
            )
            folder = found.stdout.decode(errors="replace").strip()
            desktop = Path(folder)
            if found.returncode == 0 and folder and desktop.is_dir():
                destination = desktop / ("dsGPT-report-" + self.id[:8] + ".zip")
                try:
                    shutil.copy2(self.root / "dsGPT-report.zip", destination)
                except OSError:
                    destination = None
        print("\nREPORT READY: " + str(destination or self.root / "dsGPT-report.zip"), flush=True)
        print(
            "Share that ZIP in this conversation. No report was uploaded automatically.", flush=True
        )
        if os.name == "nt" and not self.args.ci:
            with contextlib.suppress(OSError):
                os.startfile(self.share / "Read-this-report.html")

    def run(self):
        try:
            self.check("Kit file integrity", self.integrity)
            if self.report["checks"][-1]["status"] != "PASS":
                return 2
            self.check("PC and NVIDIA inventory", self.inventory)
            if not self.args.ci and not self.args.no_phone:
                self.check("Prepare Pixel debugging connection", self.phone_detect)
                self.check("Prepare Tailscale connection", self.tailscale_setup)
            self.check("Set up and verify local inference", self.discover_models)
            self.check("Start isolated backend", self.start_backend)
            self.check("Chat, restart, cancellation, pairing and diagnostics", self.backend_checks)
            self.check("Windows client and Credential Manager", self.native_client)
            if not self.args.ci:
                self.check("Real local model inference and GPU residency", self.local_models)
                self.check("Docker Desktop and isolated toolchain", self.docker_setup)
                self.check(
                    "PDF and image OCR",
                    lambda: self.docker_script(
                        "live_documents",
                        ["--samples", self.kit / "tests/fixtures/document-samples.json"],
                    ),
                )
                self.check(
                    "Compile, fail, repair and export Windows EXE",
                    lambda: self.docker_script("live_isolated_build"),
                )
                self.check(
                    "Isolated browser tools", lambda: self.docker_script("live_browser_tool")
                )
                self.check("Compile, repair and export Android APK", self.android_build)
                self.check("Real local model compiler repair", self.local_work)
                self.check("Chat completes during the local model build", self.local_work_chat)
                self.check("Managed local search", lambda: self.live_script("live_search_service"))
                self.check(
                    "Semantic document retrieval",
                    lambda: self.live_script("live_attachment_semantic"),
                )
            if not self.args.no_phone:
                self.check("Connect Pixel and install separate test app", self.phone_setup)
                self.check(
                    "Pixel offline diagnostics and frame/memory metrics", self.phone_diagnostics
                )
                self.check("Pixel pairing, background reply and app update", self.phone_connected)
                if not self.args.ci:
                    self.check(
                        "Pixel to PC over actual Tailscale HTTPS",
                        lambda: self.phone_connected(True),
                    )
            self.check("Final diagnostics after all tests", self.collect_backend_diagnostics)
            self.report["checks"].append(
                {
                    "name": "Production release and physical usability",
                    "status": "REVIEW",
                    "detail": "The kit is a development test bundle. Production Authenticode "
                    "and Android signing identity, full production installer/logon/reboot "
                    "behavior, long-duration load, model quality, and visual/keyboard comfort "
                    "are not certified by this run. No signing keys were collected.",
                }
            )
            return (
                1
                if any(c["status"] == "FAIL" for c in self.report["checks"])
                else (
                    2
                    if not self.args.ci
                    and any(c["status"] == "BLOCKED" for c in self.report["checks"])
                    else 0
                )
            )
        except RestartRequired:
            self.report["needs_restart"] = True
            return 3010
        except KeyboardInterrupt:
            self.report["checks"].append(
                {
                    "name": "Run interrupted",
                    "status": "BLOCKED",
                    "detail": "Partial evidence saved. Run the same CMD again to retry.",
                }
            )
            return 130
        finally:
            self.finish()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kit", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--backend", type=Path)
    parser.add_argument("--ci", action="store_true")
    parser.add_argument("--no-phone", action="store_true")
    parser.add_argument(
        "--wireless", action="store_true", help="Pair/connect Android wireless debugging"
    )
    args = parser.parse_args()
    if args.backend:
        from .backend import serve

        serve(args.backend)
        return 0
    if not args.kit:
        parser.error("--kit is required")
    if not args.ci:
        print(
            "dsGPT setup installs missing local dependencies and tests separate synthetic data.\n"
            "Keep the Pixel unlocked. Phone authorization is checked before long downloads.\n"
            "Downloads can take 20-60 minutes or longer. Progress is shown here.\n"
            "Normal double-click is sufficient; installers request Windows permission as needed.",
            flush=True,
        )
    runner = Runner(args)
    code = runner.run()
    return code or (1 if any(c["status"] == "FAIL" for c in runner.report["checks"]) else 0)


if __name__ == "__main__":
    sys.exit(main())
