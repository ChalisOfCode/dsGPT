"""adb may exit zero even when instrumentation fails; require its actual result."""

import re
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8")
if (
    not re.search(r"^OK \(1 test\)\s*$", text, re.MULTILINE)
    or "INSTRUMENTATION_CODE: -1" not in text
    or "FAILURES!!!" in text
    or "INSTRUMENTATION_FAILED" in text
):
    raise SystemExit("Android lifecycle instrumentation did not pass; inspect the fixture report")
print("Android emulator lifecycle instrumentation passed; no physical-device claim.")
