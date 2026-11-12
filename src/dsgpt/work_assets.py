"""Immutable task inputs and reusable, completed tool outputs."""

import hashlib

from .storage import canonical

ASSET_INSTRUCTIONS = """
Assets list exact saved inputs/ and receipts/ paths. To transcribe audio/video, return this JSON
action directly, replacing the example path with the exact saved asset path:
{"tool":"transcribe_media","path":"inputs/movie.mp4","summary":"Transcribe saved audio"}
The backend supplies the command and automatically collects BOTH JSON and SRT. Optional fields:
start_seconds (default 0) and duration_seconds (default 300, maximum 900). Follow next_start for
later windows. transcribe_media is a JSON tool name, never an argv item or worker subcommand.
To read the saved transcript, copy transcript_path from the result into this JSON action:
{"tool":"read_asset","path":"receipts/EXACT_PATH_FROM_RESULT.json","summary":"Read transcript"}
read_asset is also a JSON action. Follow next_offset using its optional offset field until null.
list_assets(offset,query) pages every saved output; follow next_offset beyond the first16 paths.
For a whole recording, follow coverage.next_start until all windows are available, then return
{"tool":"assemble_transcript","path":"inputs/movie.mp4","summary":"Assemble whole recording"}
Assembly checks contiguous same-source windows and saves one JSON/SRT pair. Selected-window tasks
may retain just their requested windows; never claim full recording coverage from a partial window.
Read work-assets-guide.txt for other asset commands.
Inspect imported apps before editing; never scaffold replacements. For video, combine timestamped
frames/inspect_image with transcribe_media, then narrow/repeat as needed. Read actual results and
verify outputs. Unsampled frames and untranscribed audio remain unreviewed.
"""

