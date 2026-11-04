"""Test-only local HTTP download worker for actual process-kill recovery tests."""

import argparse
import asyncio
import hashlib
from pathlib import Path

import httpx

from dsgpt.catalog import Asset
from dsgpt.downloads import DownloadManager
from dsgpt.storage import Store

DATA = b"GGUF" + bytes(range(256)) * 8192


async def run(directory, origin):
    target = httpx.URL(origin)
    if target.scheme != "http" or target.host != "127.0.0.1":
        raise ValueError("Fixture server must be loopback")

    class ForwardFixture(httpx.AsyncBaseTransport):
        def __init__(self):
            self.transport = httpx.AsyncHTTPTransport()

        async def handle_async_request(self, request):
            request.url = target.copy_with(path="/fixture")
            request.headers["host"] = target.netloc.decode()
            return await self.transport.handle_async_request(request)

        async def aclose(self):
            await self.transport.aclose()

    asset = Asset(
        "recovery",
        "Recovery fixture",
        "https://huggingface.co/test/test/resolve/" + "a" * 40 + "/fixture.gguf",
        hashlib.sha256(DATA).hexdigest(),
        len(DATA),
        "test",
        "test",
        "synthetic test",
    )
    manager = DownloadManager(Store(directory), {asset.id: asset}, ForwardFixture, reserve=0)
    job = manager.submit(asset.id)
    await manager.start()
    try:
        async with asyncio.timeout(30):
            while True:
                row = manager.get(job["id"])
                if row["status"] == "downloaded":
                    return
                if row["status"] == "failed":
                    raise RuntimeError(row["error_code"])
                await asyncio.sleep(0.01)
    finally:
        await manager.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--origin", required=True)
    args = parser.parse_args()
    asyncio.run(run(args.data, args.origin))
