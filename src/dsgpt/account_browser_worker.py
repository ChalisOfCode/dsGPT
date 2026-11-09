"""Private Chromium profile lifecycle for a checked networkless Linux container.

Never expose this module's CDP methods, profile bytes or errors to Work tools.
The host controller must use an owned, validated DockerSandbox and pass only
a vault-restored snapshot. The private guest/host bridge attaches the broker;
application owner UI integration remains required.
"""

import json
import os
import select
import socket
import stat
import subprocess
import sys
import time
from pathlib import Path, PurePosixPath

from .account_browser_profile_data import MAX_BYTES, MAX_FILES, validate

# Omit caches, crash dumps, extensions, locks and unneeded browsing history.
PROFILE_FILES = frozenset(
    {
        "Local State",
        "Default/Preferences",
        "Default/Cookies",
        "Default/Network/Cookies",
    }
)
PROFILE_DIRS = ("Default/Local Storage", "Default/IndexedDB")
MAX_CDP_BYTES = 4 * 1024**2

# Chrome's private pipe uses fd 3 for commands and fd 4 for replies. Duplicate
# both above these numbers before moving either, even if the original fds overlap.
_LAUNCH = """
import fcntl, os, sys
r = fcntl.fcntl(int(sys.argv[1]), fcntl.F_DUPFD_CLOEXEC, 5)
w = fcntl.fcntl(int(sys.argv[2]), fcntl.F_DUPFD_CLOEXEC, 5)
os.dup2(r, 3)
os.dup2(w, 4)
for fd in {r, w, int(sys.argv[1]), int(sys.argv[2])} - {3, 4}:
    os.close(fd)
os.execv(sys.argv[3], sys.argv[3:])
"""


class AccountBrowserWorkerError(Exception):
    pass


def _container_only():
    if os.getuid() != 1000 or {name for _, name in socket.if_nameindex()} != {"lo"}:
        raise AccountBrowserWorkerError("account_browser_networkless_container_required")


def _profile_path(name):
    return name in PROFILE_FILES or any(name.startswith(prefix + "/") for prefix in PROFILE_DIRS)


def _restore(root, files):
    if files is not None:
        validate(files)
        if not all(_profile_path(name) for name in files):
            raise AccountBrowserWorkerError("account_browser_profile_file_denied")
    root.mkdir(mode=0o700)  # Exclusive: never reuse or overwrite an existing profile.
    for name, data in (files or {}).items():
        path = root.joinpath(*PurePosixPath(name).parts)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with path.open("xb") as handle:
            handle.write(data)


def _snapshot(root):
    if not stat.S_ISDIR(root.lstat().st_mode):
        raise AccountBrowserWorkerError("account_browser_profile_file_denied")
    files = {}
    total = entries = 0

    def collect(path):
        nonlocal total, entries
        entries += 1
        if entries > MAX_FILES * 2:
            raise AccountBrowserWorkerError("account_browser_profile_limit")
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            for child in path.iterdir():
                if child.name != "LOCK":
                    collect(child)
            return
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise AccountBrowserWorkerError("account_browser_profile_file_denied")
        if len(files) >= MAX_FILES or info.st_size > MAX_BYTES - total:
            raise AccountBrowserWorkerError("account_browser_profile_limit")
        # No symlinks on selected paths; no files are opened after a failed shutdown.
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as handle:
            opened = os.fstat(handle.fileno())
            if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                raise AccountBrowserWorkerError("account_browser_profile_file_denied")
            data = handle.read(MAX_BYTES - total + 1)
        total += len(data)
        if total > MAX_BYTES:
            raise AccountBrowserWorkerError("account_browser_profile_limit")
        files[path.relative_to(root).as_posix()] = data

    for name in (*sorted(PROFILE_FILES), *PROFILE_DIRS):
        path = root
        try:
            for segment in PurePosixPath(name).parts[:-1]:
                path = path / segment
                if not stat.S_ISDIR(path.lstat().st_mode):
                    raise AccountBrowserWorkerError("account_browser_profile_file_denied")
            path = root / name
            info = path.lstat()
        except FileNotFoundError:
            continue
        if name in PROFILE_FILES and not stat.S_ISREG(info.st_mode):
            raise AccountBrowserWorkerError("account_browser_profile_file_denied")
        if name in PROFILE_DIRS and not stat.S_ISDIR(info.st_mode):
            raise AccountBrowserWorkerError("account_browser_profile_file_denied")
        collect(path)
    validate(files)
    return files


