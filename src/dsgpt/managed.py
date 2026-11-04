"""Packaged Windows backend launcher; UI closure does not own backend lifetime.

Uses the existing desktop's native credential entry (keyring 3.6.3). It refuses to
overwrite another connection. The owner key never appears in argv/files/stdout.
"""

import argparse
import ctypes
import hashlib
import hmac
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import uvicorn

from . import __version__
from .api import create_app
from .bootstrap import WindowsVault, ensure_owner, recover_owner
from .cli import load_settings
from .startup import startup
from .storage import InstanceLock, Store
from .supervisor import disable_retries, prepare_start, request_stop
from .windows_security import private_directory

PORT = 18765
ORIGIN = f"http://127.0.0.1:{PORT}"
CLIENT_TARGET = "backend-connection.dsGPT"


def identity_proof(token, challenge, version):
    message = f"dsGPT managed backend identity v1\n{challenge}\n{version}".encode()
    return hmac.new(token.encode(), message, hashlib.sha256).hexdigest()


def verify_running(token, client=None):
    nonce = secrets.token_hex(32)
    own_client = client is None
    client = client or httpx.Client(trust_env=False, follow_redirects=False, timeout=1)
    try:
        response = client.get(ORIGIN + "/managed/identity", params={"challenge": nonce})
        if response.status_code != 200 or len(response.content) > 1024:
            return None
        info = response.json()
        version, proof = info.get("version"), info.get("proof")
        if not isinstance(version, str) or not isinstance(proof, str):
            return None
        expected = identity_proof(token, nonce, version)
        return version if hmac.compare_digest(expected, proof) else None
    except (httpx.HTTPError, ValueError, AttributeError, TypeError):
        return None
    finally:
        if own_client:
            client.close()


def wire_desktop(owner_vault, client_vault, *, recover_local=False):
    owner = owner_vault.read()
    if not owner or not isinstance(owner.get("token"), str):
        raise RuntimeError("Managed owner credential unavailable")
    connection = {"origin": ORIGIN, "token": owner["token"]}
    saved = client_vault.read()
    if (
        saved is not None
        and saved != connection
        and not (recover_local and saved.get("origin") == ORIGIN)
    ):
        raise RuntimeError(
            "Existing desktop connection preserved. Disconnect it in dsGPT "
            "Settings before choosing the managed backend."
        )
    if saved != connection:
        client_vault.write(connection)
        if client_vault.read() != connection:
            raise RuntimeError("Desktop credential verification failed")


def managed_directory():
    # Separate from the developer CLI's data directory and all existing model runtimes.
    if os.name != "nt":
        raise RuntimeError("Managed launcher requires Windows 11")
    root = private_directory(Path(os.environ["LOCALAPPDATA"]) / "dsGPT" / "managed")
    return private_directory(root / "data")


def serve(directory):
    lock = InstanceLock(directory, "managed-service.lock")
    lock.acquire()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # Exclusive bind before initializing credentials. Never share a listener with
        # another service and never replace or terminate an unrecognized process.
        if os.name == "nt":
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind(("127.0.0.1", PORT))
        listener.listen(128)
        vault = WindowsVault(directory)
        ensure_owner(Store(directory), vault)
        token = vault.read()["token"]
        # Optional manually configured, locally validated runtime and tailnet settings.
        config_path = directory / "backend.toml"
        settings = load_settings(config_path if config_path.is_file() else None, directory)
        from .installation import settings_for_installation, start_saved_docker, start_saved_runtime

        settings = settings_for_installation(settings)
        start_saved_runtime(directory)
        start_saved_docker(directory)
        server = None

        def stop():
            server.should_exit = True

        app = create_app(
            settings,
            managed={
                "identity": lambda challenge: {
                    "version": __version__,
                    "proof": identity_proof(token, challenge, __version__),
                },
                "stop": stop,
            },
        )
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=PORT,
                workers=1,
                access_log=False,
                proxy_headers=False,
                log_config=None,
            )
        )
        server.run(sockets=[listener])
    finally:
        listener.close()
        lock.release()