GUIDE = """Work asset tools (all run offline inside the container)
Use run argv: /usr/bin/python3 -I /opt/dsgpt/asset_worker.py COMMAND ARGUMENTS.
Collect desired outputs with run.artifacts (up to two paths). Completed outputs are available in
later runs at receipts/<original artifact path>. Original files are at inputs/<filename>.
Artifact paths must match NEW output paths exactly: if a command writes media.json, set
artifacts=["media.json"], NOT ["receipts/media.json"]. Only subsequent runs
read receipts/media.json.
Files created by write_file are available at their project path. Each run starts fresh.
Never execute imported programs on the host. Resource limits/timeouts may reject very large apps.

APK:
 apk-decode inputs/app.apk decoded.zip   -> smali/resources rebuildable workspace
 apk-java inputs/app.apk java.zip       -> readable Java for understanding; may be incomplete
 archive-list receipts/decoded.zip --query Main --offset 0
 archive-read receipts/decoded.zip smali/com/example/Main.smali --offset 0 --query TEXT
 apk-rebuild receipts/decoded.zip patches.json modified.apk
Backend signs exported APKs with this task's persistent development key, isolated from code.
It is NOT the publisher key. It cannot update the publisher-signed app in place. Do not silently
uninstall the original or claim runtime success. Test on a device separately.

Exact decoded-workspace patches.json is a list:
[{"path":"res/values/strings.xml","sha256":"HASH_FROM_ARCHIVE_READ",
  "old":"old exact text","new":"new exact text","count":1}]
For binary resources use {"path":"...","sha256":"old file SHA256",
"replacement_file":"inputs/replacement.png"}. To obtain binary member SHA256 use run Python
hashlib on zipfile.read; do not decode a binary member as UTF-8. archive-edit INPUT PATCH OUTPUT
preserves a modified decoded ZIP without rebuilding. Use its collected receipt on the next run.

EXE:
 exe-inspect inputs/app.exe pe-report.json -> architecture, imports, managed/native detection
 exe-decompile inputs/app.exe decompiled.zip -> Ghidra per-function C-like pseudocode for native
PE; monodis IL for .NET. archive-list/read page the results. functions.tsv records failures and
export limits; original source, names, comments, project files are not guaranteed recoverable.
 exe-patch inputs/app.exe patch.json modified.exe
patch.json: {"sha256":"ORIGINAL_HASH","patches":[{"offset":1234,
"old_hex":"414243","new_hex":"58595a"}]}. Verify exact offsets/bytes first via inspection/run.
Equal-length edits only; nonoverlapping patches; PE checksum is repaired and stale Authenticode
removed. Code/resource redesign may require source reconstruction and the existing compiler.
 exe-il-rebuild receipts/decompiled.zip patches.json modified.exe rebuilds compatible managed IL.
External assemblies/resources, strong names and mixed-mode binaries may require additional inputs.
No EXE is executed on Windows by these tools; make that remaining test explicit.

Documents:
 render_document(path="inputs/report.docx") renders every page (up to 20) with LibreOffice/Poppler.
Supports PDF, DOCX and PPTX; outputs a render ZIP and hash-bound JSON report. Originals stay intact.
 extract_render_page(path="receipts/EXACT_RENDER_ZIP",page_number=1) exposes one checked PNG.
Use inspect_image on EACH extracted page for clipping, overlap, legibility and missing content.
Without vision, report visual review not performed. Rendering, OCR and blank-page
checks alone never prove good layout. Read the report for engine and font/compatibility limitations.
 recalculate_workbook(path="inputs/book.xlsx") runs Calc calculateAll and exports a NEW XLSX plus
an independently checked formula/cache report. Errors and changed content remain explicit. Read
report_path with read_asset; check relevant formula results, changed cells and number/date formats.
Active content, linked data, shared/array formulas and unsupported formats fail closed. Formats
and Excel-specific features are not guaranteed preserved. Inputs are limited to 32 MiB, expanded
Office packages to 128 MiB/4096 entries and workbooks to 20000 populated cells/32 sheets.
These names are typed JSON actions, not argv subcommands. Output paths are returned by the tool.

Legacy text extraction (does not render or calculate):
 document inputs/book.pdf pages.txt --start 1 --count 20 extracts selected pages with OCR fallback.
Follow next_start for remaining pages. DOCX, XLSX, PPTX and image OCR also work; paging there is by
Office XML part. Collect pages.txt, then read receipts/pages.txt --offset N. No document text is
silently truncated into the prompt. Verify visual layout separately with inspect_image or rendered
pages; spreadsheet formulas are not recalculated by text extraction.

Archives/large sources:
 archive-list INPUT [--query text] [--offset N] lists 30 matches; follow next_offset.
 archive-read INPUT MEMBER [--query text] [--offset N] returns 6000 characters and SHA256.
 read INPUT --offset N returns a 6000-byte page of an ordinary text/log/report file.
 extract INPUT folder safely expands ZIPs (512 MiB/30000 entries). To compile a source ZIP, write
a project Python build script that calls the worker to extract then runs the compiler in the SAME
run; collect its output. No download of dependencies occurs inside a task container.

Public files (when Work Web is enabled):
 download_file(url="https://example.org/demo.mp4",path="demo.mp4") is a model tool, not a shell
command. It saves inputs/demo.mp4 with source URL, time and hash. It supports direct public HTTPS
files up to 256 MiB each, four inputs/512 MiB total. HTML video pages, accounts and DRM streams
are not supported. Reusing the same URL/name returns the saved input; names cannot be overwritten.

Video and speech:
 video-info inputs/movie.mp4 media.json -> streams, duration, dimensions and audio codecs
 video-frames inputs/movie.mp4 storyboard.jpg --start 0 --end 30 --count 6
Collect storyboard.jpg, then inspect_image(path="receipts/storyboard.jpg") for visual analysis.
The log records exact timestamps and frame OCR. Adaptively narrow start/end around changes and
repeat sampling; this is not a claim of seeing every frame or hearing the audio.
 video-edit inputs/movie.mp4 edit.json clip.mp4
edit.json: {"start":12,"duration":20,"mode":"mp4","width":1280,"fps":30}
Other modes: gif (use .gif), audio (16 kHz mono .wav for transcription). start/duration in seconds.
 transcribe_media(path="inputs/movie.mp4",start_seconds=0,duration_seconds=300)
This is a model tool, NOT a shell command. Choose an exact saved inputs/ or receipts/ path.
The backend supplies the offline command, 900-second timeout and stable output filenames, and
always collects BOTH transcript JSON (text, segments, word timestamps/confidence) and SRT subtitles.
No output filename, argv, artifacts or timeout arguments are needed. The result.transcription
contains transcript_path and subtitles_path. read_asset(path=transcript_path,offset=0) reads the
saved text directly; follow next_offset (byte offsets). URLs must be downloaded first.
Preview text is only a preview. Follow transcription.next_start using transcribe_media again
for the next window. start_seconds is 0..604800; duration_seconds is 1..900 (default 300).
Do not claim full coverage after one window or completion until both output receipts are present.
For a whole recording, transcribe every window then assemble_transcript(path="inputs/movie.mp4").
This typed model tool selects a deterministic complete chain, checks exact saved hashes, source,
durations, gaps/overlaps and JSON/SRT consistency in the offline worker, and collects one merged
JSON/SRT pair. SRT numbering is global and timestamps stay absolute. Output provenance lists the
selected windows and excluded alternatives. It does not certify speech-recognition accuracy.
list_assets(offset=0,query="media/") pages saved metadata16 receipts at a time. Follow next_offset;
catalog_sha256 identifies inventory changes, so restart paging if it changes. read_asset can read
any current exact saved path, including receipts beyond the first page. Sandbox snapshots remain
limited to768MiB; exact required inputs that do not fit fail explicitly instead of disappearing.
The English speech model is installed automatically. Processing is offline, on CPU, and does not
compete for GPU VRAM. It can mishear names/code/noisy speech; report uncertainty and align spoken
requirements with timestamped frames. It does not identify speakers or translate languages.
FFmpeg is also installed for advanced editing, subtitle extraction, concat and scene detection;
use run argv or a saved script, bounded timeouts, and collect your outputs. Source/receipt files
stay local. Inspect the final metadata and record what was actually checked.
"""


