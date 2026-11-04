import argparse
import json
import os
import platform
import shutil
import subprocess
import tomllib
from pathlib import Path

import psutil
import uvicorn

from .api import create_app
from .bootstrap import WindowsVault, credential_target, ensure_owner
from .config import Model, Settings
from .security import Auth
from .storage import Store, utcnow


def default_data_dir():
    if os.name == "nt":
        return Path(os.environ["LOCALAPPDATA"]) / "dsGPT" / "data"
    return Path.home() / ".local" / "share" / "dsgpt"


def load_settings(path, data_dir):
    config = tomllib.loads(Path(path).read_text()) if path else {}
    models = {item["id"]: Model(**item) for item in config.get("models", [])}
    if len(models) != len(config.get("models", [])):
        raise ValueError("Duplicate model id")
    return Settings(
        data_dir=data_dir,
        models=models,
        allowed_hosts=tuple(config.get("allowed_hosts", ["127.0.0.1", "localhost", "[::1]"])),
        allowed_origins=tuple(config.get("allowed_origins", [])),
        search_origin=config.get("research", {}).get("search_origin"),
        sandbox_image=config.get("work", {}).get("sandbox_image"),
        diagnostic_retention=config.get("diagnostics", {}).get("mobile_snapshot_retention", 100),
        diagnostic_event_retention=config.get("diagnostics", {}).get("event_retention", 2000),
        diagnostic_snapshot_retention=config.get("diagnostics", {}).get("snapshot_retention", 50),
        diagnostic_snapshot_bytes=config.get("diagnostics", {}).get("snapshot_bytes", 131072),
        diagnostic_export_bytes=config.get("diagnostics", {}).get("export_bytes", 8 * 1024 * 1024),
    )


def doctor():
    cpu = psutil.cpu_freq()
    report = {
        "captured_at": utcnow(),
        "platform": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "architecture": platform.machine(),
        "cpu_physical": psutil.cpu_count(logical=False),
        "cpu_logical": psutil.cpu_count(),
        "cpu_current_mhz": cpu.current if cpu else None,
        "ram_total_bytes": psutil.virtual_memory().total,
        "ram_available_bytes": psutil.virtual_memory().available,
        "tools": {
            tool: bool(shutil.which(tool))
            for tool in (
                "ollama",
                "llama-server",
                "tailscale",
                "git",
                "java",
                "javac",
                "adb",
                "gradle",
                "dotnet",
                "cargo",
                "docker",
                "nvidia-smi",
            )
        },
        "gpu": None,
        "limitations": [
            "CPU frequency is a snapshot, not a sustained benchmark",
            "Windows edition and virtualization need target validation",
        ],
    }
    if shutil.which("nvidia-smi"):
        result = subprocess.run(
            [
                shutil.which("nvidia-smi"),
                "--query-gpu=name,driver_version,memory.total,memory.free,"
                "temperature.gpu,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        report["gpu"] = result.stdout.strip() if result.returncode == 0 else "query_failed"
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="dsGPT local backend")
    parser.add_argument("command", choices=["init", "bootstrap", "serve", "doctor", "backup"])
    parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    parser.add_argument("--config", type=Path)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.command == "doctor":
        result = json.dumps(doctor(), indent=2)
        if args.output:
            with args.output.open("x", encoding="utf-8") as file:
                file.write(result + "\n")
        else:
            print(result)
    elif args.command == "init":
        credentials = Auth(Store(args.data_dir)).initialize_owner()
        print("Save this owner credential securely. It is shown only once; do not share it.")
        print(json.dumps(credentials, indent=2))
    elif args.command == "bootstrap":
        # No token is written to stdout, command arguments, configuration or log files.
        vault = WindowsVault(args.data_dir)
        result = ensure_owner(Store(args.data_dir), vault)
        result["credential_target"] = credential_target(args.data_dir)
        print(json.dumps(result))
    elif args.command == "backup":
        if not args.output:
            parser.error("backup requires a new --output path")
        Store(args.data_dir).backup(args.output)
        print("Database backup completed")
    else:
        settings = load_settings(args.config, args.data_dir)
        store = Store(settings.data_dir)
        if not store.one("SELECT id FROM devices WHERE role='owner' AND revoked=0"):
            parser.error("Run init locally before starting the backend")
        uvicorn.run(
            create_app(settings),
            host="127.0.0.1",
            port=args.port,
            workers=1,
            proxy_headers=False,
            access_log=False,
        )


if __name__ == "__main__":
    main()
