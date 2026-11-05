"""Check acceptance-oracle integrity; these are not real-model completion results."""

import importlib.util
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from dsgpt.project_tools import ProjectAction, ProjectTools
from dsgpt.storage import Store
from dsgpt.work import WorkRegistry
from dsgpt.work_specs import sections

ROOT = Path(__file__).resolve().parents[1]


def script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


acceptance = script("live_complex_app_model")
fixture = script("complex_app_fixture")
native = script("check_complex_app_runtime")
joiner = script("check_complex_app_acceptance")


def test_long_request_is_lossless_and_keeps_final_delivery_constraints():
    text = (ROOT / "tests/fixtures/complex-app/request.txt").read_text()
    chunks = list(sections(text))
    assert len(text.encode()) > 9000 and len(chunks) >= 6
    assert "".join(chunk[2] for chunk in chunks) == text
    assert "both current APK and EXE exist" in "".join(chunk[2] for chunk in chunks[-2:])
    assert "雪" in text and "independent behavioral testing" in text


def test_acceptance_requires_new_state_instead_of_relabelling_resumed_old_task(tmp_path):
    with pytest.raises(ValueError, match="new state directory"):
        acceptance.run(SimpleNamespace(state=tmp_path), {})


def oracle_result(*, tests=16, failures=0, skipped=0, marker=True):
    body = (
        f'<testsuite tests="{tests}" failures="{failures}" errors="0" skipped="{skipped}">'
        + "".join(f'<testcase name="contract{index}"/>' for index in range(tests))
        + "</testsuite>"
    ).encode()
    return {
        "exit_code": 0,
        "stdout": "DSGPT_TASK_LEDGER_ORACLE_OK" if marker else "model claims success",
        "artifacts": [{"path": acceptance.ORACLE_XML, "content": body}],
    }


@pytest.mark.parametrize(
    "kwargs",
    [
        {"tests": 0},
        {"tests": 15},
        {"failures": 1},
        {"skipped": 1},
        {"marker": False},
    ],
)
def test_oracle_rejects_incomplete_or_failed_independent_execution(kwargs):
    with pytest.raises(AssertionError):
        acceptance.confirm_oracle(oracle_result(**kwargs), 16)


def test_oracle_does_not_accept_compiler_success_without_external_junit_report():
    result = oracle_result()
    result["artifacts"] = []
    with pytest.raises(AssertionError, match="suite report is missing"):
        acceptance.confirm_oracle(result, 16)
    assert acceptance.confirm_oracle(oracle_result(), 16)["kotlin_cases"] == 16


def test_repair_evidence_requires_real_compiler_error_before_success():
    initial = {"step": 2, "action": {"tool": "build_project"}, "result": {"exit_code": 0}}
    failure = {
        "step": 9,
        "action": {"tool": "build_project"},
        "result": {"execution_id": "failed-build", "stderr": "excerpt", "exit_code": 1},
    }
    success = {"step": 12, "action": {"tool": "build_project"}, "result": {"exit_code": 0}}
    full = {"failed-build": {"exit_code": 1, "stderr": "error: DSGPT_ACCEPTANCE_REPAIR"}}
    assert acceptance.repair_observed([initial, failure, success], 5, full) == {
        "failure_step": 9,
        "repaired_build_step": 12,
    }
    for history in ([success], [failure], [success, failure], [initial, success]):
        with pytest.raises(AssertionError):
            acceptance.repair_observed(history, 5, full)


def test_compiler_repair_check_survives_rejected_model_responses_without_counting_them():
    rejected = {
        "step": 8, "action": {"invalid_output": "incomplete JSON"},
        "result": {"error": "invalid_action"},
    }
    failed = {
        "step": 9, "action": {"tool": "build_project"},
        "result": {"exit_code": 1, "stderr": "error: DSGPT_ACCEPTANCE_REPAIR"},
    }
    passed = {"step": 11, "action": {"tool": "build_project"}, "result": {"exit_code": 0}}
    between = {**rejected, "step": 10}
    assert acceptance.repair_observed([rejected, failed, between, passed], 5) == {
        "failure_step": 9, "repaired_build_step": 11,
    }
    for history in ([rejected, passed], [failed, between], [rejected, between]):
        with pytest.raises(AssertionError, match="No actual marker compiler failure"):
            acceptance.repair_observed(history, 5)


def test_declared_user_fault_preserves_original_source_and_is_not_a_model_step(tmp_path):
    store = Store(tmp_path)
    work = WorkRegistry(store)
    task = work.create("Fixture", "Create both apps", build_target="apps")
    original = "int original_behavior() { return 42; }\n"
    with store.transaction() as db:
        ProjectTools.apply(
            db,
            task["id"],
            ProjectAction(
                tool="write_file", path="windows/main.cpp", content=original, summary="User fixture"
            ),
        )
    evidence = acceptance.inject_user_fault(store, task["id"])
    saved = store.one("SELECT content,sha256 FROM work_files WHERE task_id=?", (task["id"],))
    assert saved["content"] == original + acceptance.REPAIR_MARKER
    assert saved["sha256"] == evidence["after_sha256"]
    assert evidence["before_sha256"] == acceptance.digest(original)
    assert store.all("SELECT * FROM work_steps WHERE task_id=?", (task["id"],)) == []
    with pytest.raises(AssertionError):
        acceptance.inject_user_fault(store, task["id"])


