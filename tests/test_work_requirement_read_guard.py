"""Requirement page guards preserve navigation while avoiding identical visible reads."""

import json

import pytest

from dsgpt.project_tools import action_schema
from dsgpt.storage import canonical
from dsgpt.work import visible_requirement_read


def messages(offset=0):
    text = "The exact saved specification."
    return text, [
        {"role": "assistant", "content": canonical(
            {"tool": "read_requirements", "requirement_id": 1, "offset": offset}
        )},
        {"role": "user", "content": "Recorded tool result: " + canonical({
            "requirement_id": 1, "offset": offset, "content": text[offset:],
            "original_start": 0, "original_end": len(text),
        })},
    ]


@pytest.mark.parametrize("offset", [0, 9])
def test_exact_visible_requirement_excludes_only_that_navigation_pair(offset):
    text, prompt = messages(offset)
    visible = visible_requirement_read(prompt, text)
    assert visible == (1, offset)
    schema = action_schema(specification=True, visible_requirement_page=visible)
    reads = [v for v in schema["oneOf"] if v["properties"]["tool"]["const"] == "read_requirements"]

    def allows(section, position=None):
        for v in reads:
            values = {"requirement_id": section}
            if position is not None:
                values["offset"] = position
            if any(k not in values for k in v["required"] if k not in {"tool", "summary"}):
                continue
            if all(
                d.get("const", n) == n and d.get("minimum", 0) <= n <= d.get("maximum", 10**9)
                for k, n in values.items() for d in [v["properties"][k]]
            ):
                return True
        return False

    assert not allows(1, offset)
    assert allows(1) == bool(offset)  # Omitted offset still means zero.
    assert allows(2) and allows(2, offset)
    assert allows(1, offset + 1)
    if offset:
        assert allows(1, 0)
    assert any(v["properties"]["tool"]["const"] == "edit_file" for v in schema["oneOf"])


@pytest.mark.parametrize("damage", ["changed", "missing", "corrupt", "wrong_offset", "empty"])
def test_unverified_requirement_pages_are_still_readable(damage):
    text, prompt = messages(9)
    if damage == "changed":
        text = text.replace("saved", "newer")
    elif damage == "missing":
        prompt = prompt[:1]
    elif damage == "corrupt":
        prompt[-1]["content"] += "invalid"
    else:
        page = json.loads(prompt[-1]["content"].removeprefix("Recorded tool result: "))
        if damage == "wrong_offset":
            page["offset"] = 10
        else:
            page["content"] = ""
        prompt[-1]["content"] = "Recorded tool result: " + canonical(page)
    assert visible_requirement_read(prompt, text) is None
    schema = action_schema(specification=True, visible_requirement_page=None)
    reads = [v for v in schema["oneOf"] if v["properties"]["tool"]["const"] == "read_requirements"]
    assert len(reads) == 1 and "offset" not in reads[0]["required"]


@pytest.mark.parametrize("visible", [None, (1, 0), (2, 3)])
def test_saved_section_lengths_bound_offsets_without_removing_valid_navigation(visible):
    schema = action_schema(specification=True, requirement_lengths=[2, 3],
                           visible_requirement_page=visible)
    reads = [v for v in schema["oneOf"]
             if v["properties"]["tool"]["const"] == "read_requirements"]

    def allows(section, offset=None):
        return any(
            v["properties"]["requirement_id"]["const"] == section
            and (offset is not None or "offset" not in v["required"])
            and v["properties"]["offset"]["minimum"] <= (offset or 0)
            <= v["properties"]["offset"]["maximum"]
            for v in reads
        )

    for section, length in enumerate([2, 3], 1):
        for offset in range(-1, length + 2):
            assert allows(section, offset) == (
                0 <= offset <= length and (section, offset) != visible
            )
        assert allows(section) == ((section, 0) != visible)
    assert not allows(3, 0) and not allows(0, 0)
    assert any(v["properties"]["tool"]["const"] == "edit_file" for v in schema["oneOf"])
