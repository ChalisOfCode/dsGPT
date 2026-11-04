"""Offline binary/media tools. Run ONLY inside the isolated tool container.

All edits create new files. Originals and publisher signing keys are never changed.
"""

import argparse
import codecs
import hashlib
import json
import math
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import wave
import zipfile
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET

LIMIT = 512 * 1024**2
ENTRIES = 30000
ROOT = Path.cwd().resolve()


def path(value):
    p = Path(value)
    resolved = p.resolve()
    if p.is_absolute() or not resolved.is_relative_to(ROOT) or resolved == ROOT:
        raise ValueError("Use a relative path within the isolated workspace")
    return resolved


def sha(p):
    with p.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def read_utf8_page(source, offset=0):
    """Read a byte-bounded text page without splitting or replacing characters."""
    if offset < 0:
        raise ValueError("Use a nonnegative UTF-8 byte offset")
    with source.open("rb") as stream:
        size = os.fstat(stream.fileno()).st_size
        stream.seek(offset)
        data = stream.read(6000)
    decoder = codecs.getincrementaldecoder("utf-8")()
    text = decoder.decode(data, final=offset + len(data) >= size)
    end = offset + len(text.encode("utf-8"))
    has_more = end < size
    return {
        "offset": offset,
        "next_offset": end if has_more else None,
        "has_more": has_more,
        "bytes": size,
        "text": text,
    }


def command(argv, timeout=600, acceptable=(0,), env=None):
    result = subprocess.run(
        [str(x) for x in argv],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        env=env,
    )
    output = result.stdout.decode("utf-8", "replace")
    print(output[-12000:])
    if result.returncode not in acceptable:
        raise ValueError(f"Tool exited {result.returncode}; inspect the recorded log")
    return output


def entries(z):
    rows = z.infolist()
    if len(rows) > ENTRIES or sum(r.file_size for r in rows) > LIMIT:
        raise ValueError("Archive exceeds 30000 entries or 512 MiB expanded")
    seen = set()
    for r in rows:
        p = PurePosixPath(r.filename)
        mode = stat.S_IFMT(r.external_attr >> 16)
        if (
            p.is_absolute()
            or ".." in p.parts
            or "\\" in r.filename
            or ":" in r.filename
            or mode not in (0, stat.S_IFREG, stat.S_IFDIR)
            or r.flag_bits & 1
        ):
            raise ValueError("Unsafe/encrypted archive entry")
        folded = str(p).casefold()
        if folded in seen:
            raise ValueError("Ambiguous duplicate archive entry")
        seen.add(folded)
    return rows


def unpack(source, destination):
    destination.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(source) as z:
        for r in entries(z):
            target = destination / r.filename
            if not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError("Unsafe archive target")
            if r.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(r) as f, target.open("xb") as out:
                    shutil.copyfileobj(f, out, 1024 * 1024)


def pack(folder, output):
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(folder.rglob("*"))
    if len(rows) > ENTRIES or sum(p.stat().st_size for p in rows if p.is_file()) > LIMIT:
        raise ValueError("Decoded workspace exceeds limits")
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as z:
        for p in rows:
            if p.is_symlink():
                raise ValueError("Links are not exported")
            if p.is_file():
                z.write(p, p.relative_to(folder))


def edits(folder, specification):
    changes = json.loads(specification.read_text())
    if not isinstance(changes, list) or not 1 <= len(changes) <= 200:
        raise ValueError("Patch file must be a list of 1..200 exact edits")
    results = []
    for edit in changes:
        member = PurePosixPath(edit["path"])
        target = (folder / member).resolve()
        if (
            member.is_absolute()
            or not target.is_relative_to(folder.resolve())
            or not target.is_file()
        ):
            raise ValueError("Patch target missing or unsafe")
        before = sha(target)
        if before != edit["sha256"]:
            raise ValueError("Patch target hash changed")
        if "replacement_file" in edit:
            source = path(edit["replacement_file"])
            if source.stat().st_size > LIMIT:
                raise ValueError("Replacement too large")
            shutil.copyfile(source, target)
        else:
            content = target.read_text()
            old, new = edit["old"], edit["new"]
            if not old or content.count(old) != edit.get("count", 1):
                raise ValueError("Exact text edit count does not match")
            target.write_text(content.replace(old, new))
        results.append({"path": str(member), "before": before, "after": sha(target)})
    return results