CATALOG_PAGE = 16
SNAPSHOT_BYTES = 768 * 1024**2


def inventory(db, task):
    """Complete metadata, never file bodies; latest missing/failed paths stay unavailable."""
    from .builds import current_file_receipts

    inputs = [
        {**dict(row), "path": "inputs/" + row["name"]}
        for row in db.execute(
            "SELECT name,sha256,length(original) AS bytes FROM work_inputs "
            "WHERE task_id=? ORDER BY name",
            (task,),
        )
    ]
    receipts = [
        {**row, "path": "receipts/" + row["path"]} for row in current_file_receipts(db, task)
    ]
    return {"inputs": inputs, "receipts": receipts}


def catalog(db, task, offset=0, query=None):
    if type(offset) is not int or offset < 0 or offset > 1_000_000:
        raise ValueError("asset_offset_out_of_range")
    if query is not None and (not isinstance(query, str) or len(query) > 500):
        raise ValueError("invalid_asset_query")
    meta = inventory(db, task)
    receipts = meta["receipts"]
    if query:
        receipts = [row for row in receipts if query.casefold() in row["path"].casefold()]
    selected = receipts[offset : offset + CATALOG_PAGE]
    following = offset + len(selected)
    return {
        "inputs": meta["inputs"],
        "receipts": selected,
        "offset": offset,
        "next_offset": following if following < len(receipts) else None,
        "total_receipts": len(receipts),
        "query": query,
        "catalog_sha256": hashlib.sha256(canonical(meta).encode()).hexdigest(),
        "omitted_receipt_paths": len(receipts) - len(selected),
    }


def lookup(db, task, path):
    if not isinstance(path, str):
        return None
    meta = inventory(db, task)
    return next((row for row in meta["inputs"] + meta["receipts"] if row["path"] == path), None)


def snapshot(db, task, paths=None, required_paths=()):
    """Selected immutable blobs, retaining the original limit and bounded default snapshot."""
    from .sandbox import SandboxError

    meta = inventory(db, task)
    available = {row["path"]: row for row in meta["inputs"] + meta["receipts"]}
    required = list(
        dict.fromkeys(
            paths
            if paths is not None
            else [
                *[row["path"] for row in meta["inputs"]],
                *required_paths,
            ]
        )
    )
    if any(path not in available for path in required):
        raise SandboxError("required_asset_missing")
    selected = [available[path] for path in required]
    size = sum(row["bytes"] for row in selected)
    if size > SNAPSHOT_BYTES:
        raise SandboxError("required_assets_exceed_snapshot_limit")
    if paths is None:
        for row in meta["receipts"][:CATALOG_PAGE]:
            if row["path"] not in required and size + row["bytes"] <= SNAPSHOT_BYTES:
                selected.append(row)
                size += row["bytes"]
    rows = []
    for row in selected:
        if "id" in row:
            data = db.execute(
                "SELECT content FROM work_artifacts WHERE task_id=? AND id=?", (task, row["id"])
            ).fetchone()[0]
        else:
            data = db.execute(
                "SELECT original FROM work_inputs WHERE task_id=? AND name=?", (task, row["name"])
            ).fetchone()[0]
        if len(data) != row["bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise SandboxError("asset_content_integrity_failed")
        rows.append({"path": row["path"], "sha256": row["sha256"], "content": data})
    return rows, hashlib.sha256(canonical(selected).encode()).hexdigest()
