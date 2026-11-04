"""Bounded, read-only hardware measurements; never enumerate users or processes."""

import csv
import io
import math
import os
import re
import subprocess
from pathlib import Path

import psutil

GPU_FIELDS = (
    "name,driver_version,memory.total,memory.used,utilization.gpu,"
    "temperature.gpu,power.draw,power.limit"
)


def number(value, maximum, minimum=0):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and minimum <= result <= maximum else None


def nvidia_executable():
    # Fixed installation locations only: do not run an executable from a project or cwd.
    if os.name == "nt":
        root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
        program = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        candidates = [
            root / "System32/nvidia-smi.exe",
            program / "NVIDIA Corporation/NVSMI/nvidia-smi.exe",
        ]
    else:
        candidates = [Path("/usr/bin/nvidia-smi"), Path("/usr/local/nvidia/bin/nvidia-smi")]
    return next((str(path) for path in candidates if path.is_file()), None)


def gpu_snapshot():
    executable = nvidia_executable()
    if not executable:
        return {"status": "unavailable", "reason": "nvidia_smi_not_installed", "devices": []}
    try:
        result = subprocess.run(
            [executable, "--query-gpu=" + GPU_FIELDS, "--format=csv,noheader,nounits"],
            capture_output=True,
            timeout=2,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode or len(result.stdout) > 65536:
            raise ValueError("Unavailable measurement")
        rows = list(csv.reader(io.StringIO(result.stdout.decode("utf-8", errors="strict"))))
        if not 1 <= len(rows) <= 16 or any(len(row) != 8 for row in rows):
            raise ValueError("Invalid measurement shape")
        devices = []
        for row in rows:
            name, driver, *values = [value.strip() for value in row]
            if not re.fullmatch(r"[A-Za-z0-9 ()_.+/-]{1,100}", name):
                name = "NVIDIA GPU"
            if not re.fullmatch(r"[0-9.]{1,30}", driver):
                driver = None
            devices.append(
                {
                    "name": name,
                    "driver_version": driver,
                    "vram_total_mib": number(values[0], 2_000_000),
                    "vram_used_mib": number(values[1], 2_000_000),
                    "utilization_percent": number(values[2], 100),
                    "temperature_celsius": number(values[3], 200, -100),
                    "power_watts": number(values[4], 5000),
                    "power_limit_watts": number(values[5], 5000),
                }
            )
        return {"status": "collected", "source": "nvidia-smi", "devices": devices}
    except (OSError, subprocess.TimeoutExpired, ValueError):
        # Driver errors can contain local paths. Export a fixed reason, never stderr.
        return {"status": "unavailable", "reason": "nvidia_query_failed", "devices": []}


def cpu_temperature():
    collect = getattr(psutil, "sensors_temperatures", None)
    if collect is None:
        return None
    try:
        readings = collect()
        # Do not mislabel storage, motherboard or GPU sensors as CPU temperatures.
        values = [
            number(sensor.current, 200, -100)
            for key in ("coretemp", "k10temp", "cpu_thermal")
            for sensor in readings.get(key, [])
        ]
        return max((value for value in values if value is not None), default=None)
    except (OSError, psutil.Error, NotImplementedError):
        return None
