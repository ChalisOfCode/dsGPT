"""Observe two exact model-edited app revisions on disposable native runners."""

import argparse
import json
from pathlib import Path

from check_complex_app_runtime import Android, Windows, file_record

LABELS = {"initial": "Smoke ready", "followup": "Smoke updated"}


def verify(model, reports):
    if (
        model.get("format") != "dsgpt-bounded-model-smoke-v1"
        or model.get("status") != "compiled"
        or model.get("error")
        or len(model.get("inference_calls", [])) != 2
        or not 0 < model.get("model_seconds", 0) <= 360
    ):
        raise ValueError("Bounded model compilation did not pass")
    for platform, kind in (("android", "apk"), ("windows", "exe")):
        native = reports[platform]
        if native.get("platform") != platform or native.get("passed") is not True:
            raise ValueError("Native smoke failed: " + platform)
        for phase, label in LABELS.items():
            receipt = native["checks"][phase]
            if (
                receipt["label"] != label
                or receipt["artifact"]["sha256"] != model["phases"][phase]["artifacts"][kind]
            ):
                raise ValueError("Native evidence mismatch: " + platform + "/" + phase)
    return {"passed": True, "source": model["source"], "scope": "bounded_two_revision_smoke"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=("android", "windows", "join"), required=True)
    for name in ("initial", "updated", "model", "android", "windows", "output"):
        parser.add_argument("--" + name, type=Path, required=name == "output")
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--serial")
    parser.add_argument("--package")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.platform == "join":
        result = verify(
            json.loads(args.model.read_text()),
            {
                platform: json.loads(getattr(args, platform).read_text())
                for platform in ("android", "windows")
            },
        )
        args.output.write_text(json.dumps(result, indent=2) + "\n")
        return
    result = {"platform": args.platform, "passed": False, "checks": {}}
    driver = None
    try:
        driver = (Android if args.platform == "android" else Windows)(args, args.output.parent)
        for phase, artifact in (("initial", args.initial), ("followup", args.updated)):
            driver.install(artifact.resolve(), fresh=phase == "initial")
            driver.launch(smoke_label=LABELS[phase])
            result["checks"][phase] = {"label": LABELS[phase], "artifact": file_record(artifact)}
            driver.close()
        result["passed"] = True
    finally:
        try:
            if driver:
                driver.cleanup() if isinstance(driver, Windows) else driver.close()
        except BaseException:
            result["passed"] = False
            raise
        finally:
            args.output.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
