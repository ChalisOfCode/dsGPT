"""Release-pinned, reviewed downloads. API callers select IDs, never arbitrary URLs."""

import re
from dataclasses import asdict, dataclass
from urllib.parse import urlsplit

DOWNLOAD_HOSTS = frozenset(
    {
        "huggingface.co",
        "cas-bridge.xethub.hf.co",
        "cdn-lfs.huggingface.co",
        "cdn-lfs-us-1.hf.co",
        "cdn-lfs-eu-1.hf.co",
        "us.aws.cdn.hf.co",
        "github.com",
        "release-assets.githubusercontent.com",
    }
)


@dataclass(frozen=True)
class Asset:
    id: str
    name: str
    url: str
    sha256: str
    size: int
    license: str
    source: str
    purpose: str
    suffix: str = ".gguf"
    kind: str = "model"

    def __post_init__(self):
        url = urlsplit(self.url)
        if (
            not re.fullmatch(r"[a-z0-9-]{1,100}", self.id)
            or not re.fullmatch(r"[a-f0-9]{64}", self.sha256)
            or not 1 <= self.size <= 512 * 1024**3
            or url.scheme != "https"
            or url.port not in (None, 443)
            or url.username
            or url.password
            or url.query
            or url.fragment
            or not (
                self.kind == "model"
                and self.suffix == ".gguf"
                and url.hostname == "huggingface.co"
                and re.fullmatch(r"/[^/]+/[^/]+/resolve/[a-f0-9]{40}/[^/]+\.gguf", url.path)
                or self.kind == "runtime"
                and self.suffix in {".zip", ".tar.gz"}
                and url.hostname == "github.com"
                and re.fullmatch(
                    r"/ggml-org/llama\.cpp/releases/download/b[0-9]+/[A-Za-z0-9_.-]+", url.path
                )
                and url.path.endswith(self.suffix)
                or self.kind == "embedding"
                and self.suffix in {".onnx", ".json"}
                and url.hostname == "huggingface.co"
                and re.fullmatch(
                    r"/BAAI/bge-small-en-v1\.5/resolve/[a-f0-9]{40}/"
                    r"(?:onnx/model\.onnx|tokenizer\.json)",
                    url.path,
                )
                and url.path.endswith(self.suffix)
            )
        ):
            raise ValueError("Invalid pinned asset")

    def public(self):
        return {
            **asdict(self),
            "inference_ready": False,
            "benchmark_status": "CPU_smoke_only" if self.kind == "model" else "not_applicable",
        }


CATALOG = {
    a.id: a
    for a in [
        Asset(
            id="qwen3-1-7b-q8-0",
            name="Qwen3 1.7B Q8_0-NA",
            url="https://huggingface.co/Qwen/Qwen3-1.7B-GGUF/resolve/"
            "90862c4b9d2787eaed51d12237eafdfe7c5f6077/Qwen3-1.7B-Q8_0.gguf",
            sha256="061b54daade076b5d3362dac252678d17da8c68f07560be70818cace6590cb1a",
            size=1834426016,
            license="Apache-2.0",
            source="https://huggingface.co/Qwen/Qwen3-1.7B-GGUF/tree/"
            "90862c4b9d2787eaed51d12237eafdfe7c5f6077",
            purpose="Integration smoke model; not the final hardware recommendation",
        ),
        Asset(
            id="qwen3-4b-q4-k-m",
            name="Qwen3 4B Q4_K_M-NA",
            url="https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/"
            "bc640142c66e1fdd12af0bd68f40445458f3869b/Qwen3-4B-Q4_K_M.gguf",
            sha256="7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5",
            size=2497280256,
            license="Apache-2.0",
            source="https://huggingface.co/Qwen/Qwen3-4B-GGUF/tree/"
            "bc640142c66e1fdd12af0bd68f40445458f3869b",
            purpose="Research integration fixture; target GPU and broad quality benchmarks pending",
        ),
    ]
}

# Publisher's English embedding model. CPU-only; never a Chat model/provider.
for identifier, filename, digest, size in [
    (
        "bge-small-en-v1-5-onnx",
        "onnx/model.onnx",
        "828e1496d7fabb79cfa4dcd84fa38625c0d3d21da474a00f08db0f559940cf35",
        133093490,
    ),
    (
        "bge-small-en-v1-5-tokenizer",
        "tokenizer.json",
        "d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66",
        711396,
    ),
]:
    CATALOG[identifier] = Asset(
        identifier,
        "BGE small English v1.5 — " + filename,
        "https://huggingface.co/BAAI/bge-small-en-v1.5/resolve/"
        "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a/" + filename,
        digest,
        size,
        "MIT",
        "https://huggingface.co/BAAI/bge-small-en-v1.5/tree/"
        "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a",
        "Optional local English semantic retrieval; CPU only; no cloud inference",
        ".onnx" if filename.endswith(".onnx") else ".json",
        "embedding",
    )

# Exact asset digests/sizes from the official b11718 GitHub release, independently
# downloaded and hashed. CUDA dependencies are a separately verified required asset.
for identifier, filename, digest, size in [
    (
        "llama-b11718-linux-x64",
        "llama-b11718-bin-ubuntu-x64.tar.gz",
        "99f83b15cea9a4fb8945516c276b5f42b11608f82104fc6fa98a541cac826de7",
        17968484,
    ),
    (
        "llama-b11718-windows-cuda12",
        "llama-b11718-bin-win-cuda-12.4-x64.zip",
        "c13fda0ef74f47cd2bccda1eea2a62980c12a5778d39b39bedadb525b4e81aff",
        267470642,
    ),
    (
        "llama-b11718-windows-cudart12",
        "cudart-llama-bin-win-cuda-12.4-x64.zip",
        "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6",
        391443627,
    ),
]:
    CATALOG[identifier] = Asset(
        identifier,
        filename,
        "https://github.com/ggml-org/llama.cpp/releases/download/b11718/" + filename,
        digest,
        size,
        "NVIDIA CUDA redistributable terms" if "cudart" in identifier else "MIT; bundled notices",
        "https://github.com/ggml-org/llama.cpp/releases/tag/b11718",
        "Pinned development runtime; Windows/GPU acceptance pending",
        ".tar.gz" if filename.endswith(".tar.gz") else ".zip",
        "runtime",
    )