def test_native_android_guard_refuses_physical_device_before_any_adb_call(tmp_path):
    args = SimpleNamespace(adb="does-not-exist", serial="PHYSICAL_DEVICE", package="irrelevant")
    with pytest.raises(ValueError, match="physical devices are refused"):
        native.Android(args, tmp_path)


@pytest.mark.parametrize("followup", [False, True])
def test_reviewed_portable_oracle_compiles_and_exercises_actual_domain(tmp_path, followup):
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("Native C++ compiler is not installed on this test host")
    project_id = "00000000-0000-0000-0000-000000000042"
    files = fixture.fixture(project_id, followup=followup)
    for name in ("windows/task_ledger.h", "windows/tests.cpp"):
        (tmp_path / Path(name).name).write_text(files[name])
    executable = tmp_path / "oracle"
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            str(tmp_path / "tests.cpp"),
            "-o",
            str(executable),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=10)
    expected = fixture.FOLLOWUP_ORACLE_CASE_COUNT if followup else fixture.ORACLE_CASE_COUNT
    assert result.returncode == 0, result.stderr
    assert f"DSGPT_TASK_LEDGER_TESTS={expected}" in result.stdout
    assert "DSGPT_TASK_LEDGER_ORACLE_OK" in result.stdout


def test_portable_external_oracle_detects_broken_completion_behavior(tmp_path):
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("Native C++ compiler is not installed on this test host")
    files = fixture.fixture("00000000-0000-0000-0000-000000000043")
    original = files["windows/task_ledger.h"]
    assert original.count("it->done=!it->done") == 1
    (tmp_path / "task_ledger.h").write_text(
        original.replace("it->done=!it->done", "it->done=false")
    )
    (tmp_path / "tests.cpp").write_text(files["windows/tests.cpp"])
    executable = tmp_path / "broken-oracle"
    subprocess.run(
        [compiler, "-std=c++17", str(tmp_path / "tests.cpp"), "-o", str(executable)],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert "DSGPT_TASK_LEDGER_ORACLE_OK" not in result.stdout


def complete_report_contract():
    """Synthetic input for testing the join validator, never written as acceptance evidence."""
    names = (
        "fresh-empty",
        "blank-title-rejected",
        "first-task-added",
        "second-task-added",
        "case-insensitive-search",
        "edit-keeps-id-and-other-task",
        "completion-counts",
        "done-filter",
        "active-filter",
        "first-process-restart-preserves-tasks",
        "restart-reloads-edited-fields",
        "delete-preserves-unselected-task",
        "deleted-id-not-reused",
        "second-process-restart-preserves-edits",
        "update-preserves-existing-data",
        "update-reloads-edited-fields",
        "clear-completed-keeps-active",
        "followup-restart-preserves-active",
        "followup-reloads-active-fields",
    )
    model = {
        "fresh_start": True,
        "single_backend_source_version": True,
        "model_workflow_passed": True,
        "status": "completed_model_and_compiler_checks",
        "overall_application_acceptance": "pending_native_ui_checks",
        "native_runtime_verified": False,
        "backend_restart": {"verified": True},
        "observed_compiler_repair": {"failure_step": 2},
        "phases": {
            phase: {
                "independent_tests": {"status": "passed"},
                "artifacts": [{"kind": kind, "sha256": kind + phase} for kind in ("apk", "exe")],
            }
            for phase in ("initial", "followup")
        },
    }
    native_reports = []
    for kind, platform in (("apk", "android"), ("exe", "windows")):
        native_reports.append(
            {
                "platform": platform,
                "passed": True,
                "initial_native_passed": True,
                "followup_native_passed": True,
                "initial_artifact": {"sha256": kind + "initial"},
                "updated_artifact": {"sha256": kind + "followup"},
                "checks": [{"name": name, "passed": True} for name in names],
            }
        )
    return model, *native_reports


def test_evidence_join_requires_matching_actual_artifacts_and_both_native_phases():
    model, android, windows = complete_report_contract()
    result = joiner.verify(model, android, windows)
    assert result["bounded_fixture_passed"] is True
    assert result["arbitrary_application_reliability_proven"] is False
    android["updated_artifact"]["sha256"] = "a different reviewed fixture"
    with pytest.raises(ValueError, match="different binaries"):
        joiner.verify(model, android, windows)


@pytest.mark.parametrize("missing", ["fresh", "oracle", "restart", "followup", "native_case"])
def test_evidence_join_never_promotes_missing_acceptance_to_success(missing):
    model, android, windows = complete_report_contract()
    if missing == "fresh":
        model["fresh_start"] = False
    elif missing == "oracle":
        model["phases"]["initial"]["independent_tests"]["status"] = "not_run"
    elif missing == "restart":
        model["backend_restart"]["verified"] = False
    elif missing == "followup":
        android["followup_native_passed"] = None
    elif missing == "native_case":
        windows["checks"].pop()
    with pytest.raises(ValueError):
        joiner.verify(model, android, windows)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "failed"),
        ("status", "running"),
        ("error", {"type": "RuntimeError", "message": "shutdown failed"}),
        ("cleanup_error", "shutdown interrupted"),
        ("overall_application_acceptance", "not_completed"),
        ("native_runtime_verified", True),
    ],
)
def test_evidence_join_rejects_contradictory_model_success(field, value):
    model, android, windows = complete_report_contract()
    model[field] = value
    assert model["model_workflow_passed"] is True
    with pytest.raises(ValueError, match="evidence is incomplete"):
        joiner.verify(model, android, windows)
