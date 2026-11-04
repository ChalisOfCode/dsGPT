"""Regressions for long specifications and checked app delivery, not model-quality claims."""

import base64
import hashlib
import io
import json
import zipfile
from dataclasses import replace

import httpx
import pytest

from dsgpt.builds import WorkBuilds, snapshot_hash
from dsgpt.config import Model
from dsgpt.inference import LocalInference, ollama_input_estimate
from dsgpt.project_tools import ProjectAction, ProjectTools
from dsgpt.sandbox import SandboxError
from dsgpt.scheduler import InferenceScheduler
from dsgpt.storage import Store, canonical, utcnow
from dsgpt.work import WorkRegistry
from dsgpt.work_specs import WorkSpecs, infer_target, sections


def setup(tmp_path, requirements="Build an Android APK counter app"):
    store = Store(tmp_path)
    model = Model("local", "Local", "ollama", "http://127.0.0.1:11434", "local")
    work = WorkRegistry(store, models={"local": model}, scheduler=InferenceScheduler(store))
    task = work.create("Counter", requirements, "local", build_target="auto")
    return store, work, task, replace(model, output_tokens=2048)


def write(db, task_id, path="main.cpp", body="int counter = 0;"):
    return ProjectTools.apply(
        db, task_id, ProjectAction(tool="write_file", summary="Implement", path=path, content=body)
    )


def reviewed(store, task_id):
    with store.transaction() as db:
        db.execute(
            "UPDATE work_spec_sections SET notes='Keep behavior and recovery' WHERE task_id=?",
            (task_id,),
        )
        db.execute(
            (
                "UPDATE work_specs SET brief='Counter with reset, persistence and "
                "tests' WHERE task_id=?"
            ),
            (task_id,),
        )


