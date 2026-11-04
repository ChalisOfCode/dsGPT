"""Production-download and CPU ONNX acceptance for private attachment paraphrase retrieval."""

import argparse
import asyncio
import json
import socket
import tempfile
from pathlib import Path

from dsgpt.attachments import Attachments, prepare
from dsgpt.downloads import DownloadManager
from dsgpt.embeddings import ASSET_IDS
from dsgpt.semantic import SemanticIndex
from dsgpt.storage import Store, uid, utcnow

CASES = [
    (
        "food.txt",
        "The guest eats exclusively plant-based meals. No dairy, eggs, meat or fish.",
        "Which dietary restrictions should the restaurant follow?",
    ),
    (
        "calendar.txt",
        "Arrange meetings after three in the afternoon, using Denver time.",
        "At what hour should someone schedule a call?",
    ),
    (
        "storage.txt",
        "Persist application records in SQLite and run entirely without remote services.",
        "What database engine and deployment boundary were selected?",
    ),
    (
        "readability.txt",
        "Use large lettering with strong contrast when sharing documents.",
        "What visual accessibility accommodations are needed?",
    ),
]


def denied(*args, **kwargs):
    raise AssertionError("Network attempted during local semantic inference")


async def main(args):
    with tempfile.TemporaryDirectory(prefix="dsgpt-attachment-semantic-") as directory:
        store = Store(Path(directory))
        downloads = DownloadManager(store)
        for asset in ASSET_IDS:
            downloads.submit(asset)
        await downloads.start()
        try:
            async with asyncio.timeout(600):
                while True:
                    rows = store.all("SELECT * FROM downloads")
                    if all(r["status"] == "downloaded" for r in rows):
                        break
                    assert not any(r["status"] == "failed" for r in rows), rows
                    await asyncio.sleep(0.25)
        finally:
            await downloads.stop()
        report = {"download_assets": [{"id": r["asset_id"], "status": r["status"]} for r in rows]}
        chat, message, now = uid(), uid(), utcnow()
        with store.transaction() as db:
            db.execute(
                "INSERT INTO conversations(id,title,created_at,updated_at) VALUES(?,?,?,?)",
                (chat, "Private document fixtures", now, now),
            )
            db.execute(
                "INSERT INTO messages VALUES(?,?,?,?,?,?,?)",
                (message, chat, "user", "Read the attached records", "completed", 1, now),
            )
            Attachments(store).insert(
                db, message, prepare([{"name": n, "text": t} for n, t, _ in CASES])
            )
        socket.socket.connect = denied
        socket.socket.connect_ex = denied
        socket.create_connection = denied
        socket.getaddrinfo = denied
        semantic = SemanticIndex(store, downloads)
        await semantic.configure(0, True, False, True)
        while await semantic.process_one():
            pass
        matches = []
        for name, _, query in CASES:
            result = await semantic.search(query, "attachment")
            assert result["results"] and result["results"][0]["name"] == name, result
            hit = result["results"][0]
            matches.append({"query": query, "top": hit["name"], "score": hit["score"]})
        with store.transaction() as db:
            db.execute("UPDATE conversations SET hidden=1 WHERE id=?", (chat,))
        assert not (await semantic.search("diet", "attachment"))["results"]
        assert (await semantic.search("diet", "attachment", hidden=True))["results"]
        for row in store.all("SELECT id FROM message_attachments"):
            Attachments(store).remove(chat, row["id"])
        assert not (await semantic.search("diet", "attachment", hidden=True))["results"]
        assert not store.all("SELECT 1 FROM semantic_chunks WHERE kind='attachment'")
        report.update(
            passed=True,
            matches=matches,
            hidden_excluded=True,
            removal_purges_vectors=True,
            network_denied_during_inference=True,
            providers=semantic.engine.session.get_providers(),
            limitation="Synthetic English cases; not broad quality or GPU acceptance",
        )
        args.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(main(parser.parse_args()))
