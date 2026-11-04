"""Real publisher download/recovery probe. Never changes product network policy.

An explicit environment-proxy fixture is available only to this test script for
restricted build environments. Its result does NOT prove direct DNS/TLS pinning.
"""

import argparse
import asyncio
import hashlib
import json
import os
import ssl
import tempfile
from pathlib import Path

import httpx

from dsgpt.catalog import CATALOG
from dsgpt.downloads import DownloadManager, validate_source_url
from dsgpt.storage import Store


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed-from", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--environment-proxy-fixture", action="store_true")
    args = parser.parse_args()
    asset = CATALOG["qwen3-1-7b-q8-0"]
    with args.seed_from.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != asset.sha256:
            raise ValueError("Seed bytes do not match reviewed publisher artifact")
    observed = []

    class EnvironmentProxyFixture(httpx.AsyncBaseTransport):
        def __init__(self):
            self.transport = httpx.AsyncHTTPTransport(
                proxy=os.environ["HTTPS_PROXY"], verify=ssl.create_default_context()
            )

        async def handle_async_request(self, request):
            validate_source_url(request.url)
            response = await self.transport.handle_async_request(request)
            observed.append(
                {
                    "host": request.url.host,
                    "status": response.status_code,
                    "range": request.headers.get("range"),
                    "content_range": response.headers.get("content-range"),
                }
            )
            return response

        async def aclose(self):
            await self.transport.aclose()

    with tempfile.TemporaryDirectory(prefix="dsgpt-live-download-") as temporary:
        manager = DownloadManager(
            Store(Path(temporary)),
            transport_factory=(EnvironmentProxyFixture if args.environment_proxy_fixture else None),
            reserve=0,
        )
        job = manager.submit(asset.id)
        partial, final = manager.paths(asset)
        seed_size = asset.size - 1024**2
        with args.seed_from.open("rb") as source, partial.open("xb") as target:
            remaining = seed_size
            while remaining:
                data = source.read(min(1024**2, remaining))
                target.write(data)
                remaining -= len(data)
        manager.update(job["id"], "downloading", 0)
        await manager.start()
        try:
            async with asyncio.timeout(90):
                while manager.get(job["id"])["status"] not in {"downloaded", "failed"}:
                    await asyncio.sleep(0.05)
            result = manager.get(job["id"])
            report = {
                "fixture": "environment_proxy" if args.environment_proxy_fixture else "direct",
                "direct_public_transport_validated": not args.environment_proxy_fixture,
                "asset_id": asset.id,
                "expected_sha256": asset.sha256,
                "seed_bytes": seed_size,
                "requested_network_bytes": asset.size - seed_size,
                "status": result["status"],
                "error_code": result["error_code"],
                "observed": observed,
                "verified_final_file": final.is_file(),
            }
            args.output.write_text(json.dumps(report, indent=2) + "\n")
            print(json.dumps(report))
            if result["status"] != "downloaded":
                raise SystemExit(1)
        finally:
            await manager.stop()


if __name__ == "__main__":
    asyncio.run(main())