@pytest.mark.parametrize("length", [56600, 135000, 1500000])
def test_long_unicode_specification_is_lossless_and_bounded(length):
    text = ("Keep all constraints. 🏁 العربية 日本語\n\n" * (length // 20 + 1))[
        :length
    ] + "\nFINAL: preserve settings."
    parts = list(sections(text))
    assert "".join(p[2] for p in parts) == text
    assert all(len(body.encode()) <= 1600 and end > start for start, end, body in parts)
    assert all(parts[i][1] == parts[i + 1][0] for i in range(len(parts) - 1))
    assert parts[-1][2].endswith("preserve settings.")


@pytest.mark.parametrize(
    "prompt,target",
    [
        ("Build an Android app", "apk"),
        ("Make a Windows desktop app", "exe"),
        ("Deliver APK and EXE files", "apps"),
        ("Make a notes document", "files"),
        ("Need an APK with an accompanying Windows program", "apps"),
    ],
)
def test_natural_language_targets(prompt, target):
    assert infer_target(prompt) == target


def test_stale_edits_and_ambiguous_repairs_cannot_destroy_file(tmp_path):
    store, _, task, _ = setup(tmp_path)
    with store.transaction() as db:
        result = write(db, task["id"], body="one one\nunique broken\nkeep me\n")

        def edit(old, new, digest=result["sha256"]):
            return ProjectTools.apply(
                db,
                task["id"],
                ProjectAction(
                    tool="edit_file",
                    path="main.cpp",
                    old_text=old,
                    new_text=new,
                    expected_sha256=digest,
                    summary="Repair",
                ),
            )

        assert edit("one", "two")["error"] == "edit_match_not_unique"
        assert (
            edit("unique broken", "fixed", "0" * 64)["error"]
            == "file_changed_read_before_overwrite"
        )
        fixed = edit("unique broken", "unique fixed")
        assert "error" not in fixed
        assert (
            db.execute("SELECT content FROM work_files").fetchone()[0]
            == "one one\nunique fixed\nkeep me\n"
        )
        assert "error" in edit("unique fixed", "new")


def test_coverage_requires_real_files_and_invalidates_on_source_change(tmp_path):
    store, _, task, _ = setup(tmp_path)
    reviewed(store, task["id"])
    with store.transaction() as db:
        action = ProjectAction(
            tool="mark_requirement",
            summary="Review",
            requirement_id=1,
            content="Counter behavior checked in implementation and tests",
            evidence_paths=["main.cpp"],
        )
        assert "error" in WorkSpecs.coverage(db, task["id"], action)
        write(db, task["id"])
        result = WorkSpecs.coverage(db, task["id"], action)
        assert WorkSpecs.finish_state(db, task["id"], result["snapshot_sha256"])["ready"]
        write(db, task["id"], "tests.cpp", "int main() {return 0;}")
        current = snapshot_hash([dict(r) for r in db.execute("SELECT path,sha256 FROM work_files")])
        assert not WorkSpecs.finish_state(db, task["id"], current)["ready"]
    again = Store(tmp_path)
    assert again.one("SELECT evidence FROM work_spec_sections")["evidence"].startswith(
        "Counter behavior"
    )


def test_long_prompt_context_pages_results_instead_of_replaying_full_spec(tmp_path):
    requirements = "Build an Android APK.\n" + "Specific feature and recovery requirement.\n" * 1500
    store, work, task, model = setup(tmp_path, requirements)
    reviewed(store, task["id"])
    with store.transaction() as db:
        for n in range(32):
            write(db, task["id"], f"source/file{n}.kt", "code " * 1000)
        db.execute(
            "INSERT INTO work_steps VALUES(?,?,?,?,?)",
            (
                task["id"],
                1,
                canonical({"tool": "read_file", "path": "source/file0.kt", "summary": "Read"}),
                canonical(
                    {
                        "path": "source/file0.kt",
                        "content": "exact source " * 1000,
                        "offset": 0,
                        "next_offset": 13000,
                        "sha256": "a" * 64,
                    }
                ),
                utcnow(),
            ),
        )
    messages = work._prompt(task, task["session"], model, [])
    assert ollama_input_estimate(messages) + model.output_tokens <= model.context
    assert requirements not in canonical(messages)
    assert store.one("SELECT requirements FROM work_tasks")["requirements"] == requirements
    assert "read_requirements" in canonical(messages)
    assert len(messages) == 4, "Coding turn must retain usable paged tool results"
    result = json.loads(messages[-1]["content"].split(": ", 1)[1])
    assert result["content"] and result["next_offset"] == len(result["content"])


async def test_every_section_is_read_before_build_setup_and_restart_resumes(tmp_path):
    text = "Build an APK.\n" + "must preserve setting X\n" * 130 + "FINAL: recover after disconnect"
    store, work, task, model = setup(tmp_path, text)
    parts = list(sections(text))

    class Reader:
        seen = []

        async def stream(self, model, messages, response_schema=None):
            assert ollama_input_estimate(messages) + model.output_tokens <= model.context
            self.seen.append(json.loads(messages[1]["content"])["original_text"])
            yield {
                "kind": "delta",
                "data": {
                    "text": canonical(
                        {
                            "brief": "APK with persistence",
                            "section_notes": "Preserve exact requirements",
                        }
                    )
                },
            }

    reader = work.inference = Reader()
    with store.transaction() as db:
        db.execute("UPDATE work_tasks SET status='queued' WHERE id=?", (task["id"],))
    for i in range(len(parts)):
        if i == 1:
            work = WorkRegistry(
                Store(tmp_path),
                models={"local": model},
                inference=reader,
                scheduler=InferenceScheduler(store),
            )
        await work._step(work.store.one("SELECT * FROM work_tasks WHERE id=?", (task["id"],)))
    assert "".join(reader.seen) == text
    assert work.specs.pending_review(task["id"]) is None
    assert work.store.all("SELECT * FROM work_executions") == []


def test_revision_keeps_source_but_restarts_spec_review_and_expands_deliverables(tmp_path):
    store, work, task, _ = setup(tmp_path)
    reviewed(store, task["id"])
    with store.transaction() as db:
        write(db, task["id"])
    updated = work.revise(
        task["id"],
        task["revision"],
        note="Also deliver a Windows EXE.\n" + "Followup detail.\n" * 2000,
    )
    assert work.specs.pending_review(task["id"])
    assert store.one("SELECT content FROM work_files")["content"] == "int counter = 0;"
    assert store.one("SELECT target FROM work_build_profiles")["target"] == "apps"
    assert "Followup detail." in updated["requirements"]


def test_real_v22_upgrade_keeps_profile_data_and_backup(tmp_path):
    store, _, task, _ = setup(tmp_path)
    with store.transaction() as db:
        for table in (
            "device_presence",
            "work_uploads",
            "work_web_calls",
            "work_spec_sections",
            "work_specs",
            "work_signing_keys",
        ):
            db.execute("DROP TABLE " + table)
        db.execute("ALTER TABLE work_build_profiles RENAME TO old_profiles")
        db.execute(
            "CREATE TABLE work_build_profiles(task_id TEXT PRIMARY KEY "
            "REFERENCES work_tasks(id), target TEXT NOT NULL CHECK(target IN "
            "('files','apk','exe')))"
        )
        db.execute("INSERT INTO work_build_profiles SELECT * FROM old_profiles")
        db.execute("DROP TABLE old_profiles")
        db.execute("PRAGMA user_version=22")
    migrated = Store(tmp_path)
    assert migrated.one("SELECT target FROM work_build_profiles")["target"] == "apk"
    assert (
        migrated.one("SELECT requirements FROM work_tasks")["requirements"] == task["requirements"]
    )
    assert not migrated.all("PRAGMA foreign_key_check")
    assert len(list(tmp_path.glob("before-v22-to-v25-*.db"))) == 1


def artifact(path, content):
    return {"path": path, "content": content, "sha256": hashlib.sha256(content).hexdigest()}


def fake_apk():
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as z:
        z.writestr("AndroidManifest.xml", b"fixture, not a compiled apk")
        z.writestr("classes.dex", b"fixture")
    return data.getvalue()


def app_artifacts():
    apk = artifact("dist/app.apk", fake_apk())
    report = {
        "format": "dsgpt-app-build-v1",
        "checks": {
            "android": {
                "unit_tests": 2,
                "lint_passed": True,
                "signature_verified": True,
                "native_runtime_verified": False,
            }
        },
        "artifacts": {"app.apk": apk["sha256"]},
    }
    return [apk, artifact("dist/build-report.json", canonical(report).encode())]


@pytest.mark.parametrize("damage", ["hash", "tests", "native"])
def test_build_receipts_reject_wrong_artifacts_or_missing_checks(damage):
    values = app_artifacts()
    report = json.loads(values[1]["content"])
    if damage == "hash":
        report["artifacts"]["app.apk"] = "0" * 64
    if damage == "tests":
        report["checks"]["android"]["unit_tests"] = 0
    if damage == "native":
        report["checks"]["android"]["native_runtime_verified"] = True
    values[1] = artifact("dist/build-report.json", canonical(report).encode())
    with pytest.raises(SandboxError):
        WorkBuilds.validate_app_report(values, "apk")


async def test_signing_reuses_private_key_only_in_separate_clean_guest(tmp_path):
    store, work, task, _ = setup(tmp_path)

    class Signer:
        calls = []

        async def execute(self, identifier, files, argv, outputs, timeout, **kwargs):
            self.calls.append(files)
            assert all(f["path"] in {"input-apk.b64", "input-key.b64"} for f in files)
            if len(self.calls) > 1:
                key = next(f for f in files if f["path"] == "input-key.b64")
                assert base64.b64decode(key["content"]) == b"PRIVATE PROJECT KEY"
            return {
                "exit_code": 0,
                "artifacts": [
                    artifact("signed.apk", fake_apk()),
                    artifact("signing.p12", b"PRIVATE PROJECT KEY"),
                    artifact(
                        "signing-report.json",
                        canonical(
                            {
                                "signature_verified": True,
                                "certificate_sha256": "a" * 64,
                                "signing_identity": "project_persistent_development",
                                "native_runtime_verified": False,
                            }
                        ).encode(),
                    ),
                ],
            }

    signer = work.builds.sandbox = Signer()
    for _ in range(2):
        artifacts, report = await work.builds.sign_apk(task["id"], "fixture", app_artifacts())
        assert all(
            "signing.p12" != a["path"] and b"PRIVATE PROJECT KEY" not in a["content"]
            for a in artifacts
        )
    assert len(signer.calls[0]) == 1 and len(signer.calls[1]) == 2
    assert len(store.all("SELECT * FROM work_signing_keys")) == 1


async def test_ollama_stays_warm_and_releases_only_its_previous_model():
    calls = []

    def respond(request):
        body = json.loads(request.content) if request.content else {}
        if request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={
                    "models": [{"name": name, "size": 100, "digest": "abc"} for name in ("a", "b")]
                },
            )
        if request.url.path == "/api/show":
            return httpx.Response(
                200,
                json={"model_info": {"architecture": "fixture"}, "capabilities": ["completion"]},
            )
        calls.append((request.url.path, body))
        return httpx.Response(
            200, text=canonical({"message": {"content": "done"}, "done": True}) + "\n"
        )

    adapter = LocalInference(httpx.MockTransport(respond))
    first = Model("a", "A", "ollama", "http://127.0.0.1:11434", "a")
    for model in (first, first, replace(first, id="b", runtime_model="b")):
        assert [e async for e in adapter.stream(model, [{"role": "user", "content": "build"}])]
    assert [p for p, _ in calls] == ["/api/chat", "/api/chat", "/api/generate", "/api/chat"]
    assert calls[2][1] == {"model": "a", "keep_alive": 0, "stream": False}
    assert all(body["keep_alive"] == "5m" for path, body in calls if path == "/api/chat")


