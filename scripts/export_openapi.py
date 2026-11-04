"""Export the API contract from an isolated, empty temporary database."""

import json
import tempfile
from pathlib import Path

from dsgpt.api import create_app
from dsgpt.config import Settings

with tempfile.TemporaryDirectory(prefix="dsgpt-schema-") as directory:
    schema = create_app(Settings(Path(directory))).openapi()
    target = Path(__file__).resolve().parents[1] / "api/openapi.json"
    target.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
