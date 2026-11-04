"""A release must contain only hash-checked input files, even after runtime tests."""

import hashlib
import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/package_acceptance_kit.py"
spec = importlib.util.spec_from_file_location("acceptance_packaging", SCRIPT)
packaging = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packaging)


class AcceptancePackagingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.kit = self.root / "kit"
        self.kit.mkdir()
        self.output = self.root / "release.zip"
        self.data = b"verified program\r\n"
        (self.kit / "program.py").write_bytes(self.data)
        self.manifest = {
            "source_commit": "test-source",
            "files": {
                "program.py": {
                    "bytes": len(self.data),
                    "sha256": hashlib.sha256(self.data).hexdigest(),
                }
            },
        }
        self.write_manifest()

    def write_manifest(self):
        (self.kit / "kit-manifest.json").write_text(json.dumps(self.manifest))

    def test_exact_release_excludes_caches_and_is_reproducible(self):
        cache = self.kit / "__pycache__/program.cpython-313.pyc"
        cache.parent.mkdir()
        cache.write_bytes(b"runtime cache must not ship")
        result = packaging.package_kit(self.kit, self.output)
        with zipfile.ZipFile(self.output) as archive:
            self.assertEqual(set(archive.namelist()), {"program.py", "kit-manifest.json"})
            self.assertEqual(archive.read("program.py"), self.data)
        self.assertTrue(cache.is_file(), "Packaging must not modify the tested input")
        self.assertEqual(result["excluded_runtime_caches"], 1)
        self.assertEqual(
            result["sha256"], hashlib.sha256(self.output.read_bytes()).hexdigest()
        )
        self.assertEqual(self.output.with_suffix(".sha256").read_text().strip(), result["sha256"])
        self.assertEqual(packaging.package_kit(self.kit, self.root / "again.zip"), result)

    def test_altered_payload_does_not_replace_existing_release(self):
        self.output.write_bytes(b"previous release")
        (self.kit / "program.py").write_bytes(b"unverified program\n")
        with self.assertRaisesRegex(ValueError, "integrity"):
            packaging.package_kit(self.kit, self.output)
        self.assertEqual(self.output.read_bytes(), b"previous release")
        self.assertFalse(list(self.root.glob("*.partial")))

    def test_unexpected_private_output_cannot_be_published(self):
        (self.kit / "owner-token.txt").write_text("must stay private")
        with self.assertRaisesRegex(ValueError, "Unexpected kit file"):
            packaging.package_kit(self.kit, self.output)
        self.assertFalse(self.output.exists())

    def test_missing_file_cannot_be_published(self):
        (self.kit / "program.py").unlink()
        with self.assertRaisesRegex(ValueError, "Missing kit file"):
            packaging.package_kit(self.kit, self.output)

    def test_paths_cannot_escape_or_collide_on_windows(self):
        record = self.manifest["files"]["program.py"]
        for name in ["../outside", "/outside", "C:/outside", "bad\\name", "a//b", "PROGRAM.py"]:
            with self.subTest(name=name):
                self.manifest["files"] = {"program.py": record, name: record}
                self.write_manifest()
                with self.assertRaisesRegex(ValueError, "manifest path"):
                    packaging.package_kit(self.kit, self.output)


if __name__ == "__main__":
    unittest.main()
