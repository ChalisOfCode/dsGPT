"""A short original can be read with a real action; it never supplies coverage evidence."""

import asyncio
import json
from dataclasses import replace

import pytest

from dsgpt.builds import snapshot_hash
from dsgpt.config import Model
from dsgpt.inference import InferenceError, ollama_input_estimate
from dsgpt.project_tools import ProjectAction
from dsgpt.scheduler import InferenceScheduler
from dsgpt.storage import Store, canonical
from dsgpt.work import WorkRegistry
from dsgpt.work_specs import SpecReview, WorkSpecs


def setup(
    tmp_path, original="Keep every caption. Do not shorten names: café 日本語 🏁.", context=16384
):
    store = Store(tmp_path)
    model = Model(
        "local",
        "Local",
        "ollama",
        "http://127.0.0.1:11434",
        "local",
        context=context,
        output_tokens=512,
    )
    work = WorkRegistry(store, models={model.id: model}, scheduler=InferenceScheduler(store))
    task = work.create("Caption task", original, model.id, start=True)
    with store.transaction() as db:
        work.specs.initialize(db, task["id"], original)
    return store, work, task["id"]


class Inference:
    def __init__(self, value=None, mutation=None, failure=None):
        self.value = (
            value
            if value is not None
            else {
                "tool": "write_file",
                "path": "notes.txt",
                "content": "Actual fixture output",
                "summary": "Save actual fixture output",
            }
        )
        self.calls = []
        self.mutation, self.failure = mutation, failure

    async def stream(self, model, messages, response_schema=None):
        self.calls.append((messages, response_schema))
        if self.mutation:
            self.mutation()
        if self.failure:
            yield {"kind": "delta", "data": {"text": '{"tool":"write_file",'}}
            raise self.failure
        if self.value != "":
            text = self.value if isinstance(self.value, str) else canonical(self.value)
            yield {"kind": "delta", "data": {"text": text}}


async def step(work, tid):
    await work._step(work.store.one("SELECT * FROM work_tasks WHERE id=?", (tid,)))


def section(store, tid):
    return store.one("SELECT * FROM work_spec_sections WHERE task_id=?", (tid,))


@pytest.mark.parametrize("original", ["Do not drop names.\nKeep café, 日本語 and 🏁.", "界" * 300])
async def test_one_real_action_reads_exact_small_original_without_synthetic_step(
    tmp_path, original
):
    store, work, tid = setup(tmp_path, original)
    inference = work.inference = Inference()
    assert section(store, tid)["notes"] is None
    await step(work, tid)
    assert len(inference.calls) == 1
    messages, schema = inference.calls[0]
    assert "oneOf" in schema and schema != SpecReview.model_json_schema()
    context = json.loads(messages[1]["content"])
    assert context["requirements"]["current_section"]["content"] == original
    assert "no separate read_requirements needed" in context["requirements"]["full_text"]
    assert "Coverage and artifact checks still apply" in context["requirements"]["full_text"]
    steps = store.all("SELECT action FROM work_steps WHERE task_id=?", (tid,))
    assert [json.loads(row["action"])["tool"] for row in steps] == ["write_file"]
    assert store.one("SELECT step FROM work_sessions WHERE task_id=?", (tid,))["step"] == 1
    saved = section(store, tid)
    assert saved["notes"] == "Original supplied verbatim with the model action:\n" + original
    assert store.one("SELECT brief FROM work_specs WHERE task_id=?", (tid,))["brief"] == original
    assert saved["status"] == "pending" and saved["evidence_paths"] is None
    assert saved["snapshot_sha256"] is None and not work._completion_ready(tid)
    with store.connect() as db:
        files = [dict(r) for r in db.execute("SELECT path,sha256 FROM work_files")]
        assert not WorkSpecs.finish_state(db, tid, snapshot_hash(files))["ready"]


