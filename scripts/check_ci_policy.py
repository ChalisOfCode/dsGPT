"""Check the repository's narrow public-runner, permissions and storage policy."""

import re
from pathlib import Path

import yaml


def check(root):
    errors = []
    for path in sorted((root / ".github/workflows").glob("*.yml")):
        workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
        if any(x in workflow.get("on", {}) for x in ("pull_request_target", "schedule")):
            errors.append(f"{path.name}: unexpected privileged or recurring trigger")
        if any(v != "read" for v in workflow.get("permissions", {}).values()):
            errors.append(f"{path.name}: broad workflow permissions")
        for name, job in workflow["jobs"].items():
            prefix = f"{path.name}/{name}"
            if job.get("runs-on") not in {"ubuntu-24.04", "windows-2025"}:
                errors.append(prefix + ": nonstandard runner")
            condition = job.get("if", "")
            if (
                "github.event.repository.private == false" not in condition
                or "vars.DSGPT_ZERO_COST_READY == 'true'" not in condition
            ):
                errors.append(prefix + ": missing pre-allocation public/$0 gate")
            if not 1 <= int(job.get("timeout-minutes", 0)) <= 360:
                errors.append(prefix + ": missing/bad timeout")
            if any(v != "read" for v in job.get("permissions", {}).values()):
                errors.append(prefix + ": job permission escalation")
            for step in job.get("steps", []):
                uses = step.get("uses", "")
                if uses and not re.fullmatch(r"actions/[a-z-]+(?:/[a-z-]+)?@[0-9a-f]{40}", uses):
                    errors.append(prefix + ": unpinned/unreviewed action")
                if uses.startswith("actions/checkout@"):
                    if step.get("with", {}).get("persist-credentials") != "false":
                        errors.append(prefix + ": checkout credentials retained")
                if uses.startswith("actions/upload-artifact@"):
                    if step.get("with", {}).get("retention-days") != "1":
                        errors.append(prefix + ": artifact retention must be one day")
        if "secrets." in path.read_text() and "pull_request" in workflow.get("on", {}):
            errors.append(path.name + ": PR workflow must not reference signing secrets")
    if errors:
        raise ValueError("\n".join(errors))


if __name__ == "__main__":
    check(Path(__file__).resolve().parents[1])
    print("Static CI policy passed; account billing/settings still require direct verification.")
