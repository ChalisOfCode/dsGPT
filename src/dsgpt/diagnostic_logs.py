"""Explicitly opted-in, bounded build output with best-effort secret redaction."""

import re

from .diagnostic_details import object_value


def redact(value):
    value = re.sub(
        r"-----BEGIN [^-\n]*PRIVATE KEY-----[\s\S]*?(?:-----END [^-\n]*PRIVATE KEY-----|\Z)",
        "[PRIVATE KEY REDACTED]",
        value,
    )
    value = re.sub(
        r"(?im)^.*(?:authorization|proxy-authorization|cookie|set-cookie)\s*[:=].*$",
        "[SENSITIVE HEADER REDACTED]",
        value,
    )
    value = re.sub(
        r"(?i)\b(?:password|passwd|token|api[_-]?key|secret|credential)\b"
        r"[\"']?\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;}]+)",
        "[SECRET REDACTED]",
        value,
    )
    value = re.sub(
        r"(?i)\b(?:bearer\s+\S+|tskey-\S+|gh[pousr]_\w+|github_pat_\w+)", "[TOKEN REDACTED]", value
    )
    value = re.sub(r"https?://[^\s<>\"']+", "[URL REDACTED]", value)
    return value


def build_logs(store):
    files = {}
    rows = store.all("SELECT id,result FROM work_executions ORDER BY updated_at DESC LIMIT 5")
    for row in rows:
        result = object_value(row["result"])
        for stream in ("stdout", "stderr"):
            value = result.get(stream)
            if not isinstance(value, str) or not value:
                continue
            # Redact before clipping so a truncated multiline key cannot escape redaction.
            value = redact(value)
            raw = value.encode()
            suffix = "\n[Truncated to 16 KiB]" if len(raw) > 16384 else ""
            files[f"desktop/build-logs/{row['id']}-{stream}.log"] = (
                raw[:16384].decode("utf-8", errors="ignore") + suffix
            )
    return files