async def test_attached_image_is_reviewed_separately_and_saved_as_source_notes(tmp_path):
    store, work, task, model = setup(tmp_path)
    seen = []

    class Vision:
        async def stream(self, model, messages, response_schema=None):
            seen.append(messages)
            assert ollama_input_estimate(messages) + model.output_tokens <= model.context
            yield {
                "kind": "delta",
                "data": {
                    "text": canonical(
                        {
                            "brief": "Visible counter layout",
                            "section_notes": "Two buttons labeled Add one and Reset.",
                        }
                    )
                },
            }

    work.inference = Vision()
    with store.transaction() as db:
        db.execute(
            "INSERT INTO work_inputs VALUES(?,?,?,?,?)",
            (task["id"], "screen.png", b"fixture pixels", "f" * 64, '{"image":true}'),
        )
        db.execute("UPDATE work_tasks SET status='queued' WHERE id=?", (task["id"],))
    assert await work._review_input_image(task)
    assert not await work._review_input_image(task)
    assert len(seen) == 1 and seen[0][1]["images"] == [base64.b64encode(b"fixture pixels").decode()]
    assert "Two buttons" in store.one("SELECT content FROM work_files")["content"]


def test_checked_build_and_all_requested_formats_are_required_for_finish(tmp_path):
    store, work, task, _ = setup(tmp_path, "Deliver Android APK and Windows EXE")
    reviewed(store, task["id"])
    with store.transaction() as db:
        write(db, task["id"])
        digest = snapshot_hash([dict(r) for r in db.execute("SELECT path,sha256 FROM work_files")])
        for step, kind, verification in [(1, "apk", None), (2, "exe", {"checks": {"windows": {}}})]:
            db.execute(
                "INSERT INTO work_executions(id,task_id,step,action,snapshot_sha256,status,result,"
                "cleanup_pending,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    str(step),
                    task["id"],
                    step,
                    "{}",
                    digest,
                    "completed",
                    canonical(
                        {
                            "artifacts": [{"id": str(step), "kind": kind}],
                            "verification": verification,
                        }
                    ),
                    0,
                    utcnow(),
                    utcnow(),
                ),
            )
        assert WorkBuilds.finish_evidence(db, task["id"], "apps") is None
        db.execute(
            "UPDATE work_executions SET result=? WHERE id=?",
            (
                canonical(
                    {
                        "artifacts": [{"id": "apk", "kind": "apk"}],
                        "verification": {"checks": {"android": {}}},
                    }
                ),
                "1",
            ),
        )
        assert {
            a["kind"] for a in WorkBuilds.finish_evidence(db, task["id"], "apps")["artifacts"]
        } == {"apk", "exe"}
        db.execute("UPDATE work_executions SET status='failed' WHERE id='2'")
        assert WorkBuilds.finish_evidence(db, task["id"], "apps") is None