def apktool(*args):
    return command(["java", "-Xmx2g", "-jar", "/opt/apktool/apktool.jar", *args])


def apk_decode(source, output, java=False):
    with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
        folder = Path(temporary) / "decoded"
        if java:
            env = os.environ.copy()
            for key, leaf in (
                ("JADX_CONFIG_DIR", "config"),
                ("JADX_CACHE_DIR", "cache"),
                ("JADX_TMP_DIR", "tmp"),
            ):
                env[key] = str(Path(temporary) / leaf)
            command(
                ["/opt/jadx/bin/jadx", "-j", "2", "-d", folder, source], acceptable=(0, 1), env=env
            )
            if not folder.is_dir():
                raise ValueError("Decompiler produced no source")
        else:
            apktool("d", "-f", "-p", str(Path(temporary) / "framework"), "-o", folder, source)
        pack(folder, output)
    return {
        "input_sha256": sha(source),
        "workspace_sha256": sha(output),
        "output": str(output.relative_to(ROOT)),
        "mode": "readable_java" if java else "smali_resources",
        "note": "Java decompilation may be incomplete; rebuild from decoded smali/resources.",
    }


def apk_rebuild(source, patch, output):
    with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
        folder = Path(temporary) / "decoded"
        unpack(source, folder)
        changes = edits(folder, patch)
        output.parent.mkdir(parents=True, exist_ok=True)
        apktool("b", "-p", str(Path(temporary) / "framework"), "-o", output, folder)
        with zipfile.ZipFile(output) as z:
            if "AndroidManifest.xml" not in z.namelist():
                raise ValueError("Rebuilt APK has no manifest")
    return {
        "changes": changes,
        "unsigned_sha256": sha(output),
        "signature": "Backend signs exported APK separately with this task's persistent key.",
        "publisher_update_compatible": False,
        "native_runtime_verified": False,
    }


def pe(source):
    import pefile

    return pefile.PE(str(source), fast_load=False)


def exe_inspect(source, output):
    p = pe(source)
    managed = bool(p.OPTIONAL_HEADER.DATA_DIRECTORY[14].VirtualAddress)
    report = {
        "sha256": sha(source),
        "machine": p.FILE_HEADER.Machine,
        "entry_point": hex(p.OPTIONAL_HEADER.AddressOfEntryPoint),
        "managed_dotnet": managed,
        "sections": [
            {
                "name": s.Name.decode(errors="replace").strip("\0"),
                "address": s.VirtualAddress,
                "offset": s.PointerToRawData,
                "size": s.SizeOfRawData,
            }
            for s in p.sections
        ],
        "imports": [
            {
                "dll": x.dll.decode(errors="replace"),
                "functions": [
                    i.name.decode(errors="replace") if i.name else str(i.ordinal) for i in x.imports
                ],
            }
            for x in getattr(p, "DIRECTORY_ENTRY_IMPORT", [])
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2))
    p.close()
    return report


def exe_decompile(source, output):
    p = pe(source)
    managed = bool(p.OPTIONAL_HEADER.DATA_DIRECTORY[14].VirtualAddress)
    p.close()
    with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
        root = Path(temporary)
        folder = root / "decoded"
        folder.mkdir()
        if managed:
            command(["monodis", "--output=" + str(folder / "program.il"), source], timeout=600)
        else:
            projects = root / "projects"
            projects.mkdir()
            env = os.environ.copy()
            env["JAVA_HOME"] = "/opt/jdk"
            env["JAVA_TOOL_OPTIONS"] = (
                env.get("JAVA_TOOL_OPTIONS", "") + " -Duser.home=" + str(root)
            )
            argv = [
                "/opt/ghidra/support/analyzeHeadless",
                str(projects),
                "inspection",
                "-import",
                str(source),
                "-analysisTimeoutPerFile",
                "480",
                "-max-cpu",
                "2",
                "-scriptPath",
                "/opt/dsgpt",
                "-postScript",
                "ExportFunctions.java",
                str(folder),
                "-deleteProject",
            ]
            result = subprocess.run(
                argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, timeout=720
            )
            print(result.stdout.decode(errors="replace")[-12000:])
            if result.returncode or not (folder / "functions.tsv").is_file():
                raise ValueError("Ghidra analysis failed; inspect its log")
        pack(folder, output)
    return {
        "sha256": sha(output),
        "managed_dotnet": managed,
        "note": "Decompiled pseudocode/IL is evidence, not recovered original source. "
        "Check per-function failures and analysis timeout.",
    }


