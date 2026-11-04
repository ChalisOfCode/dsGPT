import base64
import hashlib
import io
import json
import zipfile

import pytest
from fastapi import HTTPException

from dsgpt import asset_worker, work_assets
from dsgpt.sandbox import source_archive
from dsgpt.storage import Store
from dsgpt.work_uploads import WorkUploads


def test_large_upload_resume_integrity_and_task_import(backend):
    client = backend.client
    data = bytes(range(256)) * (3 * 4096 + 13)
    first = client.post("/v1/work/uploads", json={"name": "large.apk", "size": len(data)})
    assert first.status_code == 201, first.text
    identifier = first.json()["id"]
    offset = 0
    for chunk in [data[:262144], data[262144:524288]]:
        payload = {"offset": offset, "data": base64.b64encode(chunk).decode()}
        assert client.put("/v1/work/uploads/" + identifier, json=payload).status_code == 200
        assert client.put("/v1/work/uploads/" + identifier, json=payload).status_code == 200
        offset += len(chunk)
    assert client.post("/v1/work/uploads/" + identifier + "/finish").status_code == 409
    recovered = WorkUploads(Store(backend.store.directory))
    owner = backend.credentials["device_id"]
    assert recovered.status(owner, identifier)["received"] == offset
    with pytest.raises(HTTPException):
        recovered.status("another-device", identifier)
    with pytest.raises(HTTPException):
        recovered.chunk(owner, identifier, 0, base64.b64encode(b"wrong").decode())
    while offset < len(data):
        chunk = data[offset : offset + 262144]
        recovered.chunk(owner, identifier, offset, base64.b64encode(chunk).decode())
        offset += len(chunk)
    done = recovered.finish(owner, identifier)
    assert done["sha256"] == hashlib.sha256(data).hexdigest()
    task = client.post(
        "/v1/work/tasks",
        json={
            "title": "Inspect",
            "requirements": "Inspect this file and produce a report",
            "build_target": "files",
            "upload_ids": [identifier],
        },
    )
    assert task.status_code == 201, task.text
    task_id = task.json()["id"]
    original = backend.store.one("SELECT original FROM work_inputs WHERE task_id=?", (task_id,))
    assert original["original"] == data
    recovered.delete(owner, identifier)
    assert (
        backend.store.one("SELECT original FROM work_inputs WHERE task_id=?", (task_id,))[
            "original"
        ]
        == data
    )
    with backend.store.connect() as db:
        rows, _ = work_assets.snapshot(db, task_id)
    import tarfile

    with tarfile.open(fileobj=io.BytesIO(source_archive(rows, input_limit=8 * 1024**2))) as tar:
        assert tar.extractfile("inputs/large.apk").read() == data


def test_upload_limits_and_scope(backend):
    c = backend.client
    for name in ("../app.apk", "CON.exe", "folder/app.apk"):
        assert c.post("/v1/work/uploads", json={"name": name, "size": 1}).status_code == 422
    assert (
        c.post("/v1/work/uploads", json={"name": "video.mp4", "size": 268435457}).status_code == 422
    )
    pair = c.post("/v1/pairings", json={"scopes": ["chat"]}).json()
    token = c.post("/v1/pairings/redeem", json={"code": pair["code"], "name": "Chat only"}).json()[
        "token"
    ]
    assert (
        c.post(
            "/v1/work/uploads",
            json={"name": "x.apk", "size": 1},
            headers={"Authorization": "Bearer " + token},
        ).status_code
        == 403
    )


def test_archive_traversal_duplicate_and_hash_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(asset_worker, "ROOT", tmp_path)
    for members in ({"../outside": "bad"}, {"A.txt": "one", "a.txt": "two"}):
        source = tmp_path / "bad.zip"
        with zipfile.ZipFile(source, "w") as z:
            for name, text in members.items():
                z.writestr(name, text)
        with zipfile.ZipFile(source) as z, pytest.raises(ValueError):
            asset_worker.entries(z)
    source = tmp_path / "good.zip"
    with zipfile.ZipFile(source, "w") as z:
        z.writestr("folder/name.txt", "original")
    out = tmp_path / "decoded"
    asset_worker.unpack(source, out)
    patch = tmp_path / "patch.json"
    patch.write_text(
        json.dumps(
            [
                {
                    "path": "folder/name.txt",
                    "sha256": hashlib.sha256(b"original").hexdigest(),
                    "old": "original",
                    "new": "changed",
                }
            ]
        )
    )
    changes = asset_worker.edits(out, patch)
    assert (out / "folder/name.txt").read_text() == "changed" and changes[0]["before"] != changes[
        0
    ]["after"]
    with pytest.raises(ValueError):
        asset_worker.edits(out, patch)
    with zipfile.ZipFile(source) as z:
        assert z.read("folder/name.txt") == b"original"


def test_office_parts_are_paged_and_xlsx_shared_strings_resolved(tmp_path, monkeypatch):
    monkeypatch.setattr(asset_worker, "ROOT", tmp_path)
    slides = tmp_path / "slides.pptx"
    with zipfile.ZipFile(slides, "w") as z:
        for number in (1, 2, 10):
            z.writestr(
                f"ppt/slides/slide{number}.xml",
                f'<slide xmlns="urn:test"><t>Slide {number}</t></slide>',
            )
    out = tmp_path / "text.txt"
    first = asset_worker.document(slides, out, 1, 2)
    assert first["next_start"] == 3
    assert "Slide 2" in out.read_text() and "Slide 10" not in out.read_text()
    last = asset_worker.document(slides, out, 3, 2)
    assert last["next_start"] is None and "Slide 10" in out.read_text()
    book = tmp_path / "cells.xlsx"
    with zipfile.ZipFile(book, "w") as z:
        z.writestr("xl/sharedStrings.xml", '<sst xmlns="urn:test"><si><t>Label</t></si></sst>')
        z.writestr(
            "xl/worksheets/sheet1.xml",
            '<sheet xmlns="urn:test"><c r="A1" t="s"><v>0</v></c><c r="B1"><v>42</v></c></sheet>',
        )
    asset_worker.document(book, out, 1, 1)
    assert "A1: Label" in out.read_text() and "B1: 42" in out.read_text()
