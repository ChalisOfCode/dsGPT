"""Automatic, resumable preparation of the 0.6 local model/voice experience."""

import hashlib
import json
import shutil
import time
import zipfile

import psutil

from dsgpt.hardware import gpu_snapshot

VERSION = "0.6.0"
VOICE_URL = "https://alphacephei.com/vosk/models/vosk-model-en-us-0.22-lgraph.zip"
VOICE_SHA = "d9838b4aaa82a75c4a17f5aca300eaca129aaab2a7cbf951bafbb500eb9c4334"
VOICE_BYTES = 130557655
FAST_MODEL = "qwen3.5:9b-q4_K_M"
QUALITY_MODEL = "qwen3.5:27b-q4_K_M"


def recommendations(ram_bytes, gpu_mib):
    # Leaves OS/Docker headroom; bigger weights spill into RAM on a 12 GiB GPU.
    if ram_bytes >= 30 * 1024**3 and gpu_mib >= 11000:
        return [FAST_MODEL, QUALITY_MODEL]
    if ram_bytes >= 15 * 1024**3 and gpu_mib >= 7500:
        return [FAST_MODEL]
    return ["qwen3.5:4b-q4_K_M"]


def progress(directory, phase, message, status="running", percent=None):
    path = directory / "experience-setup.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {
                "version": VERSION,
                "phase": phase,
                "message": message,
                "status": status,
                "percent": percent,
                "updated_at": time.time(),
            }
        ),
        encoding="utf-8",
    )
    temporary.replace(path)


def voice(setup):
    root = setup.directory / "voice"
    root.mkdir(parents=True, exist_ok=True)
    destination = root / "model"
    marker = root / "verified.json"
    if marker.is_file():
        try:
            manifest = json.loads(marker.read_text())
            if manifest["archive_sha256"] == VOICE_SHA and all(
                (destination / name).is_file()
                and hashlib.sha256((destination / name).read_bytes()).hexdigest() == digest
                for name, digest in manifest["files"].items()
            ):
                return
        except (ValueError, OSError, KeyError):
            pass
    progress(setup.directory, "voice", "Preparing local live dictation (131 MB)…")
    archive = root / "voice.zip.part"
    total = 0
    digest = hashlib.sha256()
    with setup.http.stream("GET", VOICE_URL, timeout=60, follow_redirects=False) as response:
        response.raise_for_status()
        with archive.open("wb") as output:
            for block in response.iter_bytes(1024 * 1024):
                total += len(block)
                if total > VOICE_BYTES:
                    raise ValueError("Voice download exceeded its verified size")
                digest.update(block)
                output.write(block)
                progress(
                    setup.directory,
                    "voice",
                    "Downloading local live dictation…",
                    percent=round(total * 100 / VOICE_BYTES),
                )
    if total != VOICE_BYTES or digest.hexdigest() != VOICE_SHA:
        raise ValueError("Voice download verification failed; restart dsGPT to retry")
    stage = root / "staging"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir()
    with zipfile.ZipFile(archive) as package:
        if sum(item.file_size for item in package.infolist()) > 500 * 1024**2:
            raise ValueError("Voice archive exceeded extraction limit")
        for item in package.infolist():
            path = stage / item.filename
            if not path.resolve().is_relative_to(stage.resolve()):
                raise ValueError("Invalid voice archive path")
        package.extractall(stage)
    model = stage / "vosk-model-en-us-0.22-lgraph"
    if not (model / "am/final.mdl").is_file():
        raise ValueError("Voice archive missing acoustic model")
    if destination.exists():
        shutil.rmtree(destination)
    model.replace(destination)
    files = {
        p.relative_to(destination).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in destination.rglob("*")
        if p.is_file()
    }
    marker.write_text(json.dumps({"archive_sha256": VOICE_SHA, "files": files}), encoding="utf-8")
    archive.unlink()
    shutil.rmtree(stage)


def prepare(setup, register):
    try:
        voice(setup)
        snapshot = gpu_snapshot()
        gpu = max((g.get("vram_total_mib") or 0 for g in snapshot["devices"]), default=0)
        names = recommendations(psutil.virtual_memory().total, gpu)
        for name in names:
            entries = (setup.model_tags() or {}).get("models", [])
            if not any(entry.get("name") == name for entry in entries):
                progress(
                    setup.directory,
                    "models",
                    "Downloading " + name + " automatically. Chat remains available.",
                )
                completed = False
                with setup.http.stream(
                    "POST",
                    "http://127.0.0.1:11434/api/pull",
                    json={"model": name, "stream": True},
                    timeout=300,
                ) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if not line:
                            continue
                        event = json.loads(line)
                        if event.get("error"):
                            raise RuntimeError("Model download failed; restart dsGPT to resume")
                        completed = event.get("status") == "success"
                        total, done = event.get("total", 0), event.get("completed", 0)
                        progress(
                            setup.directory,
                            "models",
                            "Preparing " + name + ". " + str(event.get("status", ""))[:100],
                            percent=round(100 * done / total) if total else None,
                        )
                if not completed:
                    raise RuntimeError("Model download incomplete; restart dsGPT to resume")
            entries = [
                m for m in (setup.model_tags() or {}).get("models", []) if m.get("name") == name
            ]
            verified = setup.verified_models(entries)
            if not verified:
                raise RuntimeError("Downloaded model failed local verification")
            for model in verified:
                model["name"] = "Qwen 3.5 " + (
                    "27B · higher quality, slower"
                    if name == QUALITY_MODEL
                    else "9B · everyday"
                    if name == FAST_MODEL
                    else "4B · compact"
                )
                model["context"] = 16384 if name == QUALITY_MODEL else 32768
                model["output_tokens"] = 4096 if name == QUALITY_MODEL else 8192
            register(verified, setup.request)
        progress(
            setup.directory, "ready", "Local voice and standard models are ready.", "succeeded"
        )
    except Exception:
        progress(
            setup.directory,
            "retry",
            "Automatic model or voice setup did not finish. Restart dsGPT to resume; "
            "installed models and chats are preserved.",
            "needs_attention",
        )
        raise
