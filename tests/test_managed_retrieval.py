import json

import pytest

from dsgpt import managed
from dsgpt.storage import uid


def test_owner_console_retrieval_and_probe_keep_credentials_internal(tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(managed, "managed_directory", lambda: tmp_path)

    def request(directory, method, path, body=None, **kwargs):
        calls.append((method, path, body, kwargs))
        return {"revision": 2}

    monkeypatch.setattr(managed, "owner_request", request)
    managed.main(["retrieval-status"])
    assert calls[-1][:2] == ("GET", "/v1/retrieval/settings")
    managed.main(["enable-retrieval", "--revision", "2", "--include-history"])
    assert calls[-1][2] == {"revision": 2, "enabled": True, "history_enabled": True}
    managed.main(["disable-retrieval", "--revision", "3"])
    assert calls[-1][2] == {"revision": 3, "enabled": False, "history_enabled": False}
    task = uid()
    managed.main(["semantic-search", "--question", "A paraphrase", "--task-id", task])
    assert calls[-1][2] == {
        "query": "A paraphrase",
        "kind": "memory",
        "hidden": False,
        "task_id": task,
    }
    managed.main(["sandbox-probe"])
    assert calls[-1] == ("POST", "/v1/work/sandbox/probe", None, {"timeout": 120})
    assert "Bearer" not in capsys.readouterr().out


def test_owner_console_requires_revision_before_change(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(managed, "managed_directory", lambda: tmp_path)
    with pytest.raises(SystemExit):
        managed.main(["enable-retrieval"])
    assert "--revision" in capsys.readouterr().err
    monkeypatch.setattr(managed, "owner_request", lambda *args, **kwargs: {"q": "\x1b[2J"})
    managed.main(["semantic-search", "--question", "Example"])
    value = capsys.readouterr().out
    assert "\x1b" not in value and json.loads(value)["q"] == "\x1b[2J"