def start(directory, install_dir):
    prepare_start(directory)
    vault = WindowsVault(directory)
    saved = vault.read()
    if saved:
        version = verify_running(saved["token"])
        if version:
            if version != __version__:
                raise RuntimeError(
                    "A different backend version is running. Stop it before updating."
                )
            return vault
    # Validate only port availability, without sending credentials to an unknown listener.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", PORT))
        except OSError as exc:
            raise RuntimeError(
                "Managed backend port is in use. Existing service preserved."
            ) from exc
    executable = install_dir / "python" / "pythonw.exe"
    if not executable.is_file():
        raise RuntimeError("Bundled backend runtime is missing; reinstall this development build")
    scheduled = startup(install_dir, "run")
    child = None
    if not scheduled["enabled"]:
        child = subprocess.Popen(
            [str(executable), "-I", "-m", "dsgpt.managed", "serve"],
            cwd=install_dir,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        saved = vault.read()
        if saved and verify_running(saved["token"]) == __version__:
            return vault
        if child is not None and child.poll() is not None:
            raise RuntimeError(
                "Backend startup failed. Run the Backend Check shortcut for details."
            )
        time.sleep(0.2)
    # Do not kill by stale PID or kill a backend merely because startup took longer.
    raise RuntimeError("Backend is taking longer to start. Try opening dsGPT again.")


def _stop_backend(directory):
    vault = WindowsVault(directory)
    saved = vault.read()
    if not saved or not verify_running(saved["token"]):
        # An occupied port must not be mistaken for an already stopped backend.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", PORT))
            except OSError as exc:
                raise RuntimeError("Unrecognized listener; stop refused") from exc
        return
    with httpx.Client(trust_env=False, follow_redirects=False, timeout=10) as client:
        response = client.post(
            ORIGIN + "/v1/backend/stop", headers={"Authorization": "Bearer " + saved["token"]}
        )
        response.raise_for_status()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if not verify_running(saved["token"]):
            # Wait for both service and backend locks to be released before uninstall.
            locks = [
                InstanceLock(directory, name) for name in ("managed-service.lock", "backend.lock")
            ]
            try:
                for lock in locks:
                    lock.acquire()
                return
            except RuntimeError:
                pass
            finally:
                for lock in locks:
                    lock.release()
        time.sleep(0.2)
    raise RuntimeError("Backend is still shutting down; retry after active work settles")


def stop(directory):
    guard = InstanceLock(directory, "managed-start.lock")
    guard.acquire()
    try:
        request_stop(directory)
        _stop_backend(directory)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            lock = InstanceLock(directory, "managed-supervisor.lock")
            try:
                lock.acquire()
                return
            except RuntimeError:
                time.sleep(0.2)
            finally:
                lock.release()
        raise RuntimeError("Backend supervisor is still stopping; retry after active work settles")
    finally:
        guard.release()


def owner_request(directory, method, path, body=None, timeout=30):
    saved = WindowsVault(directory).read()
    if not saved:
        raise RuntimeError("Start the managed backend first")
    with httpx.Client(trust_env=False, follow_redirects=False, timeout=timeout) as client:
        if not verify_running(saved["token"], client):
            raise RuntimeError("Managed backend identity could not be verified")
        response = client.request(
            method, ORIGIN + path, headers={"Authorization": "Bearer " + saved["token"]}, json=body
        )
        if not response.is_success:
            # API errors are sanitized, but avoid echoing arbitrary backend response bodies.
            raise RuntimeError(f"Backend operation rejected ({response.status_code})")
        return response.json()


def main(argv=None):
    parser = argparse.ArgumentParser(description="dsGPT managed Windows backend")
    parser.add_argument(
        "command",
        choices=[
            "launch",
            "start",
            "serve",
            "stop",
            "recover-owner",
            "startup-status",
            "startup-enable",
            "startup-disable",
            "check",
            "catalog",
            "downloads",
            "download",
            "pause-download",
            "resume-download",
            "cancel-download",
            "remove-download",
            "register-model",
            "runtimes",
            "runtime-status",
            "install-runtime",
            "remove-runtime",
            "attach-model",
            "forget-model",
            "unload-runtime",
            "research",
            "research-status",
            "research-sources",
            "retrieval-status",
            "enable-retrieval",
            "disable-retrieval",
            "semantic-search",
            "sandbox-status",
            "sandbox-probe",
        ],
    )
    parser.add_argument("--id")
    parser.add_argument("--name")
    parser.add_argument("--runtime", choices=["ollama", "llama.cpp"], default="ollama")
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434")
    parser.add_argument("--runtime-model")
    parser.add_argument("--abliterated", action="store_true")
    parser.add_argument("--asset-id")
    parser.add_argument("--runtime-id")
    parser.add_argument("--context", type=int, default=4096)
    parser.add_argument("--output-tokens", type=int, default=1024)
    parser.add_argument("--gpu-layers", type=int, default=0)
    parser.add_argument("--model-id")
    parser.add_argument("--question")
    parser.add_argument("--url", action="append", default=[])
    parser.add_argument("--no-search", action="store_true")
    parser.add_argument("--revision", type=int)
    parser.add_argument("--include-history", action="store_true")
    parser.add_argument("--kind", choices=["memory", "history"], default="memory")
    parser.add_argument("--task-id")
    parser.add_argument("--hidden", action="store_true")
    parser.add_argument("--confirm-revoke-devices", action="store_true")
    parser.add_argument("--confirm-startup-change", action="store_true")
    args = parser.parse_args(argv)
    try:
        directory = managed_directory()
        install_dir = Path(sys.executable).resolve().parent.parent
        if args.command == "serve":
            serve(directory)
        elif args.command == "stop":
            stop(directory)
        elif args.command in {"startup-status", "startup-enable", "startup-disable"}:
            result = startup(
                install_dir,
                args.command.removeprefix("startup-"),
                confirm=args.confirm_startup_change,
            )
            if args.command == "startup-disable":
                disable_retries(directory)
            print(json.dumps(result, indent=2))
        elif args.command == "recover-owner":
            result = recover_owner(
                directory,
                WindowsVault(directory),
                confirm_revoke_devices=args.confirm_revoke_devices,
            )
            client_vault = WindowsVault(directory, target=CLIENT_TARGET, encoding="utf-16-le")
            saved_client = client_vault.read()
            if saved_client is None or saved_client.get("origin") == ORIGIN:
                wire_desktop(WindowsVault(directory), client_vault, recover_local=True)
                result["desktop_reconnected"] = True
            else:
                result["desktop_reconnected"] = False
                result["help"] = (
                    "Another desktop connection was preserved; disconnect it in Settings first"
                )
            print(json.dumps(result))
        elif args.command == "check":
            store = Store(directory)
            saved = WindowsVault(directory).read()
            print(
                json.dumps(
                    {
                        "backend_version": __version__,
                        "database_version": store.one("PRAGMA user_version"),
                        "credential_present": saved is not None,
                        "running_version": verify_running(saved["token"]) if saved else None,
                        "startup": startup(install_dir),
                        "native_validation": "requires_target_acceptance",
                    },
                    indent=2,
                )
            )
        elif args.command in {
            "catalog",
            "downloads",
            "download",
            "pause-download",
            "resume-download",
            "cancel-download",
            "remove-download",
            "register-model",
            "runtimes",
            "runtime-status",
            "install-runtime",
            "remove-runtime",
            "attach-model",
            "forget-model",
            "unload-runtime",
            "research",
            "research-status",
            "research-sources",
            "retrieval-status",
            "enable-retrieval",
            "disable-retrieval",
            "semantic-search",
            "sandbox-status",
            "sandbox-probe",
        }:
            if args.command in {"retrieval-status", "sandbox-status", "sandbox-probe"}:
                path = (
                    "/v1/retrieval/settings"
                    if args.command == "retrieval-status"
                    else "/v1/work/sandbox"
                )
                if args.command == "sandbox-probe":
                    result = owner_request(directory, "POST", path + "/probe", timeout=120)
                else:
                    result = owner_request(directory, "GET", path)
            elif args.command in {"enable-retrieval", "disable-retrieval"}:
                if args.revision is None or args.revision < 0:
                    parser.error("Use retrieval-status first, then supply its --revision")
                enabled = args.command == "enable-retrieval"
                result = owner_request(
                    directory,
                    "PATCH",
                    "/v1/retrieval/settings",
                    {
                        "revision": args.revision,
                        "enabled": enabled,
                        "history_enabled": enabled and args.include_history,
                    },
                )
            elif args.command == "semantic-search":
                from uuid import UUID

                if not args.question:
                    parser.error("semantic-search requires --question")
                result = owner_request(
                    directory,
                    "POST",
                    "/v1/retrieval/search",
                    {
                        "query": args.question,
                        "kind": args.kind,
                        "hidden": args.hidden,
                        "task_id": str(UUID(args.task_id)) if args.task_id else None,
                    },
                )
            elif args.command == "research":
                from uuid import uuid4

                if not args.question or not args.model_id:
                    parser.error("research requires --question and --model-id")
                conversation = owner_request(
                    directory,
                    "POST",
                    "/v1/conversations",
                    {
                        "title": args.question[:200],
                    },
                )
                result = owner_request(
                    directory,
                    "POST",
                    f"/v1/conversations/{conversation['id']}/messages",
                    {
                        "request_id": str(uuid4()),
                        "content": args.question,
                        "model_id": args.model_id,
                        "research": {"search": not args.no_search, "urls": args.url},
                    },
                )
            elif args.command in {"research-status", "research-sources"}:
                from uuid import UUID

                path = "/v1/runs/" + str(UUID(args.id or ""))
                if args.command == "research-sources":
                    path += "/sources"
                result = owner_request(directory, "GET", path)
            elif args.command in {"runtimes", "runtime-status"}:
                result = owner_request(
                    directory,
                    "GET",
                    "/v1/runtimes" if args.command == "runtimes" else "/v1/runtime/status",
                )
            elif args.command == "unload-runtime":
                result = owner_request(directory, "POST", "/v1/runtime/unload")
            elif args.command in {"install-runtime", "remove-runtime", "forget-model"}:
                import re

                if not args.id or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", args.id):
                    parser.error("operation requires a valid --id")
                path = "/v1/models/" if args.command == "forget-model" else "/v1/runtimes/"
                path += args.id
                if args.command == "install-runtime":
                    result = owner_request(directory, "POST", path + "/install")
                else:
                    result = owner_request(directory, "DELETE", path)
            elif args.command == "attach-model":
                if not all((args.id, args.name, args.asset_id, args.runtime_id)):
                    parser.error("attach-model requires --id, --name, --asset-id and --runtime-id")
                result = owner_request(
                    directory,
                    "POST",
                    "/v1/models/managed",
                    {
                        "id": args.id,
                        "name": args.name,
                        "asset_id": args.asset_id,
                        "runtime_id": args.runtime_id,
                        "context": args.context,
                        "output_tokens": args.output_tokens,
                        "gpu_layers": args.gpu_layers,
                    },
                )
            elif args.command == "catalog":
                result = owner_request(
                    directory, "GET", "/v1/model-catalog?include_embeddings=true"
                )
            elif args.command == "downloads":
                result = owner_request(directory, "GET", "/v1/downloads")
            elif args.command == "download":
                if not args.id:
                    parser.error("download requires --id from catalog")
                result = owner_request(directory, "POST", "/v1/downloads", {"asset_id": args.id})
            elif args.command == "register-model":
                if not args.id or not args.name or not args.runtime_model:
                    parser.error("register-model requires --id, --name and --runtime-model")
                result = owner_request(
                    directory,
                    "POST",
                    "/v1/models/register",
                    {
                        "id": args.id,
                        "name": args.name,
                        "runtime": args.runtime,
                        "runtime_model": args.runtime_model,
                        "endpoint": args.endpoint,
                        "abliterated": args.abliterated,
                    },
                )
            else:
                from uuid import UUID

                identifier = str(UUID(args.id or ""))
                path = "/v1/downloads/" + identifier
                result = (
                    owner_request(directory, "DELETE", path)
                    if args.command == "remove-download"
                    else owner_request(
                        directory, "POST", path + "/actions", {"action": args.command.split("-")[0]}
                    )
                )
            print(json.dumps(result, indent=2))
        else:
            startup_lock = InstanceLock(directory, "managed-start.lock")
            startup_lock.acquire()
            try:
                vault = start(directory, install_dir)
                client_vault = WindowsVault(directory, target=CLIENT_TARGET, encoding="utf-16-le")
                wire_desktop(vault, client_vault)
            finally:
                startup_lock.release()
            if args.command == "launch":
                executable = install_dir / "client" / "dsGPT.exe"
                subprocess.Popen([str(executable)], cwd=executable.parent, close_fds=True)
    except Exception as exc:
        # Known application errors are safe; arbitrary OS/HTTP errors may contain secrets/paths.
        message = str(exc) if isinstance(exc, RuntimeError) else "Managed backend operation failed"
        if os.name == "nt" and args.command != "serve":
            ctypes.windll.user32.MessageBoxW(None, message, "dsGPT backend", 0x10)
        elif sys.stderr is not None:
            print(message, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
