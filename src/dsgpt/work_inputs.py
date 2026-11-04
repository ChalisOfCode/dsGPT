"""Private Work documents and bounded UTF-8 source ZIPs; originals never execute on host."""

import base64
import hashlib
import io
import stat
import zipfile
import zlib
from pathlib import PurePosixPath

from fastapi import HTTPException

from .attachments import prepare
from .project_tools import MAX_FILE_BYTES, MAX_FILES, safe_path


class WorkInputs:
    def __init__(self, documents):
        self.documents = documents

    async def prepare(self, values):
        files, originals, total = [], [], 0
        plain_total = 0
        if len(values) > 4:
            raise HTTPException(422, "Choose up to four inputs")
        for value in values:
            name = value["name"]
            if not value.get("original_base64"):
                parsed = prepare([value])
                plain_total += parsed[0]["bytes"]
                if plain_total > 131072:
                    raise HTTPException(413, "Text inputs exceed 128 KiB")
                files.extend(parsed)
                continue
            try:
                safe_path(name)
                if "/" in name:
                    raise ValueError("Input name must not contain folders")
                raw = base64.b64decode(value["original_base64"], validate=True)
                if not raw or len(raw) > 524288:
                    raise ValueError("Originals are limited to 512 KiB")
                total += len(raw)
                if total > 786432:
                    raise ValueError("Originals are limited to 768 KiB total")
                digest = hashlib.sha256(raw).hexdigest()
                if PurePosixPath(name).suffix.lower() == ".zip":
                    imported = self.archive(raw)
                    files.extend(imported)
                    metadata = {
                        "format": "zip",
                        "notice": "UTF-8 source ZIP; no host extraction or execution.",
                        "files": [
                            {"path": f["name"], "sha256": f["sha256"], "bytes": f["bytes"]}
                            for f in imported
                        ],
                    }
                else:
                    item = (await self.documents.prepare([value]))[0]
                    metadata = item["document"]
                    text = item["text"]
                    plain_total += len(text.encode())
                    if plain_total > 131072:
                        raise HTTPException(413, "Extracted/text inputs exceed 128 KiB")
                    files.append(
                        {
                            "name": name + ".txt",
                            "text": text,
                            "bytes": len(text.encode()),
                            "sha256": hashlib.sha256(text.encode()).hexdigest(),
                        }
                    )
                originals.append(
                    {"name": name, "original": raw, "sha256": digest, "extraction": metadata}
                )
            except zlib.error as exc:
                raise HTTPException(
                    422, "The source ZIP is damaged and could not be decompressed"
                ) from exc
            except (ValueError, OSError, zipfile.BadZipFile, RuntimeError) as exc:
                raise HTTPException(422, str(exc)[:300]) from exc
        if len(files) > MAX_FILES or sum(f["bytes"] for f in files) > 8 * 1024**2:
            raise HTTPException(413, "Expanded inputs exceed 128 files or 8 MiB")
        if len({f["name"].casefold() for f in files}) != len(files):
            raise HTTPException(422, "Expanded input paths must be distinct ignoring case")
        if len({f["name"].casefold() for f in originals}) != len(originals):
            raise HTTPException(422, "Original input names must be distinct ignoring case")
        return files, originals

    @staticmethod
    def archive(raw):
        result = []
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if len(entries) > 256 or sum(e.file_size for e in entries) > 8 * 1024**2:
                raise ValueError("ZIP exceeds 256 entries or 8 MiB expanded")
            for entry in entries:
                safe_path(entry.filename.rstrip("/"))
                if entry.is_dir():
                    continue
                mode = entry.external_attr >> 16
                if stat.S_IFMT(mode) not in {0, stat.S_IFREG} or entry.flag_bits & 1:
                    raise ValueError("ZIP links, special files and encryption are unsupported")
                if entry.file_size > MAX_FILE_BYTES:
                    raise ValueError("ZIP source files are limited to 256 KiB each")
                data = archive.read(entry)
                text = data.decode("utf-8")
                if any(ord(c) < 32 and c not in "\n\r\t" for c in text):
                    raise ValueError("ZIP supports UTF-8 source files; attach documents separately")
                result.append(
                    {
                        "name": entry.filename,
                        "text": text,
                        "bytes": len(data),
                        "sha256": hashlib.sha256(data).hexdigest(),
                    }
                )
        if not result:
            raise ValueError("ZIP has no source files")
        return result

    async def preview(self, value):
        files, originals = await self.prepare([value])
        original = originals[0]
        text = (
            "\n".join(f"{f['name']} ({f['bytes']} bytes)" for f in files)
            if original["extraction"]["format"] == "zip"
            else files[0]["text"]
        )
        return {
            "name": value["name"],
            "text": text,
            "bytes": len(original["original"]),
            "sha256": original["sha256"],
            "document": original["extraction"],
        }
