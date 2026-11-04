"""Write the exact backend-bundled Docker build context (no user content)."""

import argparse
from pathlib import Path

from dsgpt.tool_setup import recipe_files

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--directory", type=Path, required=True)
args = parser.parse_args()
args.directory.mkdir(parents=True, exist_ok=True)
for name, data in recipe_files().items():
    (args.directory / name).write_bytes(data)
