import hashlib
import io
import zipfile

import pytest

from dsgpt.storage import uid


def test_source_import_is_atomic_retry_safe_and_scoped_to_task(backend):
    task_id = uid()
    body = {
        "title": "Private project",
        "requirements": "Review supplied source",
        "request_id": task_id,
        "source_files": [{"name": "main.py", "text": "print('private')\n"}],
    }
    response = backend.client.post("/v1/work/tasks", json=body)
    assert response.status_code == 201
    assert backend.client.post("/v1/work/tasks", json=body).json()["id"] == task_id
    files = backend.client.get(f"/v1/work/tasks/{task_id}/files").json()
    assert len(files) == 1 and files[0]["revision"] == 1
    assert files[0]["sha256"] == hashlib.sha256(b"print('private')\n").hexdigest()
    receipt = backend.client.get(f"/v1/work/tasks/{task_id}/checkpoints").json()[0]["state"]
    assert receipt["action"] == "import_source_files"
    assert "private" not in str(receipt)
    changed = dict(body, source_files=[{"name": "main.py", "text": "changed"}])
    assert backend.client.post("/v1/work/tasks", json=changed).status_code == 409
    other = backend.client.post(
        "/v1/work/tasks", json={"title": "Other", "requirements": "Separate"}
    ).json()
    assert backend.client.get(f"/v1/work/tasks/{other['id']}/files").json() == []
    exported = backend.client.get(f"/v1/work/tasks/{task_id}/export")
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        assert archive.read("project/main.py") == b"print('private')\n"
    assert backend.store.one("SELECT count(*) AS n FROM work_executions")["n"] == 0


@pytest.mark.parametrize(
    "files",
    [
        [{"name": "../outside.py", "text": "bad"}],
        [{"name": "COM0.py", "text": "reserved by project policy"}],
        [{"name": "file.py", "text": "one"}, {"name": "FILE.py", "text": "two"}],
        [{"name": "file.py", "text": "bad\u0000binary"}],
        [{"name": "file.py", "text": "é" * 40000}],
    ],
)
def test_invalid_source_import_leaves_no_partial_task(backend, files):
    task_id = uid()
    response = backend.client.post(
        "/v1/work/tasks",
        json={
            "title": "Bad files",
            "requirements": "Read",
            "request_id": task_id,
            "source_files": files,
        },
    )
    assert response.status_code in {413, 422}
    assert backend.client.get(f"/v1/work/tasks/{task_id}").status_code == 404
    assert backend.store.one("SELECT count(*) AS n FROM work_files")["n"] == 0