class PrivateChromium:
    """Internal guest driver. Caller owns the enclosing disposable tmpfs."""

    def __init__(self, root, files=None, *, binary="/usr/bin/chromium"):
        _container_only()
        self.root = Path(root)
        self.process = self._send = self._recv = None
        self._buffer = bytearray()
        self._sequence = 0
        self._inflight = set()
        self._replies = {}
        _restore(self.root, files)
        receive_cmd, send_cmd = os.pipe()
        receive_reply, send_reply = os.pipe()
        self._send, self._recv = send_cmd, receive_reply
        try:
            self.process = subprocess.Popen(
                [
                    sys.executable,
                    "-I",
                    "-c",
                    _LAUNCH,
                    str(receive_cmd),
                    str(send_reply),
                    binary,
                    "--headless",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-background-networking",
                    "--disable-extensions",
                    "--disable-sync",
                    "--no-first-run",
                    "--no-proxy-server",
                    "--host-resolver-rules=MAP * ~NOTFOUND",
                    "--password-store=basic",
                    "--remote-debugging-pipe",
                    "--user-data-dir=" + str(self.root),
                    "about:blank",
                ],
                pass_fds=(receive_cmd, send_reply),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env={"PATH": os.defpath, "HOME": "/tmp", "LANG": "C.UTF-8", "TMPDIR": "/tmp"},
            )
            self._call("Browser.getVersion")
        except BaseException:
            self.abort()
            raise
        finally:
            os.close(receive_cmd)
            os.close(send_reply)

    def _call(self, method, params=None, *, session=None, events=None, timeout=8):
        """Trusted driver only; never dispatch an externally supplied CDP method."""
        if self._send is None:
            raise AccountBrowserWorkerError("account_browser_closed")
        if len(self._inflight) >= 8:
            raise AccountBrowserWorkerError("account_browser_command_limit")
        self._sequence += 1
        message = {"id": self._sequence, "method": method, "params": params or {}}
        if session:
            message["sessionId"] = session
        payload = json.dumps(message).encode() + b"\0"
        if len(payload) > MAX_CDP_BYTES:
            raise AccountBrowserWorkerError("account_browser_command_limit")
        identifier = message["id"]
        self._inflight.add(identifier)
        deadline = time.monotonic() + timeout
        try:
            os.set_blocking(self._send, False)
            pending = memoryview(payload)
            while pending:
                _, ready, _ = select.select(
                    [], [self._send], [], max(0, deadline - time.monotonic())
                )
                if not ready:
                    raise TimeoutError
                try:
                    pending = pending[os.write(self._send, pending) :]
                except BlockingIOError:
                    continue
            while time.monotonic() < deadline:
                reply = self._replies.pop(identifier, None)
                split = self._buffer.find(0)
                if reply is None and split >= 0:
                    raw = bytes(self._buffer[:split])
                    del self._buffer[: split + 1]
                    reply = json.loads(raw)
                if reply is not None:
                    reply_id = reply.get("id")
                    if reply_id == identifier:
                        if "error" in reply:
                            raise AccountBrowserWorkerError("account_browser_command_failed")
                        return reply.get("result", {})
                    if reply_id in self._inflight:
                        self._replies[reply_id] = reply
                    elif events is not None and "method" in reply:
                        events(reply)
                    continue
                ready, _, _ = select.select(
                    [self._recv], [], [], max(0, deadline - time.monotonic())
                )
                if not ready:
                    raise TimeoutError
                block = os.read(self._recv, 65536)
                if not block:
                    raise EOFError
                self._buffer.extend(block)
                if len(self._buffer) > MAX_CDP_BYTES:
                    raise AccountBrowserWorkerError("account_browser_reply_limit")
        except (OSError, ValueError, EOFError, TimeoutError):
            raise AccountBrowserWorkerError("account_browser_pipe_failed") from None
        finally:
            self._inflight.discard(identifier)
            self._replies.pop(identifier, None)
        raise AccountBrowserWorkerError("account_browser_command_timeout")

    def close_and_snapshot(self):
        if self._send is None:
            raise AccountBrowserWorkerError("account_browser_closed")
        try:
            self._call("Browser.close")
            if self.process.wait(timeout=8) != 0:
                raise AccountBrowserWorkerError("account_browser_unclean_shutdown")
            return _snapshot(self.root)
        except subprocess.TimeoutExpired:
            raise AccountBrowserWorkerError("account_browser_unclean_shutdown") from None
        finally:
            self.abort()

    def abort(self):
        """Dispose of a failed/cancelled worker without saving its profile."""
        for attr in ("_send", "_recv"):
            fd = getattr(self, attr)
            if fd is not None:
                os.close(fd)
                setattr(self, attr, None)
        if self.process is not None and self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=5)
