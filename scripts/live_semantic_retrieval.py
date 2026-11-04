"""Actual pinned CPU embedding acceptance; synthetic data and no generation model.

Inputs are already downloaded publisher files; this script never fetches a model.
It denies Python network calls during inference and records all quality failures.
"""

import argparse
import asyncio
import hashlib
import json
import platform
import shutil
import socket
import time
from pathlib import Path

import psutil

from dsgpt.catalog import CATALOG
from dsgpt.downloads import DownloadManager
from dsgpt.embeddings import ASSET_IDS
from dsgpt.history import History
from dsgpt.history_archive import read_archive
from dsgpt.memory import Memory
from dsgpt.semantic import SemanticIndex
from dsgpt.storage import Store, uid
from dsgpt.work import WorkRegistry

CASES = [
    (
        "Diet",
        "I eat only plant-based meals. Dairy, eggs, poultry and fish are off my menu.",
        "Which dietary restrictions should a restaurant follow for me?",
    ),
    (
        "Availability",
        "Schedule meetings after three in the afternoon, using Denver time.",
        "At what hour should someone arrange a call with me?",
    ),
    (
        "Persistence",
        "For this application, persist records in SQLite and run everything "
        "without remote services.",
        "What storage engine and deployment boundary did we select?",
    ),
    (
        "Accessibility",
        "When sharing documents, use large lettering and strong contrast.",
        "What readability accommodations do I need?",
    ),
    (
        "Connectivity",
        "The phone app should keep working when the connection drops and upload changes later.",
        "How must the handset behave during a network outage?",
    ),
    (
        "Appearance",
        "Use dark blue panels with light text for the interface.",
        "What visual theme did we decide on?",
    ),
]
DISTRACTORS = [
    ("Garden", "The tomato plants need watering every Tuesday."),
    ("Transport", "The bicycle has a flat tire and needs a new tube."),
    ("Music", "The concert starts at eight on Saturday evening."),
    ("Reading", "The novel follows a detective investigating a missing painting."),
]


def denied(*args, **kwargs):
    raise AssertionError("Network attempted during local embedding inference")


async def main(args):
    args.data.mkdir(parents=True, exist_ok=False)
    store = Store(args.data)
    downloads = DownloadManager(store)
    provenance = []
    for identifier, filename in zip(ASSET_IDS, ("model.onnx", "tokenizer.json"), strict=True):
        asset = CATALOG[identifier]
        path = args.assets / filename
        digest = hashlib.file_digest(path.open("rb"), "sha256").hexdigest()
        assert digest == asset.sha256 and path.stat().st_size == asset.size
        row = downloads.submit(identifier)
        shutil.copyfile(path, downloads.paths(asset)[1])
        downloads.update(row["id"], "downloaded", asset.size)
        provenance.append({"id": identifier, "sha256": digest, "bytes": asset.size})
    memory = Memory(store)
    index = SemanticIndex(store, downloads)
    memory.semantic = index
    records = [memory.create(title, content) for title, content, _ in CASES]
    for title, content in DISTRACTORS:
        memory.create(title, content)
    tasks = WorkRegistry(store)
    project = tasks.create("Project A", "Isolate project memory")
    other = tasks.create("Project B", "Separate task")
    scoped = memory.create("Scope", "Project A uses a green toolbar.", project["id"])
    memory.create("Scope", "Project B uses a red toolbar.", other["id"])
    exported = [
        {
            "id": "semantic-synthetic-history",
            "title": "Prior design",
            "current_node": "message",
            "mapping": {
                "message": {
                    "parent": None,
                    "message": {
                        "author": {"role": "user"},
                        "content": {
                            "content_type": "text",
                            "parts": [
                                "Our vacation cabin reservation is beside a mountain lake "
                                "in September."
                            ],
                        },
                    },
                }
            },
        }
    ]
    archive = args.data / "synthetic-export.json"
    archive.write_text(json.dumps(exported))
    parsed = read_archive(archive)
    history = History(store)
    history.apply(parsed, uid(), parsed["archive_sha256"])
    imported = store.one("SELECT conversation_id FROM history_sources")["conversation_id"]
    started = time.perf_counter()
    socket.socket.connect = denied
    socket.socket.connect_ex = denied
    socket.create_connection = denied
    socket.getaddrinfo = denied
    await index.configure(0, True, True)
    loaded = time.perf_counter()
    while await index.process_one():
        pass
    indexed = time.perf_counter()
    quality = []
    for expected, (_, _, query) in zip(records, CASES, strict=True):
        before = time.perf_counter()
        result = await index.search(query)
        matches = result["results"]
        keyword = memory.retrieve(query, byte_budget=10000)
        quality.append(
            {
                "query": query,
                "expected": expected["title"],
                "top": matches[0]["title"] if matches else None,
                "top_score": matches[0]["score"] if matches else None,
                "top1_correct": bool(matches and matches[0]["id"] == expected["id"]),
                "keyword_found_expected": expected["id"] in {r["id"] for r in keyword},
                "seconds": time.perf_counter() - before,
            }
        )
    checks = {}
    hits = await index.search("What color is the app navigation?", task_id=project["id"])
    checks["project_scope"] = [r["id"] for r in hits["results"]] == [scoped["id"]]
    hits = await index.search("Where are we staying during the autumn trip?", "history")
    checks["imported_history"] = hits["results"][0]["conversation_id"] == imported
    with store.transaction() as db:
        db.execute("UPDATE conversations SET hidden=1 WHERE id=?", (imported,))
    checks["hidden_excluded"] = not (await index.search("trip", "history"))["results"]
    checks["hidden_explicit"] = bool(
        (await index.search("trip", "history", hidden=True))["results"]
    )
    history.remove(imported)
    checks["removed_history_invalidated"] = not (
        await index.search("trip", "history", hidden=True)
    )["results"]
    target = records[0]
    memory.delete(target["id"], 1)
    checks["deleted_memory_invalidated"] = target["id"] not in {
        r["id"] for r in (await index.search(CASES[0][2]))["results"]
    }
    restart = SemanticIndex(Store(args.data), downloads)
    result = await restart.search(CASES[1][2])
    checks["persistent_index_after_restart"] = result["results"][0]["id"] == records[1]["id"]
    checks["cpu_only"] = index.engine.session.get_providers() == ["CPUExecutionProvider"]
    checks["network_denied_during_inference"] = True
    await restart.configure(1, False, False)
    checks["disable_purges_vectors"] = not store.all("SELECT 1 FROM semantic_chunks")
    try:
        rss = psutil.Process().memory_info().rss
        memory_error = None
    except psutil.Error as exc:
        rss, memory_error = None, type(exc).__name__
    report = {
        "fixture": "synthetic English paraphrases; not a broad model-quality benchmark",
        "model": "BAAI/bge-small-en-v1.5",
        "assets": provenance,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "load_seconds": loaded - started,
        "index_seconds": indexed - loaded,
        "rss_bytes_at_end": rss,
        "memory_measurement_error": memory_error,
        "quality": quality,
        "checks": checks,
        "passed": all(checks.values()) and all(q["top1_correct"] for q in quality),
        "limitations": [
            "English only",
            "No RTX/Windows/Pixel acceptance",
            "No LLM generation",
            "Python network tripwire; not an OS-level network isolation claim",
        ],
    }
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    asyncio.run(main(parser.parse_args()))
