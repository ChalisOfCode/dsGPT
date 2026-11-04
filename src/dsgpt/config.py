import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Model:
    id: str
    name: str
    runtime: str
    endpoint: str
    runtime_model: str
    abliterated: bool = False
    context: int = 8192
    output_tokens: int = 1024
    expected_digest: str | None = None
    reasoning_effort: str | None = None

    def __post_init__(self):
        url = urlsplit(self.endpoint)
        if (
            url.scheme != "http"
            or url.hostname not in {"127.0.0.1", "::1"}
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path not in {"", "/"}
            or not url.port
        ):
            raise ValueError("Inference must use a literal loopback HTTP address and explicit port")
        if self.runtime not in {"ollama", "llama.cpp"}:
            raise ValueError("Only supported local inference runtimes may be configured")
        if "cloud" in self.runtime_model.lower() or "://" in self.runtime_model:
            raise ValueError("Cloud model identifiers are prohibited")
        if not self.id or not self.name or not self.runtime_model:
            raise ValueError("Model identifiers and name are required")
        if not 512 <= self.context <= 131072 or not 1 <= self.output_tokens < self.context:
            raise ValueError("Invalid context/output budget")
        if self.expected_digest is not None and not re.fullmatch(
            r"[0-9a-f]{64}", self.expected_digest
        ):
            raise ValueError("Model digest must be SHA256")
        if self.expected_digest and self.runtime != "ollama":
            raise ValueError("Runtime digest verification currently requires Ollama")

    @property
    def label(self):
        return self.name + ("-A" if self.abliterated else "-NA")


@dataclass
class Settings:
    data_dir: Path
    models: dict[str, Model] = field(default_factory=dict)
    allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost", "[::1]")
    allowed_origins: tuple[str, ...] = ()
    max_request_bytes: int = 2_000_000
    diagnostic_retention: int = 100
    diagnostic_event_retention: int = 2000
    diagnostic_snapshot_retention: int = 50
    diagnostic_snapshot_bytes: int = 131072
    diagnostic_export_bytes: int = 8 * 1024 * 1024
    search_origin: str | None = None
    sandbox_image: str | None = None

    def __post_init__(self):
        from .web_retrieval import local_search_origin

        for value in (
            self.diagnostic_retention,
            self.diagnostic_event_retention,
            self.diagnostic_snapshot_retention,
            self.diagnostic_snapshot_bytes,
            self.diagnostic_export_bytes,
        ):
            if type(value) is not int:
                raise ValueError("Diagnostic retention and size limits must be integers")
        if not 1 <= self.diagnostic_retention <= 1000:
            raise ValueError("Keep between 1 and 1000 mobile snapshots per device")
        if not 1 <= self.diagnostic_event_retention <= 10000:
            raise ValueError("Keep between 1 and 10000 sanitized diagnostic events")
        if not 1 <= self.diagnostic_snapshot_retention <= 100:
            raise ValueError("Keep between 1 and 100 backend snapshots")
        if not 4096 <= self.diagnostic_snapshot_bytes <= 524288:
            raise ValueError("Snapshot size must be between 4 and 512 KiB")
        if not 131072 <= self.diagnostic_export_bytes <= 32 * 1024 * 1024:
            raise ValueError("Export size must be between 128 KiB and 32 MiB")
        self.data_dir = Path(self.data_dir).resolve()
        self.search_origin = local_search_origin(self.search_origin)
        if self.sandbox_image is not None and not re.fullmatch(
            r"sha256:[a-f0-9]{64}", self.sandbox_image
        ):
            raise ValueError("Sandbox image must be a locally installed immutable image ID")
        if "*" in self.allowed_hosts:
            raise ValueError("Specify exact local and tailnet hostnames")
        if any(key != model.id for key, model in self.models.items()):
            raise ValueError("Model mapping keys must match model ids")
