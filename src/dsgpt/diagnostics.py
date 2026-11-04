import hashlib
import io
import json
import os
import platform
import time
import zipfile
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

import psutil
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import __version__
from .diagnostic_details import inference_details, recent_errors, work_details
from .diagnostic_journal import capture, export_snapshots, history
from .diagnostic_logs import build_logs
from .hardware import cpu_temperature, gpu_snapshot
from .network_diagnostics import tailscale_status
from .storage import canonical, uid, utcnow


class MobileEvent(StrEnum):
    started = "app_started"
    background = "app_backgrounded"
    foreground = "app_foregrounded"
    network = "network_unavailable"
    streaming = "stream_interrupted"
    crash = "app_crash"
    upload = "upload_failed"
    download = "download_failed"
    handled = "handled_exception"
    sync = "sync_failed"
    low_memory = "low_memory"
    anr = "app_not_responding"


class MobileTimedEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)
    code: MobileEvent
    captured_at: datetime
    correlation_id: UUID | None = None

    @field_validator("captured_at")
    @classmethod
    def valid_timestamp(cls, value):
        if value.tzinfo is None or value.timestamp() > time.time() + 300:
            raise ValueError("A valid collection time with timezone is required")
        return value.astimezone(UTC)


class MobileFailure(MobileTimedEvent):
    memory_bytes: Annotated[int, Field(ge=0, le=1_000_000_000_000)] | None = None
    latency_ms: Annotated[float, Field(ge=0, le=3_600_000)] | None = None


