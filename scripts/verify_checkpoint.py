"""Verify a checkpoint archive's files against SHA256SUMS.json without executing code."""

import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
manifest = json.loads((root / "SHA256SUMS.json").read_text())
failures = []
for relative, expected in manifest.items():
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        failures.append(relative)
    elif hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        failures.append(relative)
if failures:
    raise SystemExit("Checkpoint verification failed: " + ", ".join(failures))
print(f"Verified {len(manifest)} checkpoint files")
