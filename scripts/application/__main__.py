"""Install prerequisites and configure the real app, using the tested setup helpers.

No acceptance fixture, test database, instrumentation or cleanup runner is invoked.
"""

import argparse
import contextlib
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
import webbrowser
import zipfile
from pathlib import Path
from types import SimpleNamespace

from dsgpt_acceptance.__main__ import Runner, command, executable, require
from dsgpt_acceptance.ollama_runtime import OLLAMA, installed_ok
from dsgpt_acceptance.ollama_runtime import install as install_ollama
from dsgpt_acceptance.setup import (
    Blocked,
    RestartRequired,
    adb_devices,
    docker_locations,
    wireless_endpoint,
    wireless_serial,
)

from dsgpt import installation, managed
from dsgpt.bootstrap import WindowsVault
from dsgpt.startup import startup
from dsgpt.storage import InstanceLock

PACKAGE = "com.dsgpt.mobile"


def serve_approval_urls(text):
    # Accept only the vendor's HTTPS consent host, never arbitrary command output.
    return set(re.findall(r"https://login\.tailscale\.com/[A-Za-z0-9/?=&_.%~-]+", text))


def resume(install_dir, enable):
    if os.name != "nt":
        return
    import winreg

    with winreg.CreateKey(
        winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\RunOnce"
    ) as key:
        if enable:
            argv = [
                str(install_dir / "python/python.exe"),
                "-B",
                "-I",
                "-m",
                "dsgpt_application",
                "setup",
            ]
            winreg.SetValueEx(
                key, "dsGPTApplicationSetup", 0, winreg.REG_SZ, subprocess.list2cmdline(argv)
            )
        else:
            with contextlib.suppress(FileNotFoundError):
                winreg.DeleteValue(key, "dsGPTApplicationSetup")


def route_matches(config, host, port):
    address = host + ":" + str(port)
    tcp = config.get("TCP", {}).get(str(port))
    handlers = config.get("Web", {}).get(address, {}).get("Handlers")
    return (
        tcp == {"HTTPS": True}
        and handlers == {"/": {"Proxy": managed.ORIGIN}}
        and not config.get("AllowFunnel", {}).get(address)
    )


def choose_route(config, host, previous=None):
    used = json.dumps(config)
    if previous and previous.get("host") == host:
        port = previous.get("port")
        if type(port) is int and 1 <= port <= 65535 and route_matches(config, host, port):
            return port, True
    # Recover an existing dsGPT route even if an older installer omitted its state.
    # Never claim another service's route or a public Funnel route.
    for raw in config.get("TCP", {}):
        if str(raw).isdigit() and route_matches(config, host, int(raw)):
            return int(raw), True
    for port in (8443, 18446, 18447, 18448):
        if str(port) not in used:
            return port, False
    raise RuntimeError(
        "The private app ports are occupied; existing Tailscale routes were preserved"
    )


def register_models(models, request):
    existing = {m["id"] for m in request("GET", "/v1/models")}
    identifiers = []
    for model in models:
        definition = dict(model)
        identifier = "local-" + hashlib.sha256(model["runtime_model"].encode()).hexdigest()[:16]
        definition["id"] = identifier
        if identifier not in existing:
            request("POST", "/v1/models/register", definition)
            existing.add(identifier)
        identifiers.append(identifier)
    return identifiers


