"""Verify pinned managed search startup, loopback binding and owned teardown on Docker."""

import argparse
import asyncio
import json
import tempfile
from pathlib import Path
from uuid import uuid4

from dsgpt.project_tools import ProjectAction
from dsgpt.sandbox import DockerSandbox
from dsgpt.search_service import IMAGE, ORIGIN, SearchService
from dsgpt.search_settings import SearchConfiguration
from dsgpt.storage import Store
from dsgpt.web_retrieval import LocalSearch
from dsgpt.work import WorkRegistry


async def main(args):
    report = {"image": IMAGE}
    with tempfile.TemporaryDirectory(prefix="dsgpt-search-service-") as directory:
        store = Store(Path(directory))
        config = SearchConfiguration(store, LocalSearch(None))
        service = SearchService(store, config)
        transport = DockerSandbox(store.directory, "sha256:" + "0" * 64, service.owner)
        try:
            identifier = str(uuid4())
            service.request(identifier, "start")
            await service.worker
            job = service.status()["job"]
            if job["status"] != "completed":
                code, out, err, _ = await transport.cli(
                    ["container", "logs", "--tail=60", service.name], limit=24000
                )
                print("Search startup diagnostics:", (out + err).decode(errors="replace"))
            assert job["status"] == "completed", job
            assert config.row()["origin"] == ORIGIN
            assert service.request(identifier, "start") == job
            info = json.loads(await transport.checked(["container", "inspect", service.name]))[0]
            service.validate(info)
            report["bindings"] = info["HostConfig"]["PortBindings"]
            report["idempotency"] = True
            work = WorkRegistry(store)
            work.public_research.search = config.search
            task = work.create(
                "Public research loop", "Read Python error documentation", web_mode="on"
            )
            with store.transaction() as db:
                db.execute("UPDATE work_tasks SET status='running' WHERE id=?", (task["id"],))
            searches = []
            for step, query in enumerate(
                [
                    "site:docs.python.org json JSONDecodeError",
                    "site:docs.python.org UnicodeDecodeError encoding",
                ],
                1,
            ):
                receipt = await work.web.execute(
                    task["id"],
                    step,
                    ProjectAction(
                        tool="search_web", query=query, summary="Research a new question"
                    ),
                )
                searches.append(receipt)
                assert receipt.get("results"), receipt
            page = await work.web.execute(
                task["id"],
                3,
                ProjectAction(
                    tool="open_url",
                    url="https://docs.python.org/3/library/json.html",
                    summary="Verify the official documentation",
                ),
            )
            assert page.get("text") and page.get("text_sha256"), page
            report["ongoing_research"] = {"searches": searches, "page": page}
            service.request(str(uuid4()), "stop")
            await service.worker
            assert service.status()["job"]["status"] == "completed"
            assert config.row()["origin"] is None
            report["passed"] = True
        finally:
            await service.stop_worker()
            code, out, _, _ = await transport.cli(["container", "inspect", service.name])
            if code == 0:
                service.validate(json.loads(out)[0])
                await transport.checked(["container", "rm", "--force", service.name])
    args.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(main(parser.parse_args()))
