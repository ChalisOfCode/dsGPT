"""Later requirements remain discoverable without evicting current tool evidence."""

import copy
import json
from dataclasses import replace

from test_work_inline_original import setup

from dsgpt.inference import ollama_input_estimate


def prepared(tmp_path):
    original = "".join(f"Section {n}: " + "preserve café and 雪. " * 70 + "\n\n" for n in range(12))
    store, work, tid = setup(tmp_path, original)
    with store.transaction() as db:
        db.execute(
            "UPDATE work_spec_sections SET notes='Domain API contracts, types and validation' "
            "WHERE task_id=?", (tid,),
        )
    model = replace(work.models["local"], context=16384, output_tokens=4096)
    row = store.one("SELECT * FROM work_tasks WHERE id=?", (tid,))
    session = store.one("SELECT * FROM work_sessions WHERE task_id=?", (tid,))
    return store, work, tid, model, work._guided_prompt(row, session, model, [])


def test_navigation_keeps_original_and_exposes_later_section_ids_with_paging(tmp_path):
    store, work, tid, model, messages = prepared(tmp_path)
    requirements = json.loads(messages[1]["content"])["requirements"]
    nav = requirements["navigation"]
    assert [s["id"] for s in nav["sections"]] == list(range(1, 9))
    assert nav["next_offset"] == 8 and nav["has_more"]
    assert nav["previous_offset"] is None
    assert "not authoritative requirements" in nav["usage"]
    assert all(s["status"] == "pending" for s in nav["sections"])
    assert ollama_input_estimate(messages) + model.output_tokens <= model.context
    with store.connect() as db:
        all_sections = db.execute(
            "SELECT ordinal FROM work_spec_sections WHERE task_id=? ORDER BY ordinal", (tid,)
        ).fetchall()
        restored = "".join(work.specs.read(db, tid, s[0])["content"] for s in all_sections)
    assert restored == store.one("SELECT requirements FROM work_tasks WHERE id=?", (tid,))[
        "requirements"
    ]


def test_navigation_is_optional_and_cannot_displace_a_tool_result(tmp_path):
    _, work, tid, model, messages = prepared(tmp_path)
    context = json.loads(messages[1]["content"])
    del context["requirements"]["navigation"]
    messages[1]["content"] = json.dumps(context)
    messages += [
        {"role": "assistant", "content": '{"tool":"read_file","path":"current.py"}'},
        {"role": "user", "content": "Recorded tool result: exact source bytes and diagnostic"},
    ]
    original = copy.deepcopy(messages)
    tight = replace(model, context=ollama_input_estimate(messages) + model.output_tokens)
    assert work._with_requirement_navigation(messages, tid, tight) == original
    expanded = work._with_requirement_navigation(messages, tid, model)
    assert expanded[2:] == original[2:]
    assert messages == original
    assert ollama_input_estimate(expanded) + model.output_tokens <= model.context


def test_navigation_tracks_current_requirement_page_without_cross_task_notes(tmp_path):
    store, work, tid, model, messages = prepared(tmp_path)
    other = work.create("Unrelated", "Private unrelated requirements", "local")
    with store.transaction() as db:
        work.specs.initialize(db, other["id"], other["requirements"])
        db.execute(
            "UPDATE work_spec_sections SET notes='FOREIGN_PRIVATE_NOTE' WHERE task_id=?",
            (other["id"],),
        )
    context = json.loads(messages[1]["content"])
    del context["requirements"]["navigation"]
    context["requirements"]["current_section"]["requirement_id"] = 9
    messages[1]["content"] = json.dumps(context)
    expanded = work._with_requirement_navigation(messages, tid, model)
    nav = json.loads(expanded[1]["content"])["requirements"]["navigation"]
    assert nav["offset"] == 8 and nav["previous_offset"] == 0
    assert nav["sections"][0]["id"] == 9
    assert "FOREIGN_PRIVATE_NOTE" not in json.dumps(expanded)
