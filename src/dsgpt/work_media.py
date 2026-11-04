"""Bounded public file retrieval; downloaded bytes remain inert task inputs."""

import asyncio
import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urljoin

import httpx

from .downloads import DownloadError, PublicHTTPS
from .storage import canonical, utcnow
from .web_retrieval import ResearchError, public_url, validate_public_request
from .work_uploads import MAX_INPUTS, MAX_UPLOAD


def capacity(db, task_id, name, size=1):
    rows = db.execute(
        "SELECT name,length(original) AS bytes FROM work_inputs WHERE task_id=?", (task_id,)
    ).fetchall()
    if any(r["name"].casefold() == name.casefold() for r in rows):
        raise ResearchError("download_filename_already_exists")
    if len(rows) >= 4 or size + sum(r["bytes"] for r in rows) > MAX_INPUTS:
        raise ResearchError("work_input_limit_reached")


class PublicFileReader:
    def __init__(self, transport_factory=None, max_bytes=MAX_UPLOAD):
        self.transport_factory = transport_factory or (
            lambda: PublicHTTPS(validator=validate_public_request)
        )
        self.max_bytes = max_bytes

    async def fetch(self, raw, output):
        url = public_url(raw)
        try:
            async with asyncio.timeout(300):
                async with httpx.AsyncClient(
                    transport=self.transport_factory(),
                    trust_env=False,
                    follow_redirects=False,
                    timeout=httpx.Timeout(30, connect=10),
                    headers={"Accept-Encoding": "identity", "User-Agent": "dsGPT-files/0.9.1"},
                ) as client:
                    for _ in range(6):
                        url = public_url(url)
                        client.cookies.clear()
                        async with client.stream("GET", url) as response:
                            if response.status_code in {301, 302, 303, 307, 308}:
                                location = response.headers.get("location")
                                if not location:
                                    raise ResearchError("download_invalid_redirect")
                                url = public_url(urljoin(url, location))
                                continue
                            if response.status_code != 200:
                                raise ResearchError("download_source_inaccessible")
                            content_type = response.headers.get("content-type", "").split(";")[0]
                            if content_type.lower().strip() in {
                                "text/html",
                                "application/xhtml+xml",
                            }:
                                raise ResearchError("download_requires_direct_file_url")
                            if response.headers.get("content-encoding", "identity") != "identity":
                                raise ResearchError("download_encoded_response_unsupported")
                            declared = response.headers.get("content-length")
                            if declared is not None and not 0 < int(declared) <= self.max_bytes:
                                raise ResearchError("download_file_size_limit")
                            digest, size = hashlib.sha256(), 0
                            with output.open("wb") as target:
                                async for chunk in response.aiter_raw(256 * 1024):
                                    size += len(chunk)
                                    if size > self.max_bytes:
                                        raise ResearchError("download_file_size_limit")
                                    digest.update(chunk)
                                    target.write(chunk)
                            if not size or (declared is not None and int(declared) != size):
                                raise ResearchError("download_incomplete")
                            return {
                                "url": raw,
                                "final_url": url,
                                "retrieved_at": utcnow(),
                                "bytes": size,
                                "sha256": digest.hexdigest(),
                                "content_type": content_type[:200],
                                "format": "asset",
                            }
                    raise ResearchError("download_too_many_redirects")
        except ResearchError:
            raise
        except DownloadError as exc:
            raise ResearchError("download_address_not_public") from exc
        except (OSError, httpx.HTTPError, TimeoutError, ValueError) as exc:
            raise ResearchError("download_failed") from exc


class WorkMedia:
    def __init__(self, store, reader=None):
        self.store = store
        self.reader = reader or PublicFileReader()

    def urls(self, task_id):
        """Constrain generation to exact observed links when any are available."""
        task = self.store.one("SELECT requirements FROM work_tasks WHERE id=?", (task_id,))
        candidates = [
            (url, True)
            for url in re.findall(
                r'https://[^\s<>"`\x00-\x1f]+', task["requirements"] if task else ""
            )
        ]
        for row in self.store.all(
            "SELECT url,json_extract(document,'$.links') AS links FROM work_sources "
            "WHERE task_id=? AND status!='removed' ORDER BY updated_at DESC LIMIT 32",
            (task_id,),
        ):
            candidates.append((row["url"], False))
            candidates.extend((url, False) for url in json.loads(row["links"] or "[]")[:60])
        urls = []
        for candidate, conversational in candidates:
            # Sentence punctuation is not part of a bare conversational URL.
            if conversational:
                candidate = candidate.rstrip(".,;!?")
                for opening, closing in (("(", ")"), ("[", "]"), ("{", "}")):
                    while candidate.endswith(closing) and candidate.count(
                        closing
                    ) > candidate.count(opening):
                        candidate = candidate[:-1]
            try:
                url = public_url(candidate)
            except ResearchError:
                continue
            if url not in urls:
                urls.append(url)
            if len(urls) > 32:
                # Do not hide valid links behind an incomplete grammar enum.
                return None
        return urls

    def cached(self, task_id, url, name):
        rows = self.store.all(
            "SELECT name,sha256,extraction FROM work_inputs WHERE task_id=?", (task_id,)
        )
        for row in rows:
            metadata = json.loads(row["extraction"])
            if row["name"] == name and metadata.get("url") == url:
                return {**metadata, "path": "inputs/" + name, "cached": True}
        with self.store.connect() as db:
            capacity(db, task_id, name)
        return None

    async def fetch(self, url, name, directory):
        if shutil.disk_usage(self.store.directory).free < 3 * MAX_UPLOAD + 64 * 1024**2:
            raise ResearchError("download_storage_full")
        output = Path(directory) / "body"
        metadata = await self.reader.fetch(url, output)
        return {**metadata, "path": "inputs/" + name}, output

    def temporary(self):
        return tempfile.TemporaryDirectory(prefix="public-file-", dir=self.store.directory)

    @staticmethod
    def save(db, task_id, name, metadata, output):
        capacity(db, task_id, name, metadata["bytes"])
        cursor = db.execute(
            "INSERT INTO work_inputs VALUES(?,?,zeroblob(?),?,?)",
            (task_id, name, metadata["bytes"], metadata["sha256"], canonical(metadata)),
        )
        with db.blobopen("work_inputs", "original", cursor.lastrowid) as blob:
            with output.open("rb") as source:
                while chunk := source.read(256 * 1024):
                    blob.write(chunk)
        return {**metadata, "cached": False}