def test_guided_agent_cannot_replace_existing_file_from_an_invented_body(tmp_path):
    store, work, task, _ = setup(tmp_path)
    with store.transaction() as db:
        original = write(db, task["id"], body="int n = 0\nint keep(int x) { return x; }\n")
        db.execute("UPDATE work_tasks SET status='running' WHERE id=?", (task["id"],))
    action = ProjectAction(
        tool="write_file",
        path="main.cpp",
        content="int n = 0;",
        expected_sha256=original["sha256"],
        summary="Bad wholesale repair",
    )
    work._commit(task["id"], task["session"], action)
    assert store.one("SELECT content FROM work_files")["content"].endswith(
        "int keep(int x) { return x; }\n"
    )
    assert (
        json.loads(store.one("SELECT result FROM work_steps")["result"])["error"]
        == "existing_file_requires_targeted_edit"
    )


def test_unicode_review_overview_stays_within_small_model_context(tmp_path):
    store, work, task, model = setup(tmp_path, "Build an APK. " + "界" * 6000)
    with store.transaction() as db:
        db.execute("UPDATE work_specs SET brief=?", ("界" * 1000,))
    messages = work.specs.review_messages(task, work.specs.pending_review(task["id"]))
    assert ollama_input_estimate(messages) + model.output_tokens <= model.context


