import base64
import io
import json
import stat
import zipfile

import pytest
from conftest import pair
from test_document_processing import SAMPLES, tools

from dsgpt.config import Model
from dsgpt.storage import uid


def archive(entries):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in entries:
            z.writestr(name, text)
    return base64.b64encode(out.getvalue()).decode()


def test_work_document_and_archive_preview_import_export_and_local_images(backend):
    tools(backend)
    entries = [
        {"name": "private.png", "original_base64": SAMPLES["image.png"]},
        {
            "name": "source.zip",
            "original_base64": archive(
                [("src/main.py", 'print("PRIVATE")'), ("README.md", "Private plan")]
            ),
        },
    ]
    phone, _ = pair(backend, ["work"])
    headers = {"Authorization": "Bearer " + phone["token"]}
    for entry in entries:
        preview = backend.client.post("/v1/work/inputs/preview", json=entry, headers=headers)
        assert preview.status_code == 200, preview.text
        assert "original_base64" not in preview.json()
    assert not backend.store.all("SELECT * FROM work_inputs")
    identifier = uid()
    body = {
        "title": "Private input",
        "requirements": "Review locally",
        "request_id": identifier,
        "source_files": entries,
    }
    result = backend.client.post("/v1/work/tasks", json=body, headers=headers)
    assert result.status_code == 201, result.text
    assert backend.client.post("/v1/work/tasks", json=body, headers=headers).status_code == 201
    files = backend.client.get(f"/v1/work/tasks/{identifier}/files", headers=headers).json()
    assert {f["path"] for f in files} == {"private.png.txt", "src/main.py", "README.md"}
    response = backend.client.get(f"/v1/work/tasks/{identifier}/export", headers=headers)
    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        assert z.read("inputs/private.png") == base64.b64decode(SAMPLES["image.png"])
        assert z.read("inputs/source.zip") == base64.b64decode(entries[1]["original_base64"])
        assert z.read("project/src/main.py") == b'print("PRIVATE")'
        assert len(json.loads(z.read("inputs.json"))) == 2
    model = Model("vision", "Vision", "ollama", "http://127.0.0.1:11434", "local", context=32768)
    context = backend.app.state.work._prompt(
        backend.app.state.work.get(identifier), {"summary": "", "step": 0}, model, []
    )
    assert context[1]["images"] == [SAMPLES["image.png"]]
    assert backend.app.state.work.public_research.status(identifier)["public_query"] is None


@pytest.mark.parametrize(
    "entries",
    [
        [("../outside.py", "bad")],
        [("src/main.py", "one"), ("src/MAIN.py", "two")],
        [("binary.exe", b"MZ\0binary")],
        [(".git/config", "bad")],
        [("huge.txt", "a" * 262145)],
    ],
)
def test_unsafe_zip_rejected_without_partial_task(backend, entries):
    identifier = uid()
    response = backend.client.post(
        "/v1/work/tasks",
        json={
            "title": "Invalid",
            "requirements": "Read",
            "request_id": identifier,
            "source_files": [{"name": "source.zip", "original_base64": archive(entries)}],
        },
    )
    assert response.status_code in {413, 422}, response.text
    assert not backend.store.one("SELECT id FROM work_tasks WHERE id=?", (identifier,))
    assert not backend.store.all("SELECT * FROM work_inputs")


def test_zip_symlink_is_never_extracted(backend):
    link = zipfile.ZipInfo("link.py")
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    response = backend.client.post(
        "/v1/work/inputs/preview",
        json={"name": "source.zip", "original_base64": archive([(link, "/host/private")])},
    )
    assert response.status_code == 422


@pytest.mark.parametrize("method", [8, 99])
def test_corrupt_or_unsupported_zip_compression_is_a_client_error(backend, method):
    import struct

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as z:
        z.writestr("broken.py", b"\x06" * 100)
    raw = buffer.getvalue()
    data = bytearray(raw)
    # Change both headers from stored to invalid deflate or an unsupported method.
    struct.pack_into("<H", data, 8, method)
    struct.pack_into("<H", data, data.index(b"PK\x01\x02") + 10, method)
    response = backend.client.post(
        "/v1/work/inputs/preview",
        json={"name": "source.zip", "original_base64": base64.b64encode(data).decode()},
    )
    assert response.status_code == 422, response.text
    assert backend.store.all("SELECT * FROM work_inputs") == []
    assert backend.store.all("SELECT * FROM work_tasks") == []