class MobileSnapshot(BaseModel):
    """Minimal sanitized protocol. Raw Android logs are intentionally not accepted here."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)
    consent: Literal[True]
    captured_at: datetime
    app_version: Annotated[str, Field(pattern=r"^[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}$")]
    android_api: Annotated[int, Field(ge=26, le=100)]
    memory_bytes: Annotated[int, Field(ge=0, le=1_000_000_000_000)] | None = None
    latency_ms: Annotated[float, Field(ge=0, le=3_600_000)] | None = None
    thermal_status: Annotated[int, Field(ge=0, le=6)] | None = None
    events: list[MobileEvent] = Field(default_factory=list, max_length=100)
    device_model: Annotated[str, Field(pattern=r"^[A-Za-z0-9 ._()+?-]{1,80}$")] | None = None
    startup_ms: Annotated[float, Field(ge=0, le=3_600_000)] | None = None
    startup_measurement: Literal["application_to_first_frame"] | None = None
    memory_measurement: Literal["process_pss", "java_heap"] | None = None
    frames_observed: Annotated[int, Field(ge=0, le=2_147_483_647)] | None = None
    frames_over_32ms: Annotated[int, Field(ge=0, le=2_147_483_647)] | None = None
    frame_reports_dropped: Annotated[int, Field(ge=0, le=2_147_483_647)] | None = None
    battery_level_percent: Annotated[int, Field(ge=0, le=100)] | None = None
    battery_session_delta_percent: Annotated[int, Field(ge=-100, le=100)] | None = None
    backend_reachability: Literal["not_measured", "reachable", "unreachable"] = "not_measured"
    last_http_status: Annotated[int, Field(ge=100, le=599)] | None = None
    timed_events: list[MobileTimedEvent] = Field(default_factory=list, max_length=100)
    failure_snapshots: list[MobileFailure] = Field(default_factory=list, max_length=20)
    limitations: list[
        Literal[
            "no_system_log_access",
            "battery_delta_not_app_energy",
            "thermal_unavailable",
            "crash_history_unavailable",
            "frame_metrics_unavailable",
            "memory_unavailable",
            "backend_probe_is_last_app_request",
        ]
    ] = Field(default_factory=list, max_length=10)

    @field_validator("captured_at")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None:
            raise ValueError("UTC or an explicit timezone offset is required")
        if value.timestamp() > time.time() + 300:
            raise ValueError("Collection timestamp is in the future")
        return value.astimezone(UTC)


class Diagnostics:
    def __init__(self, store, settings, builds=None):
        self.store, self.settings = store, settings
        self.builds = builds

    def desktop_snapshot(self):
        unavailable = []

        def measurement(name, collect):
            try:
                return collect()
            except (OSError, psutil.Error, NotImplementedError):
                unavailable.append(name)
                return None

        def own_memory():
            # Some managed Linux environments expose /proc from another PID namespace.
            # Never report a different process's RSS just because the numeric PID exists.
            if platform.system() == "Linux":
                from pathlib import Path

                pid = int(Path("/proc/self/stat").read_text().split(" ", 1)[0])
                if pid != os.getpid():
                    raise OSError("Process namespace mismatch")
            return psutil.Process().memory_info().rss

        memory = measurement("ram", psutil.virtual_memory)
        # psutil's Windows C extension accepts a string, not a pathlib Path.
        disk = measurement("disk", lambda: psutil.disk_usage(str(self.settings.data_dir)))
        process_rss = measurement("process_rss", own_memory)
        gpu = gpu_snapshot()
        temperature = cpu_temperature()
        if temperature is None:
            unavailable.append("cpu_temperature")
        if gpu["status"] == "unavailable":
            unavailable.append("gpu")
        return {
            "schema_version": 2,
            "app": "dsGPT",
            "app_version": __version__,
            "captured_at": utcnow(),
            "platform": platform.system(),
            "os_release": platform.release(),
            "architecture": platform.machine(),
            "cpu_logical": measurement("cpu_logical", psutil.cpu_count),
            "cpu_physical": measurement("cpu_physical", lambda: psutil.cpu_count(logical=False)),
            "cpu_utilization_percent": measurement(
                "cpu_utilization", lambda: psutil.cpu_percent(interval=0.1)
            ),
            "cpu_temperature_celsius": temperature,
            "ram_total_bytes": memory.total if memory else None,
            "ram_available_bytes": memory.available if memory else None,
            "process_rss_bytes": process_rss,
            "disk_free_bytes": disk.free if disk else None,
            "unavailable_measurements": unavailable,
            "gpu_measurement": gpu["status"],
            "gpu": gpu,
            "model_configurations": len(self.settings.models),
            "running_replies": self.store.one(
                "SELECT COUNT(*) AS n FROM runs WHERE status='running'"
            )["n"],
            "work_task_counts": self.store.all(
                "SELECT status,COUNT(*) AS count FROM work_tasks GROUP BY status"
            ),
            "work_capability": "isolated_build"
            if self.builds and self.builds.ready
            else "project_drafting",
            "code_execution_available": bool(self.builds and self.builds.ready),
            "saved_memories": self.store.one("SELECT COUNT(*) AS n FROM memories")["n"],
            "database_version": self.store.one("PRAGMA user_version")["user_version"],
            "inference": inference_details(self.store, self.settings.models),
            "work": work_details(self.store),
            "recent_errors": recent_errors(self.store),
            "snapshot_history": history(self.store),
            "logging": {
                "mode": "sanitized_event_codes",
                "event_retention": self.settings.diagnostic_event_retention,
                "mobile_snapshots_per_device": self.settings.diagnostic_retention,
                "export_preview_lifetime_seconds": 600,
                "raw_logging_enabled": False,
                "backend_snapshot_retention": self.store.diagnostic_snapshot_retention,
                "snapshot_byte_limit": self.store.diagnostic_snapshot_bytes,
                "export_byte_limit": self.settings.diagnostic_export_bytes,
                "build_logs": "explicit_opt_in_with_preview",
            },
            "network": {
                "inference": "local_only",
                "tailscale": tailscale_status(),
                "addresses_and_peer_names_included": False,
            },
            "limitations": [
                "No conversation contents, credentials, names, paths or raw logs included",
                "GPU readings require the installed NVIDIA driver; unsupported fields are null",
                "CPU temperature is unavailable when the OS exposes no supported sensor",
                "Runtime error categories describe reported errors, "
                "not a confirmed hardware diagnosis",
                "Local Tailscale state does not establish phone-to-PC reachability",
            ],
        }

    def save_mobile(self, device_id, snapshot, collection_id=None):
        data = snapshot.model_dump(mode="json")
        data.pop("consent")
        snapshot_id, now = uid(), utcnow()
        with self.store.transaction() as db:
            if collection_id:
                collection = db.execute(
                    "SELECT * FROM collections WHERE id=? AND device_id=?",
                    (collection_id, device_id),
                ).fetchone()
                if not collection:
                    raise HTTPException(404, "Collection request not found")
                if collection["status"] != "pending":
                    raise HTTPException(409, "Collection request already fulfilled")
            db.execute(
                "INSERT INTO snapshots VALUES(?,?,?,?,?)",
                (snapshot_id, device_id, data["captured_at"], now, canonical(data)),
            )
            if collection_id:
                db.execute(
                    "UPDATE collections SET status='completed',snapshot_id=? WHERE id=?",
                    (snapshot_id, collection_id),
                )
            db.execute(
                "DELETE FROM snapshots WHERE device_id=? AND id NOT IN "
                "(SELECT id FROM snapshots WHERE device_id=? ORDER BY received_at DESC LIMIT ?)",
                (device_id, device_id, self.settings.diagnostic_retention),
            )
        self.store.log("snapshot_received", snapshot_id)
        return {"id": snapshot_id, "received_at": now}

    def capture_manual(self):
        payload = self.desktop_snapshot()
        with self.store.transaction() as db:
            return capture(self.store, db, "manual", payload=payload)

    def preview(self, device_id, mobile_device=None, include_work_logs=False):
        now = utcnow()
        desktop = self.desktop_snapshot()
        events = self.store.all(
            "SELECT code,correlation_id,created_at FROM diagnostic_events ORDER BY id DESC LIMIT ?",
            (self.settings.diagnostic_event_retention,),
        )
        files = {
            "desktop/system-info.json": json.dumps(desktop, indent=2),
            "desktop/application-events.jsonl": "\n".join(canonical(e) for e in reversed(events)),
            "desktop/inference-metrics.json": json.dumps(desktop["inference"], indent=2),
            "desktop/agent-events.json": json.dumps(desktop["work"], indent=2),
            "desktop/errors.json": json.dumps(desktop["recent_errors"], indent=2),
        }
        files.update(export_snapshots(self.store))
        if include_work_logs:
            files.update(build_logs(self.store))
        mobile = None
        if mobile_device:
            mobile = self.store.one(
                "SELECT * FROM snapshots WHERE device_id=? ORDER BY received_at DESC LIMIT 1",
                (mobile_device,),
            )
            if mobile:
                files["android/app-diagnostics.json"] = json.dumps(
                    json.loads(mobile["payload"]), indent=2
                )
        availability = "cached_snapshot" if mobile else "unavailable"
        files["summary.md"] = (
            f"# dsGPT diagnostic report\n\nCollected: {now}\n\n"
            f"Backend: {desktop['platform']}; version {__version__}.\n\n"
            f"GPU measurements: {desktop['gpu_measurement']}. "
            f"Recent diagnostic errors: {len(desktop['recent_errors'])}.\n\n"
            f"Android diagnostics: {availability}. Cached reports are not live device access.\n\n"
            "If a reply fails, check that the configured local runtime is running and the model "
            "is installed. For context errors, shorten the conversation or select a tested "
            "larger context configuration.\n\n"
            "Default reports exclude private contents and raw logs. "
            "Measurements shown as unavailable were not collected.\n"
        )
        if include_work_logs:
            files["summary.md"] += (
                "\nBuild/test output was explicitly included. Known credential patterns are "
                "redacted, but project text, paths or unrecognized secrets may remain. "
                "Review every included log before sharing.\n"
            )
        if desktop["recent_errors"]:
            files["summary.md"] += (
                "\n## Recent errors and suggested checks\n\n"
                + "\n".join(
                    f"- {row['created_at']}: {row['code']}. {row['help']}"
                    for row in desktop["recent_errors"][:10]
                )
                + "\n"
            )
        manifest = {
            "schema_version": 1,
            "created_at": now,
            "privacy": "opt_in_build_logs" if include_work_logs else "sanitized_allowlist",
            "build_logs_included": include_work_logs,
            "snapshot_history_count": len(desktop["snapshot_history"]),
            "snapshots_exported": sum(name.startswith("desktop/snapshots/") for name in files),
            "desktop_platform": desktop["platform"],
            "android": availability,
            "android_captured_at": mobile["captured_at"] if mobile else None,
            "android_received_at": mobile["received_at"] if mobile else None,
            "files": {
                name: {
                    "sha256": hashlib.sha256(content.encode()).hexdigest(),
                    "bytes": len(content.encode()),
                }
                for name, content in files.items()
            },
        }
        files["manifest.json"] = json.dumps(manifest, indent=2)
        if (
            sum(len(value.encode()) for value in files.values())
            > self.settings.diagnostic_export_bytes
        ):
            raise HTTPException(413, "Diagnostic export exceeds its configured size limit")
        fingerprint = hashlib.sha256(canonical(files).encode()).hexdigest()
        export_id = uid()
        with self.store.transaction() as db:
            db.execute("DELETE FROM exports WHERE expires<?", (time.time(),))
            db.execute(
                "DELETE FROM exports WHERE device_id=? AND id NOT IN "
                "(SELECT id FROM exports WHERE device_id=? ORDER BY rowid DESC LIMIT 4)",
                (device_id, device_id),
            )
            db.execute(
                "INSERT INTO exports VALUES(?,?,?,?,?)",
                (export_id, device_id, time.time() + 600, fingerprint, canonical(files)),
            )
        return {
            "id": export_id,
            "sha256": fingerprint,
            "files": files,
            "expires_in_seconds": 600,
            "android": availability,
        }

    def download(self, export_id, device_id, fingerprint, allow_work_logs=False):
        row = self.store.one(
            "SELECT * FROM exports WHERE id=? AND device_id=? AND expires>?",
            (export_id, device_id, time.time()),
        )
        if not row:
            raise HTTPException(404, "Diagnostic preview expired or not found")
        if fingerprint != row["manifest_hash"]:
            raise HTTPException(409, "Download must match the diagnostic contents you previewed")
        files = json.loads(row["files"])
        if any(name.startswith("desktop/build-logs/") for name in files) and not allow_work_logs:
            raise HTTPException(403, "Work permission is required to download private build logs")
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in files.items():
                archive.writestr(name, content)
        return buffer.getvalue()
