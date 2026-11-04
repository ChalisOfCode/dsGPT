"""Join actual-model and native-runtime evidence for the same Task Ledger binaries."""

import argparse
import hashlib
import json
from pathlib import Path


def verify(model, android, windows):
    if not (
        model.get("model_workflow_passed") is True
        and model.get("status") == "completed_model_and_compiler_checks"
        and model.get("overall_application_acceptance") == "pending_native_ui_checks"
        and model.get("native_runtime_verified") is False
        and not model.get("error")
        and not model.get("cleanup_error")
        and model.get("fresh_start") is True
        and model.get("single_backend_source_version") is True
        and model.get("backend_restart", {}).get("verified") is True
        and model.get("observed_compiler_repair")
    ):
        raise ValueError("Fresh same-version model build/repair/restart evidence is incomplete")
    phases = model.get("phases", {})
    for phase in ("initial", "followup"):
        if phases.get(phase, {}).get("independent_tests", {}).get("status") != "passed":
            raise ValueError("Independent generated-code behavior tests are missing: " + phase)
    required = {
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
    }
    for kind, platform, native in (("apk", "android", android), ("exe", "windows", windows)):
        if not (
            native.get("platform") == platform
            and native.get("passed") is True
            and native.get("initial_native_passed") is True
            and native.get("followup_native_passed") is True
            and not native.get("error")
            and not native.get("cleanup_error")
        ):
            raise ValueError("Native initial/update acceptance did not pass: " + platform)
        checks = native.get("checks", [])
        if (
            not checks
            or any(item.get("passed") is not True for item in checks)
            or not required.issubset({item.get("name") for item in checks})
        ):
            raise ValueError("Required native scenarios were not observed: " + platform)
        for phase, field in (("initial", "initial_artifact"), ("followup", "updated_artifact")):
            artifacts = [
                item for item in phases[phase].get("artifacts", []) if item["kind"] == kind
            ]
            if len(artifacts) != 1 or artifacts[0]["sha256"] != native.get(field, {}).get("sha256"):
                raise ValueError(
                    "Native evidence belongs to different binaries: " + platform + "/" + phase
                )
    return {
        "format": "dsgpt-complex-app-acceptance-v1",
        "bounded_fixture_passed": True,
        "native_runtime_verified": True,
        "fresh_same_version_model_workflow": True,
        "task_id": model.get("task_id"),
        "source": model.get("source"),
        "scope": "Task Ledger long-request APK/EXE fixture, compiler repair, restart and update",
        "arbitrary_application_reliability_proven": False,
        "physical_owner_devices_verified": False,
        "limitations": [
            "This evidence covers one specified multi-feature application, not arbitrary requests",
            "Android runtime evidence is an emulator, not the owner's physical Pixel",
            "Model throughput and memory on the owner's GPU are not inferred from these tests",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--android", type=Path, required=True)
    parser.add_argument("--windows", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    paths = {name: getattr(args, name) for name in ("model", "android", "windows")}
    result = verify(**{name: json.loads(path.read_text()) for name, path in paths.items()})
    result["input_report_sha256"] = {
        name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in paths.items()
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"bounded_fixture_passed": True, "report": str(args.output)}))


if __name__ == "__main__":
    main()