def exe_patch(source, patch, output):
    spec = json.loads(patch.read_text())
    if spec["sha256"] != sha(source):
        raise ValueError("Original executable hash does not match")
    data = bytearray(source.read_bytes())
    changed = set()
    for change in spec["patches"]:
        offset = change["offset"]
        old, new = bytes.fromhex(change["old_hex"]), bytes.fromhex(change["new_hex"])
        if not old or len(old) != len(new) or offset < 0 or data[offset : offset + len(old)] != old:
            raise ValueError("Binary patch requires exact old bytes and equal-length replacement")
        positions = set(range(offset, offset + len(old)))
        if changed & positions:
            raise ValueError("Binary patches overlap")
        changed |= positions
        data[offset : offset + len(old)] = new
    if not changed:
        raise ValueError("No binary patches requested")
    import pefile

    parsed = pefile.PE(data=bytes(data))
    parsed.OPTIONAL_HEADER.DATA_DIRECTORY[4].VirtualAddress = 0
    parsed.OPTIONAL_HEADER.DATA_DIRECTORY[4].Size = 0
    parsed.OPTIONAL_HEADER.CheckSum = parsed.generate_checksum()
    output.parent.mkdir(parents=True, exist_ok=True)
    parsed.write(str(output))
    parsed.close()
    verified = pe(output)
    if not verified.verify_checksum():
        raise ValueError("PE checksum verification failed")
    verified.close()
    return {
        "original_sha256": spec["sha256"],
        "modified_sha256": sha(output),
        "changed_bytes": len(changed),
        "authenticode_signed": False,
        "native_runtime_verified": False,
    }


def video_info(source):
    raw = command(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", source],
        timeout=60,
    )
    return json.loads(raw)