def test_read_after_each_repair_is_progress_not_a_repeated_stale_read(tmp_path):
    store, work, task, _ = setup(tmp_path)
    with store.transaction() as db:
        write(db, task["id"])
    for revision in range(3):
        with store.transaction() as db:
            body = f"int counter = {revision};"
            db.execute(
                "UPDATE work_files SET content=?,sha256=? WHERE task_id=?",
                (body, hashlib.sha256(body.encode()).hexdigest(), task["id"]),
            )
            db.execute("UPDATE work_tasks SET status='running' WHERE id=?", (task["id"],))
        work._commit(
            task["id"],
            work.get(task["id"])["session"],
            ProjectAction(tool="read_file", path="main.cpp", summary="Inspect repaired source"),
        )
    assert work.get(task["id"])["status"] == "queued"
    assert len(store.all("SELECT * FROM work_steps")) == 3


def test_completion_guidance_requires_coverage_and_requested_build_receipts(tmp_path):
    store, work, app, model = setup(tmp_path)
    source = work.create("Repair source", "Repair main.cpp", "local", build_target="source")
    with store.transaction() as db:
        work.specs.initialize(db, source["id"], source["requirements"])
    for task in (app, source):
        reviewed(store, task["id"])
        with store.transaction() as db:
            write(db, task["id"])
            WorkSpecs.coverage(
                db,
                task["id"],
                ProjectAction(
                    tool="mark_requirement",
                    requirement_id=1,
                    summary="Review saved code",
                    content="The saved source meets this section; device behavior is untested.",
                    evidence_paths=["main.cpp"],
                ),
            )

    def next_step(task):
        current = work.get(task["id"])
        return json.loads(work._prompt(current, current["session"], model, [])[1]["content"])[
            "next_step"
        ]

    assert "Call finish now" in next_step(source)
    assert "appropriate build/export command" in next_step(app)
    assert "Call finish now" not in next_step(app)
    with store.transaction() as db:
        write(db, source["id"], "additional.cpp", "int new_behavior = 1;")
    assert "Call finish now" not in next_step(source)
    assert "mark_requirement" in next_step(source)