@pytest.mark.parametrize("kind", ["empty", "invalid", "cancel", "runtime_error"])
async def test_unfinished_model_response_never_acknowledges_original(tmp_path, kind):
    store, work, tid = setup(tmp_path)
    work.inference = Inference(
        value="" if kind == "empty" else "{" if kind == "invalid" else None,
        failure=asyncio.CancelledError()
        if kind == "cancel"
        else InferenceError("runtime_unavailable")
        if kind == "runtime_error"
        else None,
    )
    if kind == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await step(work, tid)
    else:
        await step(work, tid)
    assert section(store, tid)["notes"] is None
    assert store.one("SELECT brief FROM work_specs WHERE task_id=?", (tid,))["brief"] == ""
    assert store.all("SELECT path FROM work_files WHERE task_id=?", (tid,)) == []
    steps = store.all("SELECT action FROM work_steps WHERE task_id=?", (tid,))
    assert len(steps) == (1 if kind == "invalid" else 0)
    assert all(json.loads(row["action"]).get("tool") != "review_specification" for row in steps)


@pytest.mark.parametrize("mutation", ["requirements", "digest_only", "paused", "stopped"])
async def test_changed_or_cancelled_task_cannot_acknowledge_or_execute_old_action(
    tmp_path, mutation
):
    store, work, tid = setup(tmp_path)

    def change():
        with store.transaction() as db:
            if mutation == "requirements":
                text = "Changed requirement; the old action must not run."
                db.execute("UPDATE work_tasks SET requirements=? WHERE id=?", (text, tid))
                work.specs.initialize(db, tid, text)
            elif mutation == "digest_only":
                db.execute("UPDATE work_specs SET requirements_sha256=?", ("0" * 64,))
            else:
                db.execute("UPDATE work_tasks SET status=? WHERE id=?", (mutation, tid))

    work.inference = Inference(mutation=change)
    await step(work, tid)
    assert section(store, tid)["notes"] is None
    assert store.all("SELECT path FROM work_files WHERE task_id=?", (tid,)) == []
    assert store.all("SELECT action FROM work_steps WHERE task_id=?", (tid,)) == []
    status = store.one("SELECT status FROM work_tasks WHERE id=?", (tid,))["status"]
    assert status == (mutation if mutation in {"paused", "stopped"} else "queued")


async def test_context_fallback_uses_existing_review_and_never_acknowledges_missing_text(tmp_path):
    store, work, tid = setup(tmp_path, context=2048)
    row = store.one("SELECT * FROM work_tasks WHERE id=?", (tid,))
    session = store.one("SELECT * FROM work_sessions WHERE task_id=?", (tid,))
    candidate = work.specs.inline_original(row, work.specs.pending_review(tid))
    prompt = work._prompt(row, session, work.models["local"])
    assert not work.specs.original_in_prompt(prompt, candidate)
    assert (
        "no separate read_requirements needed"
        not in json.loads(prompt[1]["content"])["requirements"]["full_text"]
    )
    review = {"brief": "Original navigation summary", "section_notes": "Actual model review"}
    inference = work.inference = Inference(review)
    await step(work, tid)
    assert len(inference.calls) == 1
    messages, schema = inference.calls[0]
    assert schema == SpecReview.model_json_schema()
    assert ollama_input_estimate(messages) + work.models["local"].output_tokens <= 2048
    assert json.loads(messages[1]["content"])["original_text"] == row["requirements"]
    assert section(store, tid)["notes"] == review["section_notes"]
    action = json.loads(
        store.one("SELECT action FROM work_steps WHERE task_id=?", (tid,))["action"]
    )
    assert action["tool"] == "review_specification"
    assert store.all("SELECT path FROM work_files WHERE task_id=?", (tid,)) == []


async def test_hint_cannot_overflow_an_exact_fit_final_prompt(tmp_path, monkeypatch):
    store, work, tid = setup(tmp_path)
    original_context = work.specs.context

    def shorter_navigation(task_id, snapshot):
        context = original_context(task_id, snapshot)
        context["full_text"] = "Read."
        return context

    monkeypatch.setattr(work.specs, "context", shorter_navigation)
    row = store.one("SELECT * FROM work_tasks WHERE id=?", (tid,))
    session = store.one("SELECT * FROM work_sessions WHERE task_id=?", (tid,))
    roomy = work._prompt(row, session, work.models["local"])
    without_hint = json.loads(roomy[1]["content"])
    without_hint["requirements"]["full_text"] = "Read."
    before = [roomy[0], {**roomy[1], "content": canonical(without_hint)}, *roomy[2:]]
    budget = ollama_input_estimate(before) + work.models["local"].output_tokens
    assert ollama_input_estimate(roomy) + work.models["local"].output_tokens > budget
    work.models["local"] = replace(work.models["local"], context=budget)
    final = work._prompt(row, session, work.models["local"])
    assert ollama_input_estimate(final) + work.models["local"].output_tokens == budget
    requirements = json.loads(final[1]["content"])["requirements"]
    assert requirements["full_text"] == "Read."
    assert requirements["current_section"]["content"] == row["requirements"]
    candidate = work.specs.inline_original(row, work.specs.pending_review(tid))
    assert work.specs.original_in_prompt(final, candidate)
    assert section(store, tid)["notes"] is None