def video_frames(source, output, start, end, count):
    from PIL import Image, ImageDraw

    info = video_info(source)
    duration = float(info["format"]["duration"])
    stop = min(duration, end if end is not None else duration)
    if not 0 <= start < stop or not 1 <= count <= 12:
        raise ValueError("Choose a valid time range and 1..12 frames")
    width, height = 480, 300
    sheet = Image.new("RGB", (width * min(count, 3), height * ((count + 2) // 3)), "#202020")
    draw = ImageDraw.Draw(sheet)
    frames = []
    with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
        for index in range(count):
            timestamp = start + (stop - start) * (index + 0.5) / count
            target = Path(temporary) / f"{index}.png"
            command(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-ss",
                    str(timestamp),
                    "-i",
                    source,
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale=480:270:force_original_aspect_ratio=decrease",
                    "-threads",
                    "2",
                    target,
                ],
                timeout=90,
            )
            with Image.open(target) as im:
                sheet.paste(im, ((index % 3) * width, (index // 3) * height))
            draw.text(
                ((index % 3) * width + 8, (index // 3) * height + 275),
                f"{timestamp:.3f} seconds",
                fill="white",
            )
            ocr = command(["tesseract", target, "stdout"], timeout=30)
            frames.append({"seconds": round(timestamp, 3), "ocr": ocr[:4000]})
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, format="JPEG", quality=85)
    return {
        "duration": duration,
        "start": start,
        "end": stop,
        "frames": frames,
        "note": "Sampled frames, not full-motion inspection. Narrow the range around changes "
        "and sample again; use inspect_image for visual analysis.",
    }


def video_edit(source, specification, output):
    spec = json.loads(specification.read_text())
    start, seconds = float(spec.get("start", 0)), float(spec["duration"])
    if not 0 <= start or not 0 < seconds <= 3600:
        raise ValueError("Choose start >=0 and duration <=3600 seconds")
    output.parent.mkdir(parents=True, exist_ok=True)
    argv = ["ffmpeg", "-v", "error", "-ss", str(start), "-i", source, "-t", str(seconds)]
    mode = spec.get("mode", "mp4")
    if mode == "audio":
        argv += ["-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "-f", "wav"]
    elif mode in {"mp4", "gif"}:
        width = int(spec.get("width", 1280 if mode == "mp4" else 480))
        fps = int(spec.get("fps", 30 if mode == "mp4" else 10))
        if not 64 <= width <= 1920 or not 1 <= fps <= 60:
            raise ValueError("Width must be 64..1920 and fps 1..60")
        argv += ["-vf", f"scale={width}:-2,fps={fps}"]
        argv += (
            [
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "23",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                "-f",
                "mp4",
            ]
            if mode == "mp4"
            else ["-an", "-f", "gif"]
        )
    else:
        raise ValueError("Mode must be mp4, gif or audio")
    command([*argv, "-threads", "2", "-y", output], timeout=780)
    return {"sha256": sha(output), "media": video_info(output)}


def audio_transcribe(source, output, start=0, seconds=300):
    """English speech, locally decoded/recognized with absolute media timestamps."""
    if not math.isfinite(start) or start < 0 or not 0 < seconds <= 900:
        raise ValueError("Choose finite start >=0 and duration 1..900 seconds; page longer audio")
    if output.suffix.lower() != ".json":
        raise ValueError("Use a .json output; a matching .srt subtitle file is also written")
    info = video_info(source)
    if not any(stream.get("codec_type") == "audio" for stream in info.get("streams", [])):
        raise ValueError("This file has no audio stream; inspect video frames instead")
    duration = float(info["format"]["duration"])
    if not math.isfinite(duration) or not 0 <= start < duration:
        raise ValueError("Choose a start before the end of the audio/video")
    end = min(duration, start + seconds)
    # Only trusted, provisioned libraries/models. No language= auto-download fallback.
    sys.path.insert(0, "/opt/voice-python")
    from vosk import KaldiRecognizer, Model, SetLogLevel

    SetLogLevel(-1)
    recognizer = KaldiRecognizer(Model("/opt/voice-model"), 16000)
    recognizer.SetWords(True)
    segments, words = [], []

    def accept(raw):
        segment = json.loads(raw)
        batch = [
            {
                "word": item["word"],
                "start": round(start + item["start"], 3),
                "end": round(start + item["end"], 3),
                "confidence": round(item.get("conf", 0), 3),
            }
            for item in segment.get("result", [])
        ]
        if batch:
            words.extend(batch)
            segments.append(
                {
                    "start": batch[0]["start"],
                    "end": batch[-1]["end"],
                    "text": segment["text"],
                    "words": batch,
                }
            )

    with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
        audio = Path(temporary) / "audio.wav"
        command(
            [
                "ffmpeg",
                "-v",
                "error",
                "-ss",
                str(start),
                "-i",
                source,
                "-t",
                str(end - start),
                "-map",
                "0:a:0",
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                "-threads",
                "2",
                "-y",
                audio,
            ],
            timeout=180,
        )
        with wave.open(str(audio), "rb") as stream:
            if stream.getnframes() > 16000 * 901:
                raise ValueError("Decoded audio exceeded the bounded time window")
            while data := stream.readframes(4000):
                if recognizer.AcceptWaveform(data):
                    accept(recognizer.Result())
            accept(recognizer.FinalResult())
    report = {
        "source_sha256": sha(source),
        "engine": "vosk-0.3.45",
        "model": "vosk-model-en-us-0.22-lgraph",
        "language": "en-US",
        "start": start,
        "end": end,
        "duration": duration,
        "next_start": round(end, 6) if end < duration - 0.000001 else None,
        "text": " ".join(row["text"] for row in segments),
        "segments": segments,
        "word_count": len(words),
        "uncertain_words": sum(word["confidence"] < 0.6 for word in words),
        "note": "Automatic English transcription can mishear names, code and noisy speech. "
        "Timestamps refer to the original media. This is not speaker identification.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    def clock(value):
        value = round(value * 1000)
        return (
            f"{value // 3600000:02}:{value // 60000 % 60:02}:"
            f"{value // 1000 % 60:02},{value % 1000:03}"
        )

    captions = []
    for segment in segments:
        for index in range(0, len(segment["words"]), 12):
            batch = segment["words"][index : index + 12]
            captions.append(
                f"{len(captions) + 1}\n{clock(batch[0]['start'])} --> {clock(batch[-1]['end'])}\n"
                + " ".join(word["word"] for word in batch)
                + "\n"
            )
    output.with_suffix(".srt").write_text("\n".join(captions), encoding="utf-8")
    return {key: value for key, value in report.items() if key not in {"text", "segments"}} | {
        "preview": report["text"][:600],
        "status": "transcribed" if words else "no_speech_detected",
        "transcript": str(output.relative_to(ROOT)),
        "subtitles": str(output.with_suffix(".srt").relative_to(ROOT)),
        "read": "Collect the .json and .srt paths, then use read receipts/<path> --offset N. "
        "If next_start is present, transcribe the next window before claiming full coverage.",
    }


def document(source, output, start, count):
    if start < 1 or not 1 <= count <= 50:
        raise ValueError("Choose a first page >=1 and 1..50 pages per batch")
    extension = source.suffix.lower()
    pages, total = [], 1
    with tempfile.TemporaryDirectory(dir=ROOT) as temp:
        temporary = Path(temp)
        if extension == ".pdf":
            info = command(["pdfinfo", source], timeout=60)
            match = re.search(r"^Pages:\s*(\d+)", info, re.M)
            if not match:
                raise ValueError("Unable to read PDF page count")
            total = int(match[1])
            for number in range(start, min(total + 1, start + count)):
                target = temporary / "page.txt"
                command(
                    [
                        "pdftotext",
                        "-f",
                        str(number),
                        "-l",
                        str(number),
                        "-enc",
                        "UTF-8",
                        source,
                        target,
                    ]
                )
                text = target.read_text()
                if not text.strip():
                    prefix = temporary / "scan"
                    command(
                        [
                            "pdftoppm",
                            "-f",
                            str(number),
                            "-l",
                            str(number),
                            "-singlefile",
                            "-scale-to",
                            "1800",
                            "-png",
                            source,
                            prefix,
                        ]
                    )
                    text = command(["tesseract", str(prefix) + ".png", "stdout"], timeout=60)
                pages.append(f"[Page {number}]\n{text}")
        elif extension in {".png", ".jpg", ".jpeg", ".webp"}:
            pages.append(command(["tesseract", source, "stdout"], timeout=90))
        elif extension in {".docx", ".xlsx", ".pptx"}:
            with zipfile.ZipFile(source) as z:
                rows = entries(z)

                def xml(member):
                    raw = z.read(member)
                    if (
                        len(raw) > 16 * 1024**2
                        or b"<!DOCTYPE" in raw.upper()
                        or b"<!ENTITY" in raw.upper()
                    ):
                        raise ValueError("Unsafe or oversized Office XML")
                    return ET.fromstring(raw)

                if extension == ".docx":
                    names = [
                        r.filename
                        for r in rows
                        if re.fullmatch(r"word/(document|header\d+|footer\d+)\.xml", r.filename)
                    ]
                elif extension == ".pptx":
                    names = [
                        r.filename
                        for r in rows
                        if re.fullmatch(r"ppt/slides/slide\d+\.xml", r.filename)
                    ]
                else:
                    names = [
                        r.filename
                        for r in rows
                        if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", r.filename)
                    ]
                names.sort(
                    key=lambda name: (
                        int(re.search(r"(\d+)\.xml$", name)[1])
                        if re.search(r"(\d+)\.xml$", name)
                        else 0,
                        name,
                    )
                )
                total = len(names)
                shared = []
                if extension == ".xlsx" and "xl/sharedStrings.xml" in z.namelist():
                    shared = ["".join(e.itertext()) for e in xml("xl/sharedStrings.xml")]
                for name in names[start - 1 : start - 1 + count]:
                    tree = xml(name)
                    if extension == ".xlsx":
                        values = []
                        for cell in tree.iter():
                            if not cell.tag.endswith("}c"):
                                continue
                            value = "".join(
                                e.text or "" for e in cell.iter() if e.tag.endswith(("}v", "}t"))
                            )
                            if cell.get("t") == "s":
                                value = shared[int(value)]
                            values.append(cell.get("r", "") + ": " + value)
                    else:
                        values = [e.text or "" for e in tree.iter() if e.tag.endswith("}t")]
                    pages.append("[" + name + "]\n" + "\n".join(values))
        else:
            raise ValueError(
                "Use document for PDF, images, DOCX, XLSX or PPTX; read for ordinary text"
            )
    text = "\n\n".join(pages)
    if len(text.encode()) > 64 * 1024**2:
        raise ValueError("Extract fewer pages in this batch")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text)
    return {
        "pages_or_parts": total,
        "start": start,
        "count": len(pages),
        "next_start": start + count if start + count <= total else None,
        "output_bytes": output.stat().st_size,
        "sha256": sha(output),
        "notice": "Text/OCR extraction; formatting, diagrams, formulas and recognition "
        "may need visual verification.",
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest="action", required=True)
    for name in ("apk-decode", "apk-java", "exe-inspect", "exe-decompile", "extract", "video-info"):
        sub = commands.add_parser(name)
        sub.add_argument("input")
        sub.add_argument("output")
    for name in ("apk-rebuild", "exe-patch", "video-edit", "archive-edit", "exe-il-rebuild"):
        sub = commands.add_parser(name)
        sub.add_argument("input")
        sub.add_argument("patch")
        sub.add_argument("output")
    for name in ("archive-list", "archive-read", "read"):
        sub = commands.add_parser(name)
        sub.add_argument("input")
        if name == "archive-read":
            sub.add_argument("member")
        sub.add_argument("--offset", type=int, default=0)
        sub.add_argument("--query", default="")
    sub = commands.add_parser("video-frames")
    sub.add_argument("input")
    sub.add_argument("output")
    sub.add_argument("--start", type=float, default=0)
    sub.add_argument("--end", type=float)
    sub.add_argument("--count", type=int, default=6)
    sub = commands.add_parser("audio-transcribe")
    sub.add_argument("input")
    sub.add_argument("output")
    sub.add_argument("--start", type=float, default=0)
    sub.add_argument("--duration", type=float, default=300)
    sub = commands.add_parser("audio-merge")
    sub.add_argument("input")
    sub.add_argument("output")
    sub = commands.add_parser("document")
    sub.add_argument("input")
    sub.add_argument("output")
    sub.add_argument("--start", type=int, default=1)
    sub.add_argument("--count", type=int, default=20)
    args = p.parse_args()
    source = path(args.input)
    if source.stat().st_size > LIMIT:
        raise ValueError("Input exceeds 512 MiB")
    output = path(args.output) if hasattr(args, "output") else None
    patch = path(args.patch) if hasattr(args, "patch") else None
    action = args.action
    if action == "audio-transcribe":
        result = audio_transcribe(source, output, args.start, args.duration)
    elif action == "audio-merge":
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "dsgpt_transcript_merge", Path(__file__).with_name("transcript_merge.py")
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = module.merge(source, output, ROOT)
    elif action == "document":
        result = document(source, output, args.start, args.count)
    elif action in {"apk-decode", "apk-java"}:
        result = apk_decode(source, output, action == "apk-java")
    elif action == "apk-rebuild":
        result = apk_rebuild(source, patch, output)
    elif action == "exe-inspect":
        result = exe_inspect(source, output)
    elif action == "exe-decompile":
        result = exe_decompile(source, output)
    elif action == "exe-patch":
        result = exe_patch(source, patch, output)
    elif action == "video-info":
        result = video_info(source)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2))
    elif action == "video-frames":
        result = video_frames(source, output, args.start, args.end, args.count)
    elif action == "video-edit":
        result = video_edit(source, patch, output)
    elif action == "extract":
        unpack(source, output)
        result = {"extracted_to": str(output.relative_to(ROOT))}
    elif action in {"archive-edit", "exe-il-rebuild"}:
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            folder = Path(temporary) / "decoded"
            unpack(source, folder)
            result = {"changes": edits(folder, patch)}
            if action == "archive-edit":
                pack(folder, output)
            else:
                output.parent.mkdir(parents=True, exist_ok=True)
                command(["ilasm", str(folder / "program.il"), "/exe", "/output=" + str(output)])
                result.update(exe_inspect(output, output.with_suffix(".inspection.json")))
    elif action in {"archive-list", "archive-read"}:
        with zipfile.ZipFile(source) as z:
            rows = entries(z)
            if action == "archive-list":
                matches = [
                    r
                    for r in rows
                    if not r.is_dir() and args.query.casefold() in r.filename.casefold()
                ]
                result = {
                    "total": len(matches),
                    "offset": args.offset,
                    "next_offset": args.offset + 30 if args.offset + 30 < len(matches) else None,
                    "files": [
                        {"path": r.filename, "bytes": r.file_size}
                        for r in matches[args.offset : args.offset + 30]
                    ],
                }
            else:
                r = z.getinfo(args.member)
                if r.file_size > 16 * 1024**2:
                    raise ValueError("Select a source member up to 16 MiB")
                raw = z.read(r)
                text = raw.decode("utf-8")
                offset = text.find(args.query, args.offset) if args.query else args.offset
                result = {
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "characters": len(text),
                    "offset": offset,
                    "text": text[offset : offset + 6000] if offset >= 0 else "",
                    "next_offset": offset + 6000
                    if offset >= 0 and offset + 6000 < len(text)
                    else None,
                }
    else:
        result = read_utf8_page(source, args.offset)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
