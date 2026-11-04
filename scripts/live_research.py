"""Actual local-model synthesis of two actual public documents, with explicit host fixtures."""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import httpx

from dsgpt.catalog import CATALOG
from dsgpt.downloads import DownloadManager
from dsgpt.security import Auth
from dsgpt.storage import Store, utcnow


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--model-asset", default="qwen3-1-7b-q8-0")
    parser.add_argument("--search-origin")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    report = {
        "started_at": utcnow(),
        "public_transport": "explicit environment-proxy fixture",
        "runtime_listener": "explicit TCP ownership substitute",
        "target_gpu_tested": False,
        "actual_public_documents": True,
        "actual_local_inference": True,
        "model_asset": CATALOG[args.model_asset].public(),
        "actual_search_enabled": args.search_origin is not None,
        "checks": {},
        "backend_source_sha256": {
            str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((root / "src/dsgpt").glob("*.py"))
        },
    }
    with tempfile.TemporaryDirectory(prefix="dsgpt-research-live-") as temp:
        directory = Path(temp)
        store = Store(directory / "data")
        owner = Auth(store).initialize_owner()
        downloads = DownloadManager(store)
        for key in (args.model_asset, "llama-b11718-linux-x64"):
            asset = CATALOG[key]
            row = downloads.submit(key)
            shutil.copyfile(args.inputs / asset.url.rsplit("/", 1)[1], downloads.paths(asset)[1])
            downloads.update(row["id"], "verifying", asset.size)
        log = (directory / "backend.log").open("w+")
        backend = subprocess.Popen(
            [
                sys.executable,
                str(root / "scripts/research_live_fixture.py"),
                "--data",
                str(store.directory),
            ]
            + (["--search-origin", args.search_origin] if args.search_origin else []),
            stdout=log,
            stderr=log,
        )
        try:
            with httpx.Client(
                base_url="http://127.0.0.1:18765",
                trust_env=False,
                timeout=60,
                headers={"Authorization": "Bearer " + owner["token"]},
            ) as client:

                def wait(predicate, timeout=180):
                    deadline = time.monotonic() + timeout
                    while time.monotonic() < deadline:
                        assert backend.poll() is None, "Backend exited"
                        try:
                            result = predicate()
                            if result:
                                return result
                        except httpx.ConnectError:
                            pass
                        time.sleep(0.1)
                    raise AssertionError("Research live fixture timed out")

                def post(path, data=None):
                    response = client.post(path, json=data)
                    response.raise_for_status()
                    return response.json()

                wait(lambda: client.get("/health").status_code == 200, 30)
                wait(
                    lambda: all(
                        r["status"] == "downloaded" for r in client.get("/v1/downloads").json()
                    )
                )
                post("/v1/runtimes/llama-b11718-linux-x64/install")
                post(
                    "/v1/models/managed",
                    {
                        "id": "research-fixture",
                        "name": "Research CPU fixture",
                        "asset_id": args.model_asset,
                        "runtime_id": "llama-b11718-linux-x64",
                        "context": 16384 if args.search_origin else 8192,
                        "output_tokens": 768,
                        "gpu_layers": 0,
                    },
                )
                chat = post("/v1/conversations", {"title": "Actual public source research"})
                run = post(
                    f"/v1/conversations/{chat['id']}/messages",
                    {
                        "request_id": str(uuid4()),
                        "model_id": "research-fixture",
                        "content": "Using both official documents, explain how to request JSON "
                        "search results from SearXNG and what must be enabled "
                        "in its configuration. "
                        "Cite both sources.",
                        "research": {
                            "search": args.search_origin is not None,
                            "urls": [
                                "https://docs.searxng.org/dev/search_api.html",
                                "https://docs.searxng.org/admin/settings/settings_search.html",
                            ],
                        },
                    },
                )
                print("Research accepted; retrieving public documents", flush=True)

                def finished():
                    result = client.get("/v1/runs/" + run["id"]).json()
                    return result if result["status"] in {"failed", "completed"} else None

                run = wait(finished, 600)
                messages = client.get(f"/v1/conversations/{chat['id']}/messages").json()
                snapshot = client.get(f"/v1/conversations/{chat['id']}/latest-run").json()
                sources = client.get(f"/v1/runs/{run['id']}/sources").json()
                answer = messages[-1]["content"]
                record = store.one("SELECT plan FROM run_research WHERE run_id=?", (run["id"],))
                report.update(
                    run=run,
                    answer=answer,
                    sources=sources,
                    query_plan=json.loads(record["plan"]) if record["plan"] else None,
                )
                report["checks"] = {
                    "completed": run["status"] == "completed",
                    "source_refs_survive_history_and_snapshot": messages[-1].get("run_id")
                    == run["id"]
                    and messages[-1].get("research") == 1
                    and snapshot["message"].get("run_id") == run["id"]
                    and snapshot["message"].get("research") == 1,
                    "both_supplied_public_sources_retrieved": len(sources["sources"]) >= 2
                    and all(s["status"] == "retrieved" for s in sources["sources"][:2]),
                    "source_hashes_and_times": all(
                        s.get("content_sha256") and s.get("retrieved_at")
                        for s in sources["sources"]
                        if s["status"] == "retrieved"
                    ),
                    "both_real_citations_rendered": "[S1](<https://docs.searxng.org/dev/search_api.html>)"
                    in answer
                    and "[S2](<https://docs.searxng.org/admin/settings/settings_search.html>)"
                    in answer,
                    "json_configuration_answered": "json" in answer.lower()
                    and "formats" in answer.lower()
                    and re.search(r"\bformat\b", answer.lower()) is not None,
                    "no_fabricated_provenance_disclaimer": "fictional" not in answer.lower()
                    and "hypothetical" not in answer.lower(),
                    "raw_source_text_omitted_from_default_api": all(
                        "text" not in s for s in sources["sources"]
                    ),
                }
                if args.search_origin:
                    report["checks"]["local_model_planned_queries"] = bool(report["query_plan"])
                    report["checks"]["actual_search_added_sources"] = len(sources["sources"]) > 2
                assert all(report["checks"].values()), report["checks"]
        finally:
            if backend.poll() is None:
                backend.terminate()
            backend.wait(timeout=15)
            log.close()
            report["finished_at"] = utcnow()
            args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["checks"]))


if __name__ == "__main__":
    main()
