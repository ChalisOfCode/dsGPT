"""Repeated prompt fitting must preserve already-paged inventory and exact evidence."""

import copy

import pytest

from dsgpt.config import Model
from dsgpt.storage import canonical
from dsgpt.work import compact_asset_context, fit_asset_context


@pytest.mark.parametrize("inputs", [[], [{"path": "inputs/original.txt"}]])
def test_repeated_compaction_preserves_inventory_provenance_and_reader(inputs):
    context = {"assets": {"catalog_sha256": "a" * 64, "inputs": inputs,
                          "total_receipts": 3},
               "project_files": {"files": [{"path": "main.py"}], "total": 7}}
    original = copy.deepcopy(context)
    compact = compact_asset_context(context)
    assert compact_asset_context(compact) == compact
    assert context == original
    assert compact["assets"]["total_inputs"] == len(inputs)
    assert compact["assets"]["catalog_sha256"] == "a" * 64
    assert compact["assets"]["total_receipts"] == 3
    assert compact["assets"]["read"] == {"tool": "list_assets", "offset": 0}
    assert compact["project_files"]["read"] == {"tool": "list_files", "offset": 0}
    messages = [{"role": "system", "content": "Fixture"},
                {"role": "user", "content": canonical(compact)}]
    additions = [{"role": "user", "content": 'Recorded tool result: {"content":""}'}]
    model = Model("local", "Local", "ollama", "http://127.0.0.1:11434", "local",
                  context=16384, output_tokens=4096)
    fitted, prompt = fit_asset_context(messages, compact, additions, model)
    assert fitted == compact
    assert prompt[-1] == additions[0]
