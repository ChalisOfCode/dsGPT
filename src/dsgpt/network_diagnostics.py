"""Read only local Tailscale state; discard addresses, users, peers and keys."""

import json
import os
import subprocess
from pathlib import Path


def tailscale_executable():
    candidates = (
        [Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tailscale/tailscale.exe"]
        if os.name == "nt"
        else [Path("/usr/bin/tailscale"), Path("/usr/local/bin/tailscale")]
    )
    return next((p for p in candidates if p.is_file()), None)


def tailscale_status():
    result = {
        "status": "unavailable",
        "backend_state": None,
        "self_online": None,
        "peer_reachability": "not_probed",
        "addresses_and_peer_names_included": False,
    }
    executable = tailscale_executable()
    if executable is None:
        return {**result, "reason": "tailscale_not_installed"}
    try:
        process = subprocess.run(
            [str(executable), "status", "--json", "--peers=false"],
            capture_output=True,
            timeout=2,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if process.returncode or len(process.stdout) > 262144:
            return {**result, "reason": "local_status_unavailable"}
        data = json.loads(process.stdout)
        states = {"NoState", "NeedsLogin", "NeedsMachineAuth", "Stopped", "Starting", "Running"}
        state = data.get("BackendState")
        if state not in states:
            return {**result, "reason": "unsupported_status_response"}
        own = data.get("Self")
        online = own.get("Online") if isinstance(own, dict) else None
        return {
            **result,
            "status": "measured",
            "backend_state": state,
            "self_online": online if type(online) is bool else None,
        }
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, AttributeError):
        return {**result, "reason": "local_status_unavailable"}
