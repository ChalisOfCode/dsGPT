"""Opt-in, current-user Windows Task Scheduler ownership and crash restart policy.

Only the fixed managed backend may be scheduled. No passwords, elevation, remote
task administration, arbitrary command input or process termination is supported.
"""

import base64
import ctypes
import json
import os
import subprocess
from pathlib import Path

# Fixed program; installation paths are data in the child environment, never code.
SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
try {
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $sid = $identity.User.Value
    $name = 'dsGPT-Managed-' + $sid
    $root = [System.IO.Path]::GetFullPath($env:DSGPT_STARTUP_INSTALL)
    $exe = [System.IO.Path]::Combine($root, 'python\pythonw.exe')
    $mode = $env:DSGPT_STARTUP_OPERATION
    if ($mode -notin @('status', 'enable', 'disable', 'run')) { throw 'operation' }
    $service = New-Object -ComObject 'Schedule.Service'
    $service.Connect()
    $folder = $service.GetFolder('\')
    $task = $null
    try { $task = $folder.GetTask($name) } catch {
        $errorObject = $_.Exception
        $missing = $false
        while ($null -ne $errorObject) {
            if ($errorObject.HResult -eq -2147024894) { $missing = $true }
            $errorObject = $errorObject.InnerException
        }
        if (-not $missing) { throw }
    }
    function SameUser($value) {
        if ($value -eq $sid) { return $true }
        try {
            $account = New-Object System.Security.Principal.NTAccount($value)
            return $account.Translate([System.Security.Principal.SecurityIdentifier]).Value -eq $sid
        } catch { return $false }
    }
    function Owned($candidate) {
        $d = $candidate.Definition
        if ($d.RegistrationInfo.Source -ne 'dsGPT managed startup v2' -or
            $d.Actions.Count -ne 1 -or $d.Triggers.Count -ne 1 -or
            -not (SameUser $d.Principal.UserId) -or
            $d.Principal.LogonType -ne 3 -or $d.Principal.RunLevel -ne 0) { return $false }
        $a = $d.Actions.Item(1)
        $t = $d.Triggers.Item(1)
        $s = $d.Settings
        return ($a.Type -eq 0 -and $a.Path -eq $exe -and
            $a.Arguments -ceq '-I -m dsgpt.supervisor' -and
            $a.WorkingDirectory -eq $root -and $t.Type -eq 9 -and
            (SameUser $t.UserId) -and $t.Enabled -and
            $s.MultipleInstances -eq 2 -and $s.RestartCount -eq 0 -and
            $s.ExecutionTimeLimit -eq 'PT0S' -and
            -not $s.DisallowStartIfOnBatteries -and -not $s.StopIfGoingOnBatteries -and
            -not $s.RunOnlyIfNetworkAvailable -and -not $s.RunOnlyIfIdle -and
            -not $s.AllowHardTerminate -and -not $s.WakeToRun -and $s.AllowDemandStart)
    }
    if ($null -ne $task -and -not (Owned $task)) {
        @{error='task_conflict'} | ConvertTo-Json -Compress
        exit 2
    }
    if ($mode -eq 'enable') {
        if ($null -eq $task) {
            $d = $service.NewTask(0)
            $d.RegistrationInfo.Source = 'dsGPT managed startup v2'
            $d.RegistrationInfo.Description = 'dsGPT backend: three retries, one minute apart.'
            $d.Principal.UserId = $sid
            $d.Principal.LogonType = 3
            $d.Principal.RunLevel = 0
            $t = $d.Triggers.Create(9)
            $t.UserId = $sid
            $t.Enabled = $true
            $t.Delay = 'PT10S'
            $a = $d.Actions.Create(0)
            $a.Path = $exe
            $a.Arguments = '-I -m dsgpt.supervisor'
            $a.WorkingDirectory = $root
            $s = $d.Settings
            $s.Enabled = $true
            $s.MultipleInstances = 2
            $s.RestartCount = 0
            $s.ExecutionTimeLimit = 'PT0S'
            $s.DisallowStartIfOnBatteries = $false
            $s.StopIfGoingOnBatteries = $false
            $s.RunOnlyIfNetworkAvailable = $false
            $s.RunOnlyIfIdle = $false
            $s.AllowHardTerminate = $false
            $s.WakeToRun = $false
            $s.AllowDemandStart = $true
            # TASK_CREATE only: a concurrent/foreign registration is never overwritten.
            $task = $folder.RegisterTaskDefinition($name, $d, 2, $sid, $null, 3, $null)
        } else { $task.Enabled = $true }
        $task = $folder.GetTask($name)
        if (-not (Owned $task) -or -not $task.Enabled) { throw 'verification' }
    } elseif ($mode -eq 'disable' -and $null -ne $task) {
        $folder.DeleteTask($name, 0)
        $task = $null
    } elseif ($mode -eq 'run' -and $null -ne $task -and $task.Enabled) {
        $null = $task.Run($null)
    }
    @{installed=($null -ne $task); enabled=($null -ne $task -and $task.Enabled);
      state=$(if ($null -ne $task) { [int]$task.State } else { 0 });
      restart_count=3; restart_interval_seconds=60; current_user_only=$true;
      requires_interactive_login=$true} | ConvertTo-Json -Compress
} catch {
    @{error='scheduler_operation_failed'} | ConvertTo-Json -Compress
    exit 1
}
"""


def powershell_path():
    if os.name != "nt":
        raise RuntimeError("Windows startup settings require Windows")
    buffer = ctypes.create_unicode_buffer(32768)
    size = ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer))
    if not size or size >= len(buffer):
        raise RuntimeError("Windows system directory unavailable")
    return Path(buffer.value) / "WindowsPowerShell/v1.0/powershell.exe"


def startup(install_dir, operation="status", *, confirm=False):
    if operation not in {"status", "enable", "disable", "run"}:
        raise ValueError("Unknown startup operation")
    if operation in {"enable", "disable"} and not confirm:
        raise RuntimeError("Confirm the Windows startup setting change explicitly")
    shell = powershell_path()
    install_dir = Path(install_dir).resolve()
    if not (install_dir / "python/pythonw.exe").is_file():
        raise RuntimeError("Bundled backend runtime is missing")
    environment = os.environ.copy()
    environment.update(DSGPT_STARTUP_INSTALL=str(install_dir), DSGPT_STARTUP_OPERATION=operation)
    try:
        result = subprocess.run(
            [
                str(shell),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-EncodedCommand",
                base64.b64encode(SCRIPT.encode("utf-16-le")).decode("ascii"),
            ],
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=30,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "Windows startup operation timed out; check startup status before retrying"
        ) from exc
    try:
        if len(result.stdout) > 65536:
            raise ValueError("response limit")
        info = json.loads(result.stdout.decode("utf-8-sig"))
        if not isinstance(info, dict):
            raise ValueError("response shape")
    except (ValueError, UnicodeDecodeError) as exc:
        raise RuntimeError("Windows startup status could not be verified") from exc
    if info.get("error") == "task_conflict":
        raise RuntimeError("An unrelated or modified startup task was preserved; change refused")
    if result.returncode or "error" in info:
        raise RuntimeError(
            "Windows Task Scheduler operation failed; check its service and permissions"
        )
    if not all(type(info.get(key)) is bool for key in ("installed", "enabled")):
        raise RuntimeError("Windows startup status could not be verified")
    return info
