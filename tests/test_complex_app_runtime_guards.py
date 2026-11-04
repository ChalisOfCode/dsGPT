"""Native harness guard regressions using OS-wrapper fixtures, not native app evidence."""

import ctypes
import importlib.util
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    "complex_runtime_guards",
    Path(__file__).resolve().parents[1] / "scripts/check_complex_app_runtime.py",
)
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


def test_android_taps_a_found_leaf_without_waiting_for_children(monkeypatch):
    driver = native.Android.__new__(native.Android)
    driver.node = lambda *_: ET.fromstring('<node text="Add" bounds="[10,20][30,40]"/>')
    calls = []
    driver.command = lambda *args, **kwargs: calls.append(args)
    monkeypatch.setattr(native.time, "sleep", lambda _: pytest.fail("Found leaf was retried"))
    driver.tap("Add")
    assert calls == [("shell", "input", "tap", "20", "30")]


@pytest.mark.parametrize("bounds", ["[0,0][0,0]", "invalid"])
def test_android_does_not_tap_a_control_without_visible_bounds(bounds):
    driver = native.Android.__new__(native.Android)
    driver.node = lambda *_: ET.fromstring(f'<node text="Add" bounds="{bounds}"/>')
    driver.command = lambda *_args, **_kwargs: pytest.fail("Invisible control was tapped")
    with pytest.raises(RuntimeError, match="not visible|no valid UI bounds"):
        driver.tap("Add")


def installed_apk_driver(package_path, installed_bytes):
    driver = native.Android.__new__(native.Android)
    driver.package = "com.dsgpt.generated.p123"
    calls = []

    def command(*args, **kwargs):
        calls.append(args)
        if args[0] == "install":
            return "Success\n"
        if args[:3] == ("shell", "pm", "path"):
            return "package:" + package_path + "\n"
        if args[:2] == ("exec-out", "cat"):
            assert args[2] == package_path and kwargs["binary"] is True
            return installed_bytes
        pytest.fail("Unexpected OS-wrapper request: " + repr(args))

    driver.command = command
    return driver, calls


@pytest.mark.parametrize(
    "installed_path",
    [
        "/data/app/~~mBqOZ2+6w==/com.dsgpt.generated.p123-aBc_12==/base.apk",
        "/data/app/com.dsgpt.generated.p123-1/base.apk",
    ],
)
def test_installed_apk_guard_accepts_tilde_paths_and_verifies_bytes(tmp_path, installed_path):
    # Opaque bytes exercise path/hash guards only; this is not an installable APK.
    artifact = tmp_path / "guard-fixture.apk"
    artifact.write_bytes(b"opaque byte fixture")
    driver, calls = installed_apk_driver(installed_path, artifact.read_bytes())
    driver.install(artifact)
    assert driver.current_artifact == artifact
    assert calls[-1] == ("exec-out", "cat", installed_path)


def test_installed_apk_guard_rejects_different_bytes(tmp_path):
    artifact = tmp_path / "guard-fixture.apk"
    artifact.write_bytes(b"expected")
    driver, _ = installed_apk_driver("/data/app/~~install/package/base.apk", b"old package")
    with pytest.raises(RuntimeError, match="bytes do not match"):
        driver.install(artifact)
    assert not hasattr(driver, "current_artifact")


def test_android_editor_reads_values_instead_of_accessibility_labels():
    driver = native.Android.__new__(native.Android)
    root = ET.fromstring("""<hierarchy>
      <node content-desc="Title" class="android.widget.EditText" text="Pay invoice today"/>
      <node content-desc="Notes" class="android.view.View">
        <node class="android.widget.EditText" text="Receipt attached"/>
      </node>
      <node content-desc="Priority" class="android.widget.EditText" text="1"/>
    </hierarchy>""")
    driver.hierarchy = lambda: (root, "")
    assert driver.editor() == {
        "Title": "Pay invoice today",
        "Notes": "Receipt attached",
        "Priority": "1",
    }


def test_android_editor_rejects_ambiguous_editable_values():
    driver = native.Android.__new__(native.Android)
    root = ET.fromstring("""<hierarchy><node content-desc="Title">
      <node class="android.widget.EditText" text="one"/>
      <node class="android.widget.EditText" text="two"/>
    </node></hierarchy>""")
    driver.hierarchy = lambda: (root, "")
    with pytest.raises(RuntimeError, match="one observable native editor"):
        driver.editor()


def windows_message_driver(completed, result_value=0):
    driver = native.Windows.__new__(native.Windows)
    calls = []

    def send_timeout(handle, message, first, second, flags, timeout, result):
        calls.append((handle, message, first, second, flags, timeout))
        result._obj.value = result_value
        return completed

    # These are ctypes/Win32 wrapper fixtures. No window or application is created.
    driver.ctypes = SimpleNamespace(
        c_size_t=ctypes.c_size_t,
        c_ssize_t=ctypes.c_ssize_t,
        byref=ctypes.byref,
        set_last_error=lambda _: None,
        get_last_error=lambda: 1460,
    )
    driver.user = SimpleNamespace(SendMessageTimeoutW=send_timeout)
    return driver, calls


def test_windows_messages_have_fixed_deadline_and_keep_signed_error_result():
    driver, calls = windows_message_driver(True, ctypes.c_size_t(-1).value)
    assert driver.send(123, 0x0186, 2, 0) == -1
    assert calls == [(123, 0x0186, 2, 0, 0x0001 | 0x0002 | 0x0020, 5000)]


def test_hung_windows_target_reports_failure_instead_of_claiming_a_result():
    driver, calls = windows_message_driver(False)
    with pytest.raises(RuntimeError, match="timed out or failed.*1460"):
        driver.send(123, 0x000D, 10, 456)
    assert len(calls) == 1
