"""Exercise the Task Ledger acceptance contract through real Android/Windows controls.

This does not launch a model or treat application self-tests as independent evidence.
Android execution is restricted to an explicitly selected emulator. Windows execution
uses a fresh LOCALAPPDATA directory and only windows owned by the launched process.
Use a disposable CI worker for generated executables. No native app is run on import.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

APP_CLASS = "dsGPTTaskLedgerWindow"
WINDOW_MESSAGE_TIMEOUT_MS = 5000
IDS = {
    "Title": 101,
    "Notes": 102,
    "Priority": 103,
    "Search": 104,
    "filter": 105,
    "rows": 106,
    "counts": 107,
    "error": 108,
    "Add": 201,
    "Save edit": 202,
    "Toggle done": 203,
    "Delete": 204,
    "Clear completed": 205,
}


def file_record(path):
    path = Path(path)
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"name": path.name, "bytes": path.stat().st_size, "sha256": digest}


def wait_for(check, description, timeout=15):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            value = check()
            if value:
                return value
        except (OSError, RuntimeError, ValueError, ET.ParseError) as exc:
            last_error = str(exc)
        time.sleep(0.2)
    raise RuntimeError(f"Timed out: {description}" + (f" ({last_error})" if last_error else ""))


def expected_row(identifier, title, priority, done=False):
    return f"#{identifier} {title} | Priority {priority} | {'Done' if done else 'Active'}"


def expected_counts(total, active):
    return f"Total: {total} | Active: {active} | Done: {total - active}"


class Android:
    def __init__(self, args, directory):
        self.adb, self.serial, self.package = args.adb, args.serial, args.package
        self.directory, self.current_artifact = directory, None
        if not re.fullmatch(r"emulator-\d+", self.serial or ""):
            raise ValueError(
                "An explicit emulator-<port> serial is required; physical devices are refused"
            )
        if not re.fullmatch(r"com\.dsgpt\.generated\.p[a-zA-Z0-9]+", self.package or ""):
            raise ValueError("Use the fixture's com.dsgpt.generated.p<project-id> application ID")
        if self.command("get-serialno").strip() != self.serial:
            raise RuntimeError("ADB did not select the requested emulator")
        if self.command("shell", "getprop", "ro.kernel.qemu").strip() != "1":
            raise RuntimeError("Selected device did not identify itself as an emulator")

    def command(self, *arguments, binary=False, timeout=30):
        result = subprocess.run(
            [self.adb, "-s", self.serial, *arguments],
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(
                f"ADB {arguments[0]} failed ({result.returncode}): "
                + result.stderr.decode("utf-8", errors="replace")[-1500:]
            )
        return result.stdout if binary else result.stdout.decode("utf-8", errors="replace")

    def install(self, artifact, fresh=False):
        result = self.command("install", "-r", str(artifact), timeout=180)
        if "Success" not in result:
            raise RuntimeError("APK installation did not report success: " + result[-1500:])
        # Bind the requested package to the exact installed artifact, not an old app.
        paths = self.command("shell", "pm", "path", self.package).strip().splitlines()
        if len(paths) != 1 or not paths[0].startswith("package:/data/app/"):
            raise RuntimeError("Expected one installed base APK for the requested package")
        installed = paths[0].removeprefix("package:").strip()
        if not re.fullmatch(r"/data/app/[a-zA-Z0-9_./=+~\-]+\.apk", installed):
            raise RuntimeError("Unexpected installed APK path")
        payload = self.command("exec-out", "cat", installed, binary=True, timeout=60)
        if hashlib.sha256(payload).hexdigest() != file_record(artifact)["sha256"]:
            raise RuntimeError("Installed package bytes do not match the supplied APK")
        if fresh and "Success" not in self.command("shell", "pm", "clear", self.package):
            raise RuntimeError("Could not reset fixture data on the selected emulator")
        self.current_artifact = artifact

    def launch(self, smoke_label=None):
        result = self.command("shell", "am", "start", "-W", "-n", self.package + "/.MainActivity")
        if "Error" in result or "Exception" in result:
            raise RuntimeError("Activity launch failed: " + result[-1500:])
        if smoke_label is not None:
            wait_for(lambda: smoke_label in self.labels(), smoke_label)
            return
        wait_for(
            lambda: expected_counts(0, 0) in self.labels() or self.has_counts(),
            "Task Ledger screen",
        )

    def close(self):
        self.command("shell", "am", "force-stop", self.package)

    def hierarchy(self):
        remote = "/sdcard/dsgpt-task-ledger-acceptance.xml"
        self.command("shell", "uiautomator", "dump", remote, timeout=30)
        raw = self.command("exec-out", "cat", remote)
        return ET.fromstring(raw), raw

    def labels(self):
        root, _ = self.hierarchy()
        return [node.get("text", "") for node in root.iter("node") if node.get("text")]

    def has_counts(self):
        return any(
            re.fullmatch(r"Total: \d+ \| Active: \d+ \| Done: \d+", text) for text in self.labels()
        )

    def node(self, label, field=False):
        root, _ = self.hierarchy()
        attribute = "content-desc" if field else "text"
        found = [node for node in root.iter("node") if node.get(attribute) == label]
        if len(found) != 1:
            raise RuntimeError(f"Expected one {attribute}={label!r}, found {len(found)}")
        return found[0]

    def tap(self, label, field=False):
        # ElementTree leaf nodes are falsey even when a visible control was found.
        node = wait_for(lambda: (self.node(label, field),), f"visible control {label}")[0]
        bounds = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.get("bounds", ""))
        if not bounds:
            raise RuntimeError("Control has no valid UI bounds: " + label)
        left, top, right, bottom = map(int, bounds.groups())
        if right <= left or bottom <= top:
            raise RuntimeError("Control is not visible: " + label)
        self.command("shell", "input", "tap", str((left + right) // 2), str((top + bottom) // 2))

    def field(self, name, value):
        # ADB's input command is not a general Unicode IME. Domain acceptance covers
        # Unicode; this native-control scenario deliberately uses ASCII input only.
        if not re.fullmatch(r"[A-Za-z0-9 ._\-]*", value):
            raise ValueError("Native ADB typing fixture only supports its declared ASCII values")
        self.tap(name, field=True)
        self.command("shell", "input", "keycombination", "KEYCODE_CTRL_LEFT", "KEYCODE_A")
        self.command("shell", "input", "keyevent", "KEYCODE_DEL")
        if value:
            self.command("shell", "input", "text", value.replace(" ", "%s"))
        self.command("shell", "input", "keyevent", "KEYCODE_ESCAPE")

    def click(self, label):
        self.tap(label)

    def select(self, label):
        self.tap(label)

    def filter(self, label):
        self.tap(label)

    def editor(self):
        values = {}
        for name in ("Title", "Notes", "Priority"):
            node = self.node(name, field=True)
            edits = [
                item for item in node.iter("node") if item.get("class") == "android.widget.EditText"
            ]
            if len(edits) != 1:
                raise RuntimeError("Expected one observable native editor for " + name)
            values[name] = edits[0].get("text", "")
        return values

    def observe(self):
        labels = self.labels()
        counts = [
            value
            for value in labels
            if re.fullmatch(r"Total: \d+ \| Active: \d+ \| Done: \d+", value)
        ]
        if len(counts) != 1:
            raise RuntimeError("Expected one observable global task count")
        rows = [
            value
            for value in labels
            if re.fullmatch(r"#\d+ .+ \| Priority [0-2] \| (?:Active|Done)", value)
        ]
        return {"counts": counts[0], "rows": rows}

    def snapshot(self, name):
        _, xml = self.hierarchy()
        (self.directory / (name + ".xml")).write_text(xml, encoding="utf-8")
        image = self.command("exec-out", "screencap", "-p", binary=True)
        if not image.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError("Emulator did not produce a PNG screenshot")
        (self.directory / (name + ".png")).write_bytes(image)
        return [name + ".xml", name + ".png"]


class Windows:
    def __init__(self, args, directory):
        if os.name != "nt":
            raise RuntimeError("Windows native acceptance must run on a Windows worker")
        import ctypes
        from ctypes import wintypes

        self.ctypes, self.wintypes, self.directory = ctypes, wintypes, directory
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.gdi = ctypes.WinDLL("gdi32", use_last_error=True)
        self.user.SendMessageTimeoutW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            ctypes.c_size_t,
            ctypes.c_ssize_t,
            wintypes.UINT,
            wintypes.UINT,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        self.user.SendMessageTimeoutW.restype = ctypes.c_ssize_t
        self.user.GetDlgItem.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user.GetDlgItem.restype = wintypes.HWND
        self.user.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.user.GetWindowThreadProcessId.restype = wintypes.DWORD
        self.user.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user.IsWindowVisible.argtypes = [wintypes.HWND]
        self.user.PostMessageW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            ctypes.c_size_t,
            ctypes.c_ssize_t,
        ]
        self.user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        self.user.EnumWindows.argtypes = [self.callback_type, wintypes.LPARAM]
        self.process = self.window = self.current_artifact = self.log = None
        self.profile = tempfile.TemporaryDirectory(prefix="dsgpt-ledger-native-")
        self.environment = os.environ.copy()
        self.environment["LOCALAPPDATA"] = self.profile.name
        self.environment["APPDATA"] = self.profile.name
        self.environment["TEMP"] = self.profile.name
        self.environment["TMP"] = self.profile.name

    def install(self, artifact, fresh=False):
        if self.process is not None:
            raise RuntimeError("Close the prior application before choosing an update")
        self.current_artifact = Path(artifact).resolve()

    def launch(self, smoke_label=None):
        if self.current_artifact is None:
            raise RuntimeError("No Windows executable supplied")
        self.log = (self.directory / "windows-process.log").open("ab")
        self.process = subprocess.Popen(
            [str(self.current_artifact)],
            cwd=self.profile.name,
            env=self.environment,
            stdout=self.log,
            stderr=subprocess.STDOUT,
        )

        def find_window():
            if self.process.poll() is not None:
                raise RuntimeError(
                    f"Application exited before opening its window: {self.process.returncode}"
                )
            matches = []

            @self.callback_type
            def collect(handle, _):
                process_id = self.wintypes.DWORD()
                self.user.GetWindowThreadProcessId(handle, self.ctypes.byref(process_id))
                name = self.ctypes.create_unicode_buffer(256)
                self.user.GetClassNameW(handle, name, len(name))
                if (
                    process_id.value == self.process.pid
                    and name.value == (APP_CLASS if smoke_label is None else "dsGPTGeneratedWindow")
                    and self.user.IsWindowVisible(handle)
                ):
                    matches.append(handle)
                return True

            self.user.EnumWindows(collect, 0)
            return matches[0] if len(matches) == 1 else None

        self.window = wait_for(find_window, "the launched process's Task Ledger window")
        if smoke_label is not None:
            wait_for(lambda: self.text(self.window) == smoke_label, smoke_label)
            return
        for name in ("Title", "Notes", "Priority", "Search", "filter", "rows", "counts"):
            self.control(name)

    def close(self):
        if self.process is None:
            return
        try:
            if self.process.poll() is None:
                self.user.PostMessageW(self.window, 0x0010, 0, 0)  # WM_CLOSE
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
                    raise RuntimeError("Application failed to close normally") from None
            if self.process.returncode != 0:
                raise RuntimeError(f"Application exited with {self.process.returncode}")
        finally:
            self.process = self.window = None
            if self.log:
                self.log.close()
                self.log = None

    def cleanup(self):
        try:
            self.close()
        finally:
            self.profile.cleanup()

    def control(self, name):
        handle = self.user.GetDlgItem(self.window, IDS[name])
        if not handle:
            raise RuntimeError(f"Required native control {name!r} (ID {IDS[name]}) is missing")
        return handle

    def send(self, handle, message, first=0, second=0):
        result = self.ctypes.c_size_t()
        self.ctypes.set_last_error(0)
        completed = self.user.SendMessageTimeoutW(
            handle,
            message,
            first,
            second,
            0x0001 | 0x0002 | 0x0020,  # BLOCK | ABORTIFHUNG | ERRORONEXIT
            WINDOW_MESSAGE_TIMEOUT_MS,
            self.ctypes.byref(result),
        )
        if not completed:
            code = self.ctypes.get_last_error()
            raise RuntimeError(
                f"Native message 0x{message:04x} timed out or failed (Win32 error {code})"
            )
        # List/combo messages return signed LB_ERR/CB_ERR through an unsigned DWORD_PTR.
        return self.ctypes.c_ssize_t(result.value).value

    def text(self, handle):
        size = self.send(handle, 0x000E)  # WM_GETTEXTLENGTH
        if size < 0 or size > 16384:
            raise RuntimeError("Native control text length is invalid")
        value = self.ctypes.create_unicode_buffer(size + 1)
        self.send(handle, 0x000D, len(value), self.ctypes.addressof(value))
        return value.value

    def field(self, name, value):
        buffer = self.ctypes.create_unicode_buffer(value)
        handle = self.control(name)
        if not self.send(handle, 0x000C, 0, self.ctypes.addressof(buffer)):  # WM_SETTEXT
            raise RuntimeError("Native control did not accept text: " + name)
        if self.text(handle) != value:
            raise RuntimeError("Native edit value differs from supplied input: " + name)
        self.send(self.window, 0x0111, IDS[name] | (0x0300 << 16), handle)  # EN_CHANGE

    def click(self, label):
        self.send(self.control(label), 0x00F5)  # BM_CLICK

    def filter(self, label):
        index = ("All", "Active", "Done").index(label)
        handle = self.control("filter")
        if self.send(handle, 0x014E, index) != index:  # CB_SETCURSEL
            raise RuntimeError("Could not change native filter")
        self.send(self.window, 0x0111, IDS["filter"] | (1 << 16), handle)

    def rows(self):
        handle = self.control("rows")
        count = self.send(handle, 0x018B)  # LB_GETCOUNT
        if count < 0 or count > 1000:
            raise RuntimeError("Unexpected native list length")
        values = []
        for index in range(count):
            size = self.send(handle, 0x018A, index)  # LB_GETTEXTLEN
            if size < 0 or size > 16384:
                raise RuntimeError("Unexpected native row length")
            text = self.ctypes.create_unicode_buffer(size + 1)
            self.send(handle, 0x0189, index, self.ctypes.addressof(text))  # LB_GETTEXT
            values.append(text.value)
        return values

    def select(self, label):
        values = self.rows()
        if values.count(label) != 1:
            raise RuntimeError("Expected one selectable task row: " + label)
        index, handle = values.index(label), self.control("rows")
        if self.send(handle, 0x0186, index) != index:  # LB_SETCURSEL
            raise RuntimeError("Native task selection failed")
        self.send(self.window, 0x0111, IDS["rows"] | (1 << 16), handle)

    def observe(self):
        return {"counts": self.text(self.control("counts")), "rows": self.rows()}

    def editor(self):
        return {name: self.text(self.control(name)) for name in ("Title", "Notes", "Priority")}

    def snapshot(self, name):
        # Read visible window pixels without asking an untrusted window procedure to
        # render. PrintWindow can block forever inside a hung application. Occlusion
        # can affect this screen capture; semantic checks do not depend on its pixels.
        ctypes, wintypes = self.ctypes, self.wintypes
        self.user.GetWindowDC.argtypes = [wintypes.HWND]
        self.user.GetWindowDC.restype = wintypes.HDC
        self.user.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        self.gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]
        self.gdi.CreateCompatibleDC.restype = wintypes.HDC
        self.gdi.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
        self.gdi.CreateCompatibleBitmap.restype = wintypes.HBITMAP
        self.gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
        self.gdi.SelectObject.restype = wintypes.HANDLE
        self.gdi.BitBlt.argtypes = [
            wintypes.HDC,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HDC,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.DWORD,
        ]
        self.gdi.BitBlt.restype = wintypes.BOOL
        self.gdi.GetDIBits.argtypes = [
            wintypes.HDC,
            wintypes.HBITMAP,
            wintypes.UINT,
            wintypes.UINT,
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.UINT,
        ]
        self.gdi.DeleteObject.argtypes = [wintypes.HANDLE]
        self.gdi.DeleteDC.argtypes = [wintypes.HDC]
        rectangle = wintypes.RECT()
        if not self.user.GetWindowRect(self.window, ctypes.byref(rectangle)):
            raise RuntimeError("Could not obtain the native window dimensions")
        width, height = rectangle.right - rectangle.left, rectangle.bottom - rectangle.top
        if not 1 <= width <= 4096 or not 1 <= height <= 4096:
            raise RuntimeError("Unexpected native window dimensions")
        original = self.user.GetWindowDC(self.window)
        memory = self.gdi.CreateCompatibleDC(original)
        bitmap = self.gdi.CreateCompatibleBitmap(original, width, height)
        previous = self.gdi.SelectObject(memory, bitmap)
        try:
            if not self.gdi.BitBlt(memory, 0, 0, width, height, original, 0, 0, 0x40CC0020):
                raise RuntimeError("Could not capture the visible native window")
            self.gdi.SelectObject(memory, previous)
            pixels = ctypes.create_string_buffer(width * height * 4)
            header = struct.pack(
                "<IiiHHIIiiII", 40, width, -height, 1, 32, 0, len(pixels), 0, 0, 0, 0
            )
            info = ctypes.create_string_buffer(header)
            if self.gdi.GetDIBits(memory, bitmap, 0, height, pixels, info, 0) != height:
                raise RuntimeError("Could not read the native window screenshot")
            payload = (
                struct.pack("<2sIHHI", b"BM", 54 + len(pixels), 0, 0, 54) + header + pixels.raw
            )
            (self.directory / (name + ".bmp")).write_bytes(payload)
            (self.directory / (name + ".json")).write_text(
                json.dumps(
                    {
                        **self.observe(),
                        "capture_method": "visible_window_dc_bitblt",
                        "occlusion_possible": True,
                    },
                    indent=2,
                )
                + "\n"
            )
            return [name + ".bmp", name + ".json"]
        finally:
            self.gdi.SelectObject(memory, previous)
            self.gdi.DeleteObject(bitmap)
            self.gdi.DeleteDC(memory)
            self.user.ReleaseDC(self.window, original)


class Scenario:
    def __init__(self, driver, report, output):
        self.driver, self.report, self.output = driver, report, output

    def save(self):
        self.output.write_text(json.dumps(self.report, indent=2) + "\n", encoding="utf-8")

    def verify(self, name, total, active, rows):
        wanted = {"counts": expected_counts(total, active), "rows": sorted(rows)}
        last = None

        def matches():
            nonlocal last
            last = self.driver.observe()
            return last["counts"] == wanted["counts"] and sorted(last["rows"]) == wanted["rows"]

        try:
            wait_for(matches, name)
            images = self.driver.snapshot(f"{len(self.report['checks']) + 1:02d}-{name}")
        except Exception:
            self.report["checks"].append(
                {"name": name, "passed": False, "expected": wanted, "observed": last}
            )
            self.save()
            raise
        self.report["checks"].append(
            {"name": name, "passed": True, "expected": wanted, "observed": last, "evidence": images}
        )
        self.save()

    def add(self, title, notes, priority):
        for name, value in (("Title", title), ("Notes", notes), ("Priority", str(priority))):
            self.driver.field(name, value)
        self.driver.click("Add")

    def verify_editor(self, name, row, title, notes, priority):
        self.driver.select(row)
        wanted = {"Title": title, "Notes": notes, "Priority": str(priority)}
        last = None

        def matches():
            nonlocal last
            last = self.driver.editor()
            return last == wanted

        try:
            wait_for(matches, name)
            images = self.driver.snapshot(f"{len(self.report['checks']) + 1:02d}-{name}")
        except Exception:
            self.report["checks"].append(
                {"name": name, "passed": False, "expected": wanted, "observed": last}
            )
            self.save()
            raise
        self.report["checks"].append(
            {"name": name, "passed": True, "expected": wanted, "observed": last, "evidence": images}
        )
        self.save()

    def initial(self):
        d = self.driver
        alpha = expected_row(1, "Pay invoice", 1)
        beta = expected_row(2, "Book service", 2)
        renamed = expected_row(1, "Pay invoice today", 1)
        done = expected_row(1, "Pay invoice today", 1, True)
        gamma = expected_row(3, "Confirm booking", 0)
        self.verify("fresh-empty", 0, 0, [])
        self.add("   ", "", 0)
        self.verify("blank-title-rejected", 0, 0, [])
        self.add("Pay invoice", "Keep receipt", 1)
        self.verify("first-task-added", 1, 1, [alpha])
        self.add("Book service", "Bring records", 2)
        self.verify("second-task-added", 2, 2, [alpha, beta])
        d.field("Search", "INVOICE")
        self.verify("case-insensitive-search", 2, 2, [alpha])
        d.field("Search", "")
        d.select(alpha)
        d.field("Title", "Pay invoice today")
        d.field("Notes", "Receipt attached")
        d.click("Save edit")
        self.verify("edit-keeps-id-and-other-task", 2, 2, [renamed, beta])
        d.select(renamed)
        d.click("Toggle done")
        self.verify("completion-counts", 2, 1, [done, beta])
        d.filter("Done")
        self.verify("done-filter", 2, 1, [done])
        d.filter("Active")
        self.verify("active-filter", 2, 1, [beta])
        d.filter("All")
        d.close()
        d.launch()
        self.verify("first-process-restart-preserves-tasks", 2, 1, [done, beta])
        self.verify_editor(
            "restart-reloads-edited-fields", done, "Pay invoice today", "Receipt attached", 1
        )
        d.select(beta)
        d.click("Delete")
        self.verify("delete-preserves-unselected-task", 1, 0, [done])
        self.add("Confirm booking", "New identifier", 0)
        self.verify("deleted-id-not-reused", 2, 1, [done, gamma])
        d.close()
        d.launch()
        self.verify("second-process-restart-preserves-edits", 2, 1, [done, gamma])
        self.report["initial_native_passed"] = True
        self.save()

    def update(self, artifact):
        d = self.driver
        done = expected_row(1, "Pay invoice today", 1, True)
        active = expected_row(3, "Confirm booking", 0)
        d.close()
        d.install(artifact, fresh=False)
        d.launch()
        self.verify("update-preserves-existing-data", 2, 1, [done, active])
        self.verify_editor(
            "update-reloads-edited-fields", done, "Pay invoice today", "Receipt attached", 1
        )
        d.click("Clear completed")
        self.verify("clear-completed-keeps-active", 1, 1, [active])
        d.close()
        d.launch()
        self.verify("followup-restart-preserves-active", 1, 1, [active])
        self.verify_editor(
            "followup-reloads-active-fields", active, "Confirm booking", "New identifier", 0
        )
        self.report["followup_native_passed"] = True
        self.save()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=("android", "windows"), required=True)
    parser.add_argument("--initial", type=Path, required=True, help="Actual initial APK or EXE")
    parser.add_argument(
        "--updated", type=Path, help="Actual follow-up APK or EXE with Clear completed"
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New report file; existing reports are not overwritten",
    )
    parser.add_argument(
        "--artifact-origin",
        choices=("reviewed-fixture", "model-generated", "unspecified"),
        default="unspecified",
    )
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--serial", help="Required emulator-<port> for Android")
    parser.add_argument("--package", help="Required generated application ID for Android")
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("Choose a new report path so prior native evidence is preserved")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    evidence = args.output.parent / (args.output.stem + "-evidence")
    evidence.mkdir(exist_ok=False)
    report = {
        "format": "dsgpt-complex-app-native-v1",
        "platform": args.platform,
        "artifact_origin_declared": args.artifact_origin,
        "model_actions_verified": False,
        "initial_artifact": file_record(args.initial),
        "updated_artifact": file_record(args.updated) if args.updated else None,
        "initial_native_passed": None,
        "followup_native_passed": None,
        "passed": False,
        "checks": [],
        "evidence_directory": evidence.name,
        "limits": [
            "A bounded Task Ledger control scenario, not arbitrary-app completeness "
            "or visual design approval.",
            "Actual native controls and persisted state are observed; "
            "application self-test claims are not used.",
            "Android UI typing uses ASCII; Unicode behavior belongs to "
            "the independent domain test suite.",
            "No inference, compilation, isolation or source-to-binary provenance "
            "claim is established by this script.",
        ],
    }
    driver = None
    started = time.monotonic()
    try:
        driver = Android(args, evidence) if args.platform == "android" else Windows(args, evidence)
        driver.install(args.initial.resolve(), fresh=True)
        driver.launch()
        scenario = Scenario(driver, report, args.output)
        scenario.initial()
        if args.updated:
            scenario.update(args.updated.resolve())
        driver.close()
        report["passed"] = report["initial_native_passed"] and (
            args.updated is None or report["followup_native_passed"]
        )
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        if driver:
            try:
                report["failure_evidence"] = driver.snapshot("failure")
            except Exception as screenshot_error:
                report["failure_capture_error"] = str(screenshot_error)
    finally:
        if driver:
            try:
                driver.cleanup() if isinstance(driver, Windows) else driver.close()
            except Exception as cleanup_error:
                report["cleanup_error"] = str(cleanup_error)
                report["passed"] = False
        report["elapsed_seconds"] = round(time.monotonic() - started, 2)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {"passed": report["passed"], "report": str(args.output), "error": report.get("error")}
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
