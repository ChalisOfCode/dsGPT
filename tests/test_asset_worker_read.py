"""The isolated worker's text pages preserve bytes and terminate explicitly."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

WORKER_PATH = Path(__file__).resolve().parents[1] / "src/dsgpt/asset_worker.py"
SPEC = importlib.util.spec_from_file_location("asset_worker_read_under_test", WORKER_PATH)
worker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(worker)


@pytest.mark.parametrize("symbol", ["é", "中", "🙂"])
@pytest.mark.parametrize("overhang", [1, 2, 3])
def test_pages_reconstruct_exact_unicode_bytes(tmp_path, symbol, overhang):
    raw = ("a" * (6000 - overhang) + symbol * 3001 + " tail").encode()
    source = tmp_path / "unicode.txt"
    source.write_bytes(raw)
    pages, offset = [], 0
    while True:
        page = worker.read_utf8_page(source, offset)
        chunk = page["text"].encode()
        assert page["offset"] == offset and page["bytes"] == len(raw)
        assert chunk == raw[offset : offset + len(chunk)]
        assert 0 < len(chunk) <= 6000
        pages.append(chunk)
        if not page["has_more"]:
            assert page["next_offset"] is None
            break
        assert page["next_offset"] == offset + len(chunk)
        offset = page["next_offset"]
    assert b"".join(pages) == raw
    assert source.read_bytes() == raw


@pytest.mark.parametrize("raw", [b"", b"short", b"x" * 6000])
def test_eof_is_null_including_empty_exact_page_and_beyond_end(tmp_path, raw):
    source = tmp_path / "text.txt"
    source.write_bytes(raw)
    for offset in (0, len(raw), len(raw) + 100):
        page = worker.read_utf8_page(source, offset)
        assert page["text"].encode() == raw[offset:]
        assert page["next_offset"] is None and not page["has_more"]


@pytest.mark.parametrize("raw,offset", [(b"abc\xff", 0), (b"abc\xc3", 0), ("é".encode(), 1)])
def test_invalid_utf8_or_mid_character_offset_is_not_silently_replaced(tmp_path, raw, offset):
    source = tmp_path / "invalid.txt"
    source.write_bytes(raw)
    with pytest.raises(UnicodeError):
        worker.read_utf8_page(source, offset)


def test_negative_offset_is_rejected(tmp_path):
    source = tmp_path / "text.txt"
    source.write_text("hello")
    with pytest.raises(ValueError, match="nonnegative"):
        worker.read_utf8_page(source, -1)


@pytest.mark.parametrize(
    "invalid_tail", [b"\xf0\x9f", b"\xed\xa0\x80", b"\xe0\x80\xaf", b"\xf4\x90\x80\x80"]
)
def test_malformed_sequence_crossing_boundary_fails_on_continuation(tmp_path, invalid_tail):
    source = tmp_path / "broken-tail.txt"
    source.write_bytes(b"a" * 5999 + invalid_tail)
    first = worker.read_utf8_page(source)
    assert first["text"] == "a" * 5999
    assert first["has_more"] is True and first["next_offset"] == 5999
    with pytest.raises(UnicodeError):
        worker.read_utf8_page(source, first["next_offset"])


def test_real_cli_emits_final_page_and_does_not_modify_original(tmp_path):
    source = tmp_path / "text.txt"
    raw = "notes: café 🙂".encode()
    source.write_bytes(raw)
    result = subprocess.run(
        [sys.executable, "-I", str(WORKER_PATH), "read", "text.txt"],
        cwd=tmp_path,
        capture_output=True,
        timeout=10,
        check=True,
    )
    page = json.loads(result.stdout)
    assert page["text"].encode() == raw
    assert page["next_offset"] is None and page["has_more"] is False
    assert source.read_bytes() == raw