async def test_same_original_new_running_revision_rejects_stale_model_action(tmp_path):
    store, work, tid = setup(tmp_path)
    original = store.one("SELECT requirements FROM work_tasks WHERE id=?", (tid,))["requirements"]
    newer = {}

    def pause_revise_resume():
        current = store.one("SELECT revision FROM work_tasks WHERE id=?", (tid,))
        paused = work.transition(tid, "pause", current["revision"])
        work.revise(tid, paused["revision"], web_mode="on", resume=True)
        # A later worker owns this running revision. The old response must neither
        # acknowledge/execute nor requeue that different turn.
        with store.transaction() as db:
            db.execute(
                "UPDATE work_tasks SET status='running',revision=revision+1 WHERE id=?", (tid,)
            )
            newer["revision"] = db.execute(
                "SELECT revision FROM work_tasks WHERE id=?", (tid,)
            ).fetchone()[0]

    work.inference = Inference(mutation=pause_revise_resume)
    await step(work, tid)
    current = store.one("SELECT * FROM work_tasks WHERE id=?", (tid,))
    assert current["requirements"] == original
    assert current["status"] == "running" and current["revision"] == newer["revision"]
    assert section(store, tid)["notes"] is None
    assert store.all("SELECT path FROM work_files WHERE task_id=?", (tid,)) == []
    assert store.all("SELECT action FROM work_steps WHERE task_id=?", (tid,)) == []


@pytest.mark.parametrize("original", ["a" * 901, "界" * 301, "a" * 1700])
async def test_long_or_multisection_original_still_uses_separate_review(tmp_path, original):
    store, work, tid = setup(tmp_path, original)
    inference = work.inference = Inference({"brief": "Navigation", "section_notes": "Read section"})
    await step(work, tid)
    assert len(inference.calls) == 1
    assert inference.calls[0][1] == SpecReview.model_json_schema()
    assert store.all("SELECT path FROM work_files WHERE task_id=?", (tid,)) == []


async def test_inline_read_does_not_weaken_evidence_or_finish_gates(tmp_path):
    store, work, tid = setup(tmp_path)
    work.inference = Inference()
    await step(work, tid)
    work.inference = Inference({"tool": "finish", "summary": "Attempt finish without coverage"})
    await step(work, tid)
    assert store.one("SELECT status FROM work_tasks WHERE id=?", (tid,))["status"] == "queued"
    result = json.loads(
        store.one(
            "SELECT result FROM work_steps WHERE task_id=? ORDER BY step DESC LIMIT 1", (tid,)
        )["result"]
    )
    assert result["error"] == "requirements_review_required"
    with store.transaction() as db:
        result = WorkSpecs.coverage(
            db,
            tid,
            ProjectAction(
                tool="mark_requirement",
                requirement_id=1,
                content="Claim",
                summary="Claim",
                evidence_paths=["receipts/missing.srt"],
            ),
        )
    assert result["error"] == "coverage_requires_current_project_files_or_receipts"


async def test_real_revision_invalidates_inline_read_and_preserves_existing_files(tmp_path):
    store, work, tid = setup(tmp_path)
    work.inference = Inference()
    await step(work, tid)
    row = store.one("SELECT * FROM work_tasks WHERE id=?", (tid,))
    paused = work.transition(tid, "pause", row["revision"])
    updated = work.revise(tid, paused["revision"], note="Also keep every timestamp.", resume=True)
    assert section(store, tid)["notes"] is None
    assert store.one("SELECT content FROM work_files WHERE task_id=?", (tid,))["content"]
    inference = work.inference = Inference({"tool": "list_files", "summary": "Read current files"})
    await step(work, tid)
    assert len(inference.calls) == 1
    assert (
        json.loads(inference.calls[0][0][1]["content"])["requirements"]["current_section"][
            "content"
        ]
        == updated["requirements"]
    )
    assert section(store, tid)["notes"].endswith(updated["requirements"])
