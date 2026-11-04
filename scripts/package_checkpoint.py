"""Package a clean Git revision, verified backend wheel, evidence and recovery bundle."""

import argparse
import hashlib
import io
import json
import shutil
import subprocess
import tarfile
import tempfile
import tomllib
import zipfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--stage", default="Stage2")
    parser.add_argument("--validation", default="reports/stage2-validation.json")
    parser.add_argument("--checkpoint", default="stage2-native-clients")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]

    def git(*arguments):
        return subprocess.check_output(["git", *arguments], cwd=root)

    if git("status", "--porcelain").strip():
        raise SystemExit("Commit the intended checkpoint before packaging")
    revision = git("rev-parse", "HEAD").decode().strip()
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    wheel = root / f"dist/dsgpt_backend-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel) as package:
        for source in (root / "src/dsgpt").glob("*.py"):
            if package.read("dsgpt/" + source.name) != source.read_bytes():
                raise SystemExit("Wheel is stale; rebuild before packaging")
    with tempfile.TemporaryDirectory(prefix="dsgpt-package-") as temporary:
        if not args.stage.isalnum():
            raise SystemExit("Stage label must be alphanumeric")
        stage = Path(temporary) / ("dsGPT-" + args.stage)
        stage.mkdir()
        with tarfile.open(fileobj=io.BytesIO(git("archive", "--format=tar", "HEAD"))) as archive:
            archive.extractall(stage, filter="data")
        (stage / "dist").mkdir()
        shutil.copy2(wheel, stage / "dist" / wheel.name)
        source_distribution = root / f"dist/dsgpt_backend-{version}.tar.gz"
        shutil.copy2(source_distribution, stage / "dist" / source_distribution.name)
        validation = json.loads((root / args.validation).read_text())
        for relative, expected in validation["artifacts"].items():
            source = root / relative
            if hashlib.sha256(source.read_bytes()).hexdigest() != expected["sha256"]:
                raise SystemExit("Artifact changed after validation: " + relative)
            shutil.copy2(source, stage / relative)
        git("bundle", "create", str(stage / "repository.bundle"), "--all")
        metadata = {
            "schema_version": 1,
            "project": "dsGPT & dsGPT Mobile",
            "checkpoint": args.checkpoint,
            "repository_revision": revision,
            "native_windows_installer": "dist/dsGPT-Desktop-Preview-Setup.exe",
            "managed_windows_preview_installer": (
                "dist/dsGPT-Managed-Preview-Setup.exe"
                if "dist/dsGPT-Managed-Preview-Setup.exe" in validation["artifacts"]
                else None
            ),
            "native_android_apk": "dist/dsGPT-Mobile-Debug.apk",
            "development_wheel": "dist/" + wheel.name,
            "validation": validation,
            "model_weights_included": False,
            "final_system_release": False,
            "native_execution_tested": False,
            "signing_key_included": False,
        }
        (stage / "release-metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
        checksums = {
            str(path.relative_to(stage)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(stage.rglob("*"))
            if path.is_file()
        }
        (stage / "SHA256SUMS.json").write_text(json.dumps(checksums, indent=2) + "\n")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(args.output, "w", zipfile.ZIP_DEFLATED) as output:
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    output.write(path, str(path.relative_to(stage.parent)))
    print(
        json.dumps(
            {
                "path": str(args.output.resolve()),
                "revision": revision,
                "bytes": args.output.stat().st_size,
                "sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
