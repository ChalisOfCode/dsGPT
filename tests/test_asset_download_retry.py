"""Pinned image asset downloads recover only before response bytes are consumed."""

import hashlib
import io
from unittest.mock import Mock, call
from urllib.error import HTTPError, URLError

import pytest

from dsgpt import asset_install


@pytest.mark.parametrize("error", [TimeoutError(), URLError(TimeoutError()),
                                  HTTPError("https://example.invalid", 504, "", {}, None)])
def test_transient_open_failure_recovers_and_exhausts(error, monkeypatch):
    response = object()
    opening = Mock(side_effect=[error, error, response])
    sleep = Mock()
    monkeypatch.setattr(asset_install.urllib.request, "urlopen", opening)
    monkeypatch.setattr(asset_install.time, "sleep", sleep)
    assert asset_install.open_asset_download("https://example.invalid") is response
    assert opening.call_args_list == [call("https://example.invalid", timeout=120)] * 3
    assert sleep.call_args_list == [call(1), call(2)]
    opening.reset_mock(side_effect=True)
    sleep.reset_mock()
    opening.side_effect = error
    with pytest.raises(type(error)):
        asset_install.open_asset_download("https://example.invalid")
    assert opening.call_count == 3
    assert sleep.call_args_list == [call(1), call(2)]


@pytest.mark.parametrize("error", [URLError("certificate verification failed"),
                                  HTTPError("https://example.invalid", 403, "", {}, None)])
def test_other_open_failures_are_fatal(error, monkeypatch):
    opening = Mock(side_effect=error)
    sleep = Mock()
    monkeypatch.setattr(asset_install.urllib.request, "urlopen", opening)
    monkeypatch.setattr(asset_install.time, "sleep", sleep)
    with pytest.raises(type(error)):
        asset_install.open_asset_download("https://example.invalid")
    assert opening.call_count == 1
    sleep.assert_not_called()


def test_install_retries_before_file_creation_and_verifies_bytes(monkeypatch, tmp_path):
    data = b"verified"
    target = tmp_path / "downloads/apktool.jar"
    def open_response(url, timeout):
        assert not target.exists()
        if opening.call_count == 1:
            raise TimeoutError()
        return io.BytesIO(data)
    opening = Mock(side_effect=open_response)
    monkeypatch.setattr(asset_install.urllib.request, "urlopen", opening)
    monkeypatch.setattr(asset_install.time, "sleep", Mock())
    monkeypatch.setattr(asset_install, "INPUTS", ((
        "apktool.jar", "https://example.invalid", len(data),
        hashlib.sha256(data).hexdigest(), "apktool", "jar",
    ),))
    for folder in ("jadx/bin", "ghidra/support"):
        (tmp_path / folder).mkdir(parents=True)
    asset_install.install(tmp_path)
    assert opening.call_count == 2
    assert (tmp_path / "apktool/apktool.jar").read_bytes() == data


@pytest.mark.parametrize("failure", ["stream", "size", "digest"])
def test_partial_or_invalid_asset_is_not_retried_or_installed(failure, monkeypatch, tmp_path):
    expected = b"verified"
    response = io.BytesIO(b"too large" if failure == "size" else b"modified")
    if failure == "stream":
        response.read = Mock(side_effect=[b"part", TimeoutError()])
    opening = Mock(return_value=response)
    sleep = Mock()
    monkeypatch.setattr(asset_install.urllib.request, "urlopen", opening)
    monkeypatch.setattr(asset_install.time, "sleep", sleep)
    monkeypatch.setattr(asset_install, "INPUTS", ((
        "apktool.jar", "https://example.invalid", len(expected),
        hashlib.sha256(expected).hexdigest(), "apktool", "jar",
    ),))
    with pytest.raises(TimeoutError if failure == "stream" else ValueError):
        asset_install.install(tmp_path)
    assert opening.call_count == 1
    sleep.assert_not_called()
    assert not (tmp_path / "apktool").exists()
