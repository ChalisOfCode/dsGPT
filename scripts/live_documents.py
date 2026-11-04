"""Real networkless decoder verification against the independently installed wheel."""

import argparse
import asyncio
import base64
import hashlib
import json
import tempfile
from pathlib import Path

from dsgpt.builds import WorkBuilds
from dsgpt.document_processing import DocumentProcessor
from dsgpt.storage import Store


async def main(args):
    samples = json.loads(args.samples.read_text())
    report = {"checks": [], "image": args.image}
    with tempfile.TemporaryDirectory(prefix="dsgpt-documents-") as directory:
        store = Store(Path(directory))
        builds = WorkBuilds(store, image=args.image)
        report["isolation"] = await builds.probe()
        processor = DocumentProcessor(store, builds)
        for name, encoded in samples.items():
            result = (await processor.prepare([{"name": name, "original_base64": encoded}]))[0]
            marker = "COBALT" if name == "text.pdf" else "ORCHID"
            assert marker in result["text"], result["text"]
            assert result["original_base64"] == encoded
            assert result["sha256"] == hashlib.sha256(base64.b64decode(encoded)).hexdigest()
            report["checks"].append(
                {
                    "name": name,
                    "marker_found": True,
                    "sha256": result["sha256"],
                    "document": result["document"],
                }
            )
        assert not store.all("SELECT * FROM work_executions WHERE cleanup_pending=1")
        assert not store.all("SELECT * FROM message_attachments"), "Preview persisted attachment"
        code, out, _, _ = await builds.sandbox.cli(
            [
                "container",
                "ls",
                "-aq",
                "--filter",
                "label=org.dsgpt.owner=" + builds.sandbox.owner_id,
            ]
        )
        assert code == 0 and not out.strip(), "Leaked document container"
        report["no_remaining_containers"] = True
        report["passed"] = True
    args.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--samples", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(main(parser.parse_args()))