def start_experience(install_dir, directory):
    try:
        status = json.loads((directory / "experience-setup.json").read_text())
        if status.get("version") == "0.6.0" and status.get("status") == "succeeded":
            return
    except (OSError, ValueError):
        pass
    subprocess.Popen(
        [
            str(install_dir / "python/pythonw.exe"),
            "-B",
            "-I",
            "-m",
            "dsgpt_application",
            "prepare-experience",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        close_fds=True,
    )


class Setup(Runner):
    """Reuse prerequisite detection; override lifecycle so application data persists."""

    def __init__(self, install_dir, *, ci=False, launch=True):
        self.directory = managed.managed_directory()
        self.launch_ui = launch
        self.phone_job = uuid.uuid4().hex
        output = self.directory.parent / "setup" / uuid.uuid4().hex
        super().__init__(
            SimpleNamespace(kit=install_dir, output=output, ci=ci, no_phone=False, wireless=True)
        )
        self.report["scope"] = (
            "Application installation; no personal chats or credentials collected"
        )
        self.report.pop("quality_limit", None)
        self.state = installation.load(self.directory)
        self.state.setdefault("format", 1)
        self.report["kind"] = "application_setup"

    def save(self):
        safe = self.clean(self.report)
        (self.share / "setup-report.json").write_text(json.dumps(safe, indent=2), encoding="utf-8")

    def persist(self):
        installation.save(self.directory, self.state)

    def resume_setup(self, enable):
        resume(self.kit, enable)

    def spawn(self, argv, env=None):
        if len(argv) == 2 and argv[1] == "serve" and Path(argv[0]).name.lower() == "ollama.exe":
            installation.remember_runtime(self.directory, argv[0])
            self.state = installation.load(self.directory)
        # These services outlive setup. Do not retain unbounded inference logs.
        child = subprocess.Popen(
            [str(v) for v in argv],
            env=env,
            cwd=self.private,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            close_fds=True,
        )
        self.children.append(child)
        return child

    def install_ollama_runtime(self):
        # Reuse the verified runtime cache left by the accepted kit, if present.
        cache = Path(os.environ["LOCALAPPDATA"]) / "dsGPT-Acceptance/dependencies"
        result = install_ollama(self.http, cache, lambda message: print(message, flush=True))
        self.report["local_runtime_setup"] = {
            "strategy": "standalone_cli",
            "desktop_app_launched": False,
            "account_required": False,
        }
        return str(result)

    def integrity(self):
        manifest = json.loads((self.kit / "application-manifest.json").read_text())
        for name, record in manifest["files"].items():
            path = self.kit / name
            require(
                path.resolve().is_relative_to(self.kit) and path.is_file(),
                "Application file missing",
            )
            require(
                path.stat().st_size == record["bytes"]
                and installation.file_digest(path) == record["sha256"],
                "Application file verification failed: " + name,
            )
        self.report["source_commit"] = manifest["source_commit"]
        return {"verified_files": len(manifest["files"])}

    def desktop_dependencies(self):
        roots = [
            Path(os.environ.get(v, "")) / "Microsoft/EdgeWebView/Application"
            for v in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")
        ]
        if not any(any(root.glob("*/msedgewebview2.exe")) for root in roots):
            self.vendor_install("Microsoft.EdgeWebView2Runtime")
        system = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32"
        if not all((system / name).is_file() for name in ("vcruntime140.dll", "msvcp140.dll")):
            self.vendor_install("Microsoft.VCRedist.2015+.x64")
        return {"desktop_dependencies_ready": True}

    def local_setup(self):
        result = self.discover_models()
        # Remember an installed CLI even when an already-running server was reused.
        cli = executable(
            "ollama",
            [
                Path(os.environ["LOCALAPPDATA"]) / "Programs/Ollama/ollama.exe",
                Path(os.environ.get("ProgramFiles", "")) / "Ollama/ollama.exe",
            ],
        )
        if not cli:
            cached = (
                Path(os.environ["LOCALAPPDATA"])
                / "dsGPT-Acceptance/dependencies"
                / ("ollama-" + OLLAMA["version"])
            )
            if cached.is_dir() and installed_ok(cached, OLLAMA):
                cli = str(cached / "ollama.exe")
        if cli:
            installation.remember_runtime(self.directory, cli)
            self.state = installation.load(self.directory)
        return result

    def private_connection(self):
        self.tailscale_setup()
        host = installation.tailnet_host(self.tailnet)
        old_host = self.state.get("tailnet_host")
        self.state["tailnet_host"] = host
        self.persist()
        if old_host != host:
            # Graceful stop preserves accepted work and never terminates by PID.
            managed.stop(self.directory)
        return {"pc_connected": True}

    def request(self, method, path, body=None, timeout=60):
        return managed.owner_request(self.directory, method, path, body, timeout)

    def prepare_backend(self):
        lock = InstanceLock(self.directory, "managed-start.lock")
        lock.acquire()
        try:
            vault = managed.start(self.directory, self.kit)
            managed.wire_desktop(
                vault,
                WindowsVault(self.directory, target=managed.CLIENT_TARGET, encoding="utf-16-le"),
            )
        finally:
            lock.release()
        ids = register_models(self.models, self.request)
        self.state["model_ids"] = ids
        self.persist()
        return {
            "persistent_backend": True,
            "registered_models": len(ids),
            "credential_manager": True,
        }

    def wait_job(self, path, identifier, timeout):
        deadline = time.monotonic() + timeout
        last = 0
        while time.monotonic() < deadline:
            job = self.request("GET", path).get("job") or {}
            require(job.get("id") == identifier, "Setup job changed; reopen Repair dsGPT")
            if job.get("status") == "completed":
                return {"completed": True}
            if job.get("status") in {"failed", "interrupted"}:
                raise RuntimeError(
                    "Automatic setup failed: " + str(job.get("error_code", "unknown"))
                )
            if time.monotonic() - last > 20:
                print(
                    "  Still preparing the installed tools; downloads can take several minutes.",
                    flush=True,
                )
                last = time.monotonic()
            time.sleep(2)
        raise RuntimeError("Tool setup is still running. Open Repair dsGPT to check it again")

    def tools(self):
        self.docker_ready()
        desktop = next(
            (
                root / "Docker Desktop.exe"
                for root in docker_locations()
                if (root / "Docker Desktop.exe").is_file()
            ),
            None,
        )
        if desktop:
            self.state["docker_desktop"] = {
                "path": str(desktop.resolve()),
                "sha256": installation.file_digest(desktop),
            }
            self.persist()
        status = self.request("GET", "/v1/tools/setup")
        if status["sandbox"].get("configured"):
            probe = self.request("POST", "/v1/work/sandbox/probe", timeout=120)
            if probe.get("ready"):
                return {"reused": True}
        job = status.get("job") or {}
        if job.get("status") != "running":
            job = self.request("POST", "/v1/tools/setup/" + str(uuid.uuid4()))
        return self.wait_job("/v1/tools/setup", job["id"], 1500)

    def search(self):
        config = self.request("GET", "/v1/research/settings")
        if config.get("configuration_owned") or (
            config.get("origin") and config["origin"] != "http://127.0.0.1:8888"
        ):
            return {"existing_search_preserved": True}
        status = self.request("GET", "/v1/search/service")
        job = status.get("job") or {}
        if job.get("status") != "running":
            job = self.request("POST", "/v1/search/service/start/" + str(uuid.uuid4()))
        return self.wait_job("/v1/search/service", job["id"], 700)

    def https(self):
        if not self.tailnet:
            self.tailscale_setup()
        result = command([self.tailscale, "serve", "status", "--json"], 20)
        require(result.returncode == 0, "Cannot inspect Tailscale routes")
        config = json.loads(result.stdout or b"{}")
        port, reused = choose_route(config, self.tailnet, self.state.get("route"))
        if not reused:
            self.enable_private_https(port)
        result = command([self.tailscale, "serve", "status", "--json"], 20)
        require(
            result.returncode == 0
            and route_matches(json.loads(result.stdout or b"{}"), self.tailnet, port),
            "Private Tailscale route verification failed",
        )
        self.state["route"] = {"host": self.tailnet, "port": port}
        self.state["phone_origin"] = "https://" + self.tailnet + ":" + str(port)
        self.persist()
        require(
            self.http.get(self.state["phone_origin"] + "/v1/device", timeout=20).status_code == 401,
            "Private phone route is not ready",
        )
        return {"persistent_private_https": True, "existing_routes_preserved": True}

    def enable_private_https(self, port):
        opened = set()
        with (
            tempfile.TemporaryDirectory() as temporary,
            (Path(temporary) / "serve.log").open("wb") as output,
        ):
            process = subprocess.Popen(
                [self.tailscale, "serve", "--bg", "--yes", "--https=" + str(port), managed.ORIGIN],
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            deadline = time.monotonic() + 240
            try:
                while True:
                    with Path(output.name).open("rb") as snapshot:
                        text = snapshot.read(32768).decode(errors="replace")
                    for url in serve_approval_urls(text) - opened:
                        opened.add(url)
                        self.secrets.append(url)
                        self.phone_progress(
                            "https",
                            "Tailscale needs your approval to enable HTTPS. "
                            "Approve it in the browser that just opened; setup will continue here.",
                        )
                        webbrowser.open(url)
                    if process.poll() is not None:
                        require(
                            process.returncode == 0,
                            "Tailscale HTTPS setup did not finish. Approve any open Tailscale "
                            "browser request, then retry automatic connection.",
                        )
                        return
                    if time.monotonic() >= deadline:
                        raise Blocked(
                            "Tailscale HTTPS approval did not finish. Complete the "
                            "Tailscale browser approval, then retry automatic connection."
                        )
                    time.sleep(1)
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()

    def phone_progress(self, phase, message, *, status="running"):
        """One bounded, atomic status file. Never include credentials or command output."""
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self.directory / "phone-setup.json"
        temporary = target.with_suffix(".tmp")
        record = {
            "request": self.phone_job,
            "status": status,
            "phase": phase,
            "message": message,
            "updated": int(time.time()),
        }
        temporary.write_text(json.dumps(record), encoding="utf-8")
        self.report["phone_connection"] = record
        os.replace(temporary, target)

    def find_phone(self, adb):
        require(
            command([adb, "start-server"], 20).returncode == 0,
            "Android connection could not start. Reopen dsGPT and retry.",
        )
        command([adb, "reconnect", "offline"], 15)
        # mDNS advertises the new connection port after Android changes it. ADB still
        # requires the PC's previously authorized TLS key; discovery grants no access.
        for attempt in range(12):
            discovered = command([adb, "mdns", "services"], 15)
            endpoints = []
            for line in discovered.stdout.decode(errors="replace").splitlines():
                parts = line.split()
                if len(parts) >= 3 and parts[-2].rstrip(".") == "_adb-tls-connect._tcp":
                    try:
                        endpoint = wireless_endpoint(parts[-1])
                    except ValueError:
                        continue
                    if endpoint not in endpoints:
                        endpoints.append(endpoint)
            for endpoint in endpoints[:8]:
                command([adb, "connect", endpoint], 10)
            devices = adb_devices(command([adb, "devices"], 15).stdout)
            pixels = {}
            for serial, state in devices:
                if state != "device" or serial.startswith("emulator-"):
                    continue

                def prop(name, selected=serial):
                    result = command([adb, "-s", selected, "shell", "getprop", name], 10)
                    return (
                        result.stdout.decode(errors="replace").strip()
                        if result.returncode == 0
                        else ""
                    )

                if prop("ro.product.manufacturer").lower() != "google" or not prop(
                    "ro.product.model"
                ).lower().startswith("pixel"):
                    continue
                identity = prop("ro.serialno")
                if not identity:
                    continue
                identity = hashlib.sha256(identity.encode()).hexdigest()
                if identity not in pixels or wireless_serial(serial):
                    pixels[identity] = serial
            remembered = self.state.get("phone_hardware")
            if remembered in pixels:
                return pixels[remembered], remembered
            if len(pixels) == 1:
                identity, serial = next(iter(pixels.items()))
                return serial, identity
            if len(pixels) > 1:
                raise Blocked(
                    "More than one Pixel is available. Disconnect the extra Pixel "
                    "from debugging and retry."
                )
            if attempt < 11:
                time.sleep(2)
        raise Blocked(
            "Pixel is not reachable through its authorized debugging connection. Keep both "
            "devices on the same home Wi-Fi and turn on Pixel Settings > System > Developer "
            "options > Wireless debugging, then retry. If Android forgot this PC, Android "
            "requires you to authorize it again."
        )

    def install_phone(self, *, reconnect=False):
        adb = self.kit / "platform-tools/adb.exe"
        self.phone_progress("phone", "Finding your already-paired Pixel over Wi-Fi…")
        existing = None
        if reconnect:
            status = self.request("GET", "/v1/devices/phone-status")
            phones = status.get("phones", [])
            existing = next(
                (p for p in phones if p["id"] == self.state.get("phone_device_id")), None
            )
            if existing is None and len(phones) == 1:
                existing = phones[0]
        try:
            self.phone, hardware = self.find_phone(adb)
        except Blocked:
            if existing:
                self.phone_progress(
                    "paired",
                    "Your phone pairing is saved. Open dsGPT Mobile over Tailscale to connect. "
                    "Wireless debugging is only needed for automatic APK updates.",
                    status="succeeded" if existing.get("online") else "paired",
                )
                return {"installed": False, "connection_preserved": True, "update_deferred": True}
            raise
        self.secrets.append(self.phone)
        self.phone_progress("install", "Updating dsGPT Mobile on your Pixel…")
        result = command(
            [adb, "-s", self.phone, "install", "-r", self.kit / "android/dsGPT-Mobile.apk"], 180
        )
        require(
            result.returncode == 0 and b"Success" in result.stdout,
            "Pixel app update failed. The existing app was preserved. Unlock your Pixel and retry.",
        )
        origin = self.state.get("phone_origin", "")
        require(
            bool(re.fullmatch(r"https://[A-Za-z0-9.-]+\.ts\.net:[0-9]{1,5}", origin)),
            "The private phone address is not ready. Retry automatic connection.",
        )
        self.phone_progress("pair", "Connecting your phone and saving its private connection…")
        code = self.request(
            "POST", "/v1/pairings", {"scopes": ["chat", "work", "models", "diagnostics"]}
        )["code"]
        require(bool(re.fullmatch(r"[A-Za-z0-9_-]{6,128}", code)), "Invalid pairing response")
        self.secrets.append(code)
        result = command(
            [
                adb,
                "-s",
                self.phone,
                "shell",
                "am",
                "start",
                "-W",
                "-n",
                PACKAGE + "/.AutomaticPairingActivity",
                "--es",
                "dsgpt_origin",
                origin,
                "--es",
                "dsgpt_pairing",
                code,
                "--es",
                "dsgpt_request",
                self.phone_job,
            ],
            30,
        )
        require(
            result.returncode == 0 and b"Error" not in result.stdout + result.stderr,
            "Pixel connection could not open. Unlock the phone and retry.",
        )
        deadline = time.monotonic() + 100
        reply = {}
        while time.monotonic() < deadline:
            response = command(
                [
                    adb,
                    "-s",
                    self.phone,
                    "shell",
                    "run-as",
                    PACKAGE,
                    "cat",
                    "files/phone-connection-result.json",
                ],
                10,
            )
            if response.returncode == 0 and len(response.stdout) < 4096:
                try:
                    candidate = json.loads(response.stdout)
                    if isinstance(candidate, dict) and candidate.get("request") == self.phone_job:
                        reply = candidate
                        break
                except ValueError:
                    pass
            time.sleep(1)
        if reply.get("status") == "different_desktop":
            raise Blocked(
                "This Pixel is connected to another dsGPT desktop. Its saved connection was "
                "preserved. Disconnect it in the phone's dsGPT Settings before retrying here."
            )
        require(
            reply.get("status") in {"paired", "reused"},
            "The Pixel could not verify its private connection. Keep Tailscale connected on both "
            "devices and unlock your Pixel, then retry. "
            "No address or pairing code needs to be entered.",
        )
        device_id = reply.get("device_id")
        require(
            isinstance(device_id, str) and bool(re.fullmatch(r"[a-f0-9-]{36}", device_id)),
            "Pixel returned an invalid connection result. Retry automatic connection.",
        )
        # Read the exact identity, including on accounts with more than 50 devices.
        offset = 0
        verified = False
        while offset < 10000:
            devices = self.request("GET", f"/v1/devices?limit=50&offset={offset}")
            verified = any(
                d.get("id") == device_id and not d.get("revoked") and d.get("role") != "owner"
                for d in devices
            )
            if verified or len(devices) < 50:
                break
            offset += 50
        require(
            verified,
            "The phone credential could not be verified on this desktop. Retry connection.",
        )
        self.state["phone_installed"] = True
        self.state["phone_hardware"] = hardware
        self.state["phone_device_id"] = device_id
        self.state["phone_apk_sha256"] = installation.file_digest(
            self.kit / "android/dsGPT-Mobile.apk"
        )
        self.persist()
        self.phone_progress(
            "done",
            "Pixel connected. Open dsGPT Mobile and chat. "
            "For everyday use, only Tailscale needs to stay connected.",
            status="succeeded",
        )
        return {
            "installed": True,
            "phone_authenticated": True,
            "connection_reused": reply["status"] == "reused",
            "requires_phone_confirmation": False,
        }

    def step(self, name, function, critical=False):
        self.check(name, function)
        if (
            name == "Install and connect dsGPT Mobile"
            and self.report["checks"][-1]["status"] != "PASS"
        ):
            self.phone_progress(
                "phone",
                "Pixel connection needs attention. Click Connect Pixel automatically to retry.",
                status="needs_attention",
            )
        passed = self.report["checks"][-1]["status"] == "PASS"
        if critical and not passed:
            raise RuntimeError(name + " did not finish. Open Repair dsGPT to retry automatically")
        return passed

    def open_client(self):
        if self.launch_ui:
            subprocess.Popen([str(self.kit / "client/dsGPT.exe")], cwd=self.kit, close_fds=True)

    def run_setup(self):
        self.step("Verify installed application", self.integrity, True)
        self.step("Prepare desktop runtime", self.desktop_dependencies, True)
        self.step("Prepare local model", self.local_setup, True)
        tailnet = self.step("Connect this PC to Tailscale", self.private_connection)
        self.step("Start persistent dsGPT and register local models", self.prepare_backend, True)
        self.step(
            "Start dsGPT after Windows sign-in", lambda: startup(self.kit, "enable", confirm=True)
        )
        self.open_client()
        if not self.args.ci:
            start_experience(self.kit, self.directory)
        print(
            "dsGPT is open. Your chats are now saved in your real local profile. "
            "Preparing the remaining tools...",
            flush=True,
        )
        if self.step("Prepare document and build tools", self.tools):
            self.step("Prepare local web search", self.search)
        if tailnet and self.step("Prepare persistent private phone connection", self.https):
            self.step("Install and connect dsGPT Mobile", self.install_phone)
        self.state["ready"] = all(
            c["status"] == "PASS"
            for c in self.report["checks"]
            if c["name"] != "Install and connect dsGPT Mobile"
        )
        self.persist()
        self.resume_setup(False)
        return self.state["ready"]

    def finish_report(self):
        self.report["finished"] = True
        self.save()
        target = self.directory.parent / "dsGPT-Setup-report.zip"
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(self.share / "setup-report.json", "setup-report.json")
        print("Setup report: " + str(target), flush=True)
        self.http.close()


def _main(argv=None):
    parser = argparse.ArgumentParser(description="dsGPT automatic application setup")
    parser.add_argument(
        "command",
        choices=["setup", "launch", "pair-phone", "remove-route", "prepare-experience"],
        default="launch",
        nargs="?",
    )
    parser.add_argument("--no-launch", action="store_true")
    parser.add_argument("--connect-phone", action="store_true")
    args = parser.parse_args(argv)
    install_dir = Path(sys.executable).resolve().parent.parent
    directory = managed.managed_directory()
    state = installation.load(directory)
    if args.command == "remove-route":
        route = state.get("route")
        if route:
            cli = executable(
                "tailscale", [Path(os.environ.get("ProgramFiles", "")) / "Tailscale/tailscale.exe"]
            )
            require(bool(cli), "Tailscale CLI unavailable; private route was preserved")
            result = command([cli, "serve", "status", "--json"], 20)
            require(result.returncode == 0, "Cannot inspect private route; removal refused")
            if route_matches(json.loads(result.stdout or b"{}"), route["host"], route["port"]):
                result = command([cli, "serve", "--https=" + str(route["port"]), "off"], 20)
                require(result.returncode == 0, "Private route removal failed")
        resume(install_dir, False)
        return 0
    if args.command == "launch":
        if state.get("ready") and installation.start_saved_runtime(directory):
            result = managed.main(["launch"])
            if result == 0:
                start_experience(install_dir, directory)
            if result == 0 and args.connect_phone:
                subprocess.Popen(
                    [
                        str(install_dir / "python/pythonw.exe"),
                        "-B",
                        "-I",
                        "-m",
                        "dsgpt_application",
                        "pair-phone",
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    close_fds=True,
                )
            return result
        subprocess.Popen(
            [
                str(install_dir / "python/python.exe"),
                "-B",
                "-I",
                "-m",
                "dsgpt_application",
                "setup",
            ],
            close_fds=True,
        )
        return 0
    setup = Setup(install_dir, launch=not args.no_launch)
    lock = InstanceLock(
        directory,
        "experience-setup.lock"
        if args.command == "prepare-experience"
        else "application-setup.lock",
    )
    acquired = False
    try:
        lock.acquire()
        acquired = True
        if args.command == "prepare-experience":
            from dsgpt_application.experience import prepare

            setup.integrity()
            prepare(setup, register_models)
            return 0
        if args.command == "pair-phone":
            setup.phone_progress("verify", "Checking the installed phone setup…")
            setup.integrity()
            require(managed.main(["start"]) == 0, "dsGPT could not start")
            setup.phone_progress("tailscale", "Connecting the desktop to Tailscale…")
            setup.private_connection()
            require(managed.main(["start"]) == 0, "dsGPT could not restart")
            setup.phone_progress("https", "Preparing your private HTTPS address automatically…")
            setup.https()
            setup.install_phone(reconnect=True)
            return 0
        return 0 if setup.run_setup() else 2
    except RestartRequired:
        if args.command == "pair-phone":
            setup.phone_progress(
                "restart",
                "Windows needs a restart. Save your work and restart; "
                "dsGPT setup will resume after sign-in.",
                status="needs_attention",
            )
        setup.resume_setup(True)
        print("Save your work and restart Windows. dsGPT setup resumes after sign-in.", flush=True)
        return 3010
    except Exception as exc:
        if args.command == "pair-phone" and acquired:
            safe = (
                str(exc)
                if isinstance(exc, (RuntimeError, AssertionError, Blocked))
                else "Automatic connection could not finish. Retry from dsGPT."
            )
            setup.phone_progress("attention", setup.clean(safe)[:1200], status="needs_attention")
        print(
            str(exc)
            if isinstance(exc, (RuntimeError, AssertionError, Blocked))
            else "Setup could not finish. Open Repair dsGPT to resume.",
            flush=True,
        )
        return 1
    finally:
        if args.command != "prepare-experience":
            setup.finish_report()
        lock.release()


def main(argv=None):
    try:
        return _main(argv)
    except Exception as exc:
        message = (
            str(exc)
            if isinstance(exc, RuntimeError)
            else "dsGPT could not open. Use Start > dsGPT > Repair dsGPT to resume setup."
        )
        if os.name == "nt":
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, "dsGPT", 0x10)
        elif sys.stderr is not None:
            print(message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
