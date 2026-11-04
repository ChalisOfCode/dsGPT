"""Local prerequisite helpers. Never infer readiness from an installer exit alone."""

import base64
import ipaddress
import os
import subprocess
import sys
import time
from pathlib import Path


class Blocked(Exception):
    """An external prerequisite is unavailable or was explicitly skipped."""


class RestartRequired(Exception):
    """Windows setup needs a reboot before dependent checks can run."""


def interactive(ci=False):
    return not ci and os.name == "nt" and bool(sys.stdin and sys.stdin.isatty())


def skip_pressed():
    import msvcrt

    return msvcrt.kbhit() and msvcrt.getwch().lower() == "s"


def wait_ready(probe, message, *, ci=False, timeout=120, interval=2):
    """Keep detecting while a person fixes setup; S skips without a false pass."""
    started = time.monotonic()
    last_message = None
    last_print = started - 30
    while True:
        value, detail = probe()
        if value:
            return value
        now = time.monotonic()
        if detail != last_message or now - last_print >= 30:
            print("  " + message + "\n  " + detail, flush=True)
            if interactive(ci):
                print(
                    "  Checking automatically. Press S to skip this step, or Ctrl+C to stop.",
                    flush=True,
                )
            last_message, last_print = detail, now
        if interactive(ci):
            if skip_pressed():
                raise Blocked("Skipped by user: " + detail)
        elif now - started >= (5 if ci else timeout):
            raise Blocked(detail + " (Unattended wait expired.)")
        time.sleep(interval)


def adb_devices(output):
    """Return states without exposing serial numbers in the shareable report."""
    devices = []
    for line in output.decode(errors="replace").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] in {"device", "offline", "unauthorized", "recovery"}:
            devices.append((parts[0], parts[1]))
    return devices


def adb_guidance(devices):
    if len(devices) > 1:
        return "Several Android devices are visible. Disconnect the others; keep your Pixel."
    state = devices[0][1] if devices else "missing"
    return {
        "unauthorized": "Windows sees the Pixel and is waiting for phone authorization. "
        "Unlock it and tap Allow in 'Allow USB debugging?' (the RSA fingerprint prompt). "
        "The USB debugging toggle alone does not approve this computer. "
        "If the dialog is hidden, unplug/reconnect once with the phone unlocked.",
        "offline": "ADB sees the Pixel but it is offline. Reconnect the USB cable with the "
        "phone unlocked; detection will continue here.",
        "recovery": "The phone is in recovery mode. Restart it normally and unlock it.",
        "missing": "ADB cannot see a device yet. Keep USB debugging on. Reconnect directly "
        "to the PC using a data-capable cable; try another USB port/cable if needed. "
        "Charging by itself does not confirm a data connection. In the phone's USB "
        "notification, select File transfer / Android Auto if available.",
    }.get(state, "Pixel detected; verifying authorized access.")


def powershell(command, script, timeout=120):
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    return command(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded], timeout
    )


def ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def elevated(command, program, arguments, timeout=900):
    # Use a structured executable plus Windows argv quoting, never a generated shell command.
    script = "$ErrorActionPreference='Stop'; try { $p=Start-Process -FilePath "
    script += ps_quote(program) + " -ArgumentList " + ps_quote(subprocess.list2cmdline(arguments))
    script += " -Verb RunAs -Wait -PassThru; exit $p.ExitCode } catch { exit 1223 }"
    return powershell(command, script, timeout)


def resume_after_reboot(kit, enable, wireless=False):
    """One launch after the next sign-in, removed after normal completion/cancellation."""
    if os.name != "nt":
        return
    import winreg

    key_name = r"Software\Microsoft\Windows\CurrentVersion\RunOnce"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_name) as key:
        if enable:
            argv = [sys.executable, "-B", "-I", "-m", "dsgpt_acceptance", "--kit", str(kit)]
            if wireless:
                argv.append("--wireless")
            winreg.SetValueEx(
                key, "dsGPTAcceptanceResume", 0, winreg.REG_SZ, subprocess.list2cmdline(argv)
            )
        else:
            try:
                winreg.DeleteValue(key, "dsGPTAcceptanceResume")
            except FileNotFoundError:
                pass


def docker_locations():
    return [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/DockerDesktop",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Docker/Docker",
    ]


def google_usb_inventory(command):
    # No device serials or friendly names leave the private machine.
    result = powershell(
        command,
        "$d=@(Get-CimInstance Win32_PnPEntity | Where-Object { "
        "$_.PNPDeviceID -like 'USB\\VID_18D1*' }); "
        "[pscustomobject]@{google_usb_devices=$d.Count; "
        "driver_problem_count=@($d | Where-Object { $_.ConfigManagerErrorCode -ne 0 }).Count} "
        "| ConvertTo-Json -Compress",
        30,
    )
    return result


def wireless_endpoint(value):
    """Only literal local-network endpoints from the phone's debugging screen."""
    host, separator, port = value.strip().rpartition(":")
    if not separator or not port.isascii() or not port.isdecimal() or not 1 <= int(port) <= 65535:
        raise ValueError("Enter the phone's IP address and port, for example 192.168.1.20:37001.")
    address = ipaddress.ip_address(host.strip("[]"))
    tailnet = address.version == 4 and address in ipaddress.ip_network("100.64.0.0/10")
    if (not address.is_private and not tailnet) or any(
        (address.is_loopback, address.is_unspecified, address.is_multicast)
    ):
        raise ValueError("Use the private address displayed by your phone.")
    return (f"[{address}]" if address.version == 6 else str(address)) + ":" + str(int(port))


def wireless_serial(serial):
    if "_adb-tls-connect._tcp" in serial:
        return True
    try:
        wireless_endpoint(serial)
        return True
    except ValueError:
        return False


def pairing_endpoints(output):
    endpoints = []
    for line in output.decode(errors="replace").splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[-2].rstrip(".") == "_adb-tls-pairing._tcp":
            try:
                endpoint = wireless_endpoint(parts[-1])
            except ValueError:
                continue
            if endpoint not in endpoints:
                endpoints.append(endpoint)
    return endpoints
