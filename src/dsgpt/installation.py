"""Persistent, non-secret setup state for the installed Windows application."""

import hashlib
import json
import os
import re
import subprocess
from dataclasses import replace
from pathlib import Path

import httpx

STATE_FILE = "application-setup.json"


def load(directory):
    path = Path(directory) / STATE_FILE
    if not path.is_file():
        return {}
    if path.is_symlink() or path.stat().st_size > 65536:
        raise RuntimeError("Application setup state is invalid; run Repair dsGPT")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("format") != 1:
        raise RuntimeError("Application setup state is invalid; run Repair dsGPT")
    return value


def save(directory, value):
    path = Path(directory) / STATE_FILE
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({**value, "format": 1}, indent=2), encoding="utf-8")
    temporary.replace(path)


def tailnet_host(value):
    if (
        not isinstance(value, str)
        or not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9.-]{0,249})\.ts\.net", value)
        or ".." in value
    ):
        raise ValueError("Invalid private Tailscale hostname")
    return value.lower()


def settings_for_installation(settings):
    state = load(settings.data_dir)
    host = state.get("tailnet_host")
    if not host:
        return settings
    host = tailnet_host(host)
    return replace(settings, allowed_hosts=tuple(dict.fromkeys((*settings.allowed_hosts, host))))


def file_digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def remember_runtime(directory, executable):
    path = Path(executable).resolve(strict=True)
    if path.name.lower() != "ollama.exe":
        raise ValueError("Unexpected local inference executable")
    state = load(directory)
    state["ollama_cli"] = {"path": str(path), "sha256": file_digest(path)}
    save(directory, state)


def start_saved_runtime(directory, *, client=None, launch=subprocess.Popen):
    """Restore only the CLI verified during setup; never kill an existing runtime."""
    state = load(directory)
    record = state.get("ollama_cli")
    owned = client is None
    client = client or httpx.Client(trust_env=False, follow_redirects=False, timeout=2)
    try:
        try:
            response = client.get("http://127.0.0.1:11434/api/tags")
            if response.is_success and isinstance(response.json().get("models"), list):
                return True
        except (httpx.HTTPError, ValueError, AttributeError):
            pass
        if not record:
            return False
        path = Path(record["path"])
        if (
            not path.is_absolute()
            or path.name.lower() != "ollama.exe"
            or path.is_symlink()
            or not path.is_file()
            or file_digest(path) != record["sha256"]
        ):
            return False
        launch(
            [str(path), "serve"],
            env=dict(os.environ, OLLAMA_HOST="127.0.0.1:11434", OLLAMA_NO_CLOUD="1"),
            cwd=path.parent,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return True
    finally:
        if owned:
            client.close()


def start_saved_docker(directory, *, launch=subprocess.Popen):
    record = load(directory).get("docker_desktop")
    if not record:
        return False
    path = Path(record["path"])
    if (
        not path.is_absolute()
        or path.name.lower() != "docker desktop.exe"
        or path.is_symlink()
        or not path.is_file()
        or file_digest(path) != record["sha256"]
    ):
        return False
    launch(
        [str(path)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return True
