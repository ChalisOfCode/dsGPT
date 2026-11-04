"""Independent bounded GGUF metadata/tensor audit of the official native COPY.

This reads payloads in at most 1 MiB chunks. It never loads a model or executes
conversion code, and it does not modify either GGUF. Whole-file hashes are taken
from the separate reviewer's conversion provenance; tensor bytes are independently
compared here, including the compatibility layer's exact F32 add-one operation.
"""

import argparse
import hashlib
import json
import math
import re
import struct
import time
from collections import Counter
from pathlib import Path

CHUNK = 1024 * 1024
PRIMITIVES = {
    0: "B",
    1: "b",
    2: "H",
    3: "h",
    4: "I",
    5: "i",
    6: "f",
    7: "?",
    10: "Q",
    11: "q",
    12: "d",
}
# GGML on-disk blocks used by this concrete model (no unsupported type guessing).
GGML_BLOCKS = {
    0: (1, 4),
    1: (1, 2),
    2: (32, 18),
    3: (32, 20),
    6: (32, 22),
    7: (32, 24),
    8: (32, 34),
    10: (256, 84),
    11: (256, 110),
    12: (256, 144),
    13: (256, 176),
    14: (256, 210),
    15: (256, 292),
}
SHARED = {
    "mtp.fc.weight": "nextn.eh_proj.weight",
    "mtp.pre_fc_norm_embedding.weight": "nextn.enorm.weight",
    "mtp.pre_fc_norm_hidden.weight": "nextn.hnorm.weight",
    "mtp.embed_tokens.weight": "nextn.embed_tokens.weight",
    "mtp.shared_head.head.weight": "nextn.shared_head_head.weight",
    "mtp.shared_head.norm.weight": "nextn.shared_head_norm.weight",
    "mtp.norm.weight": "nextn.shared_head_norm.weight",
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def stat(path):
    value = path.stat()
    return {"bytes": value.st_size, "mtime_ns": value.st_mtime_ns, "inode": value.st_ino}


class GGUF:
    def __init__(self, path):
        self.path = path
        self.length = path.stat().st_size
        self.file = path.open("rb")
        self.metadata = {}
        self.tensors = {}
        if self.read(4) != b"GGUF":
            raise ValueError("Invalid GGUF magic")
        self.version = self.number("I")
        if self.version != 3:
            raise ValueError("Audit supports the concrete GGUF v3 files only")
        self.tensor_count = self.number("Q")
        metadata_count = self.number("Q")
        if self.tensor_count > 100000 or metadata_count > 100000:
            raise ValueError("Unbounded GGUF descriptor count")
        for _ in range(metadata_count):
            name = self.string()
            if name in self.metadata:
                raise ValueError("Duplicate metadata key")
            begin = self.file.tell()
            kind = self.number("I")
            decoded = self.value(kind)
            end = self.file.tell()
            self.metadata[name] = {
                "type": kind,
                "value": decoded,
                "sha256": self.hash_span(begin, end - begin),
            }
        for _ in range(self.tensor_count):
            name = self.string()
            ndims = self.number("I")
            if name in self.tensors or not 1 <= ndims <= 4:
                raise ValueError("Duplicate tensor or invalid dimensions")
            dims = [self.number("Q") for _ in range(ndims)]
            kind = self.number("I")
            offset = self.number("Q")
            if kind not in GGML_BLOCKS:
                raise ValueError(f"Unsupported concrete tensor type {kind}")
            elements = math.prod(dims)
            block, size = GGML_BLOCKS[kind]
            if not elements or elements % block:
                raise ValueError("Invalid tensor block dimensions")
            self.tensors[name] = {
                "dimensions": dims,
                "type": kind,
                "offset": offset,
                "bytes": elements // block * size,
            }
        alignment = self.metadata.get("general.alignment", {}).get("value", 32)
        if not isinstance(alignment, int) or alignment <= 0 or alignment > 65536:
            raise ValueError("Invalid alignment")
        self.data_offset = ((self.file.tell() + alignment - 1) // alignment) * alignment
        last = self.data_offset
        for tensor in sorted(self.tensors.values(), key=lambda x: x["offset"]):
            tensor["position"] = self.data_offset + tensor["offset"]
            if tensor["position"] < last or tensor["offset"] % alignment:
                raise ValueError("Overlapping or misaligned tensors")
            last = tensor["position"] + tensor["bytes"]
            if last > self.length:
                raise ValueError("Tensor exceeds file")

    def read(self, length):
        if not 0 <= length <= 8 * CHUNK:
            raise ValueError("Unbounded read")
        value = self.file.read(length)
        if len(value) != length:
            raise ValueError("Truncated GGUF")
        return value

    def number(self, format):
        return struct.unpack("<" + format, self.read(struct.calcsize(format)))[0]

    def string(self):
        length = self.number("Q")
        return self.read(length).decode("utf-8")

    def skip(self, length):
        if length < 0 or self.file.tell() + length > self.length:
            raise ValueError("Invalid metadata length")
        self.file.seek(length, 1)

    def value(self, kind, depth=0):
        if depth > 4:
            raise ValueError("Unbounded metadata nesting")
        if kind in PRIMITIVES:
            return self.number(PRIMITIVES[kind])
        if kind == 8:
            return self.string()
        if kind != 9:
            raise ValueError(f"Unknown metadata type {kind}")
        element = self.number("I")
        count = self.number("Q")
        if count > 2000000:
            raise ValueError("Unbounded metadata array")
        if count <= 1024:
            return {
                "element_type": element,
                "items": [self.value(element, depth + 1) for _ in range(count)],
            }
        if element in PRIMITIVES:
            self.skip(count * struct.calcsize(PRIMITIVES[element]))
        elif element == 8:
            for _ in range(count):
                self.skip(self.number("Q"))
        else:
            raise ValueError("Unsupported large nested metadata array")
        return {"element_type": element, "count": count, "decoded": False}

    def hash_span(self, offset, length):
        previous = self.file.tell()
        self.file.seek(offset)
        hasher = hashlib.sha256()
        while length:
            take = min(length, CHUNK)
            hasher.update(self.read(take))
            length -= take
        self.file.seek(previous)
        return hasher.hexdigest()


def mapped_tensor(name, base, count):
    # Match the pinned text loader's order: dt rename, MTP rename, skip prefixes.
    changed = name + ".bias" if name.endswith(".ssm_dt") else name
    match = re.fullmatch(r"mtp\.layers\.(\d+)\.(.+)", changed)
    if match and int(match[1]) < count:
        changed = f"blk.{base + int(match[1])}.{match[2]}"
    elif changed in SHARED and count == 1:
        changed = f"blk.{base}.{SHARED[changed]}"
    if changed.startswith(("v.", "mm.", "mtp.")):
        return None, False
    shift = (
        name.startswith("mtp.")
        and changed != name
        and not changed.endswith(".ssm_norm.weight")
        and (
            changed.endswith("_norm.weight")
            or changed.endswith((".nextn.enorm.weight", ".nextn.hnorm.weight"))
        )
    )
    return changed, shift


def compare_metadata(original, copied):
    expected = dict(original.metadata)
    changes = []

    def require(key, kind, value):
        actual = copied.metadata.get(key)
        if actual is None or actual["type"] != kind or actual["value"] != value:
            raise ValueError(f"Compatibility metadata differs: {key}")
        expected[key] = actual
        if key not in original.metadata or actual["sha256"] != original.metadata[key]["sha256"]:
            changes.append({"key": key, "before": original.metadata.get(key), "after": actual})

    architecture = original.metadata["general.architecture"]["value"]
    if architecture != "qwen35":
        raise ValueError("Audit is scoped to the original dense qwen35 model")
    base = 1 + max(
        int(re.match(r"blk\.(\d+)\.", n)[1]) for n in original.tensors if n.startswith("blk.")
    )
    layer_ids = [int(m[1]) for n in original.tensors if (m := re.match(r"mtp\.layers\.(\d+)\.", n))]
    count = (
        max(layer_ids) + 1
        if layer_ids
        else int(any(n.startswith("mtp.") for n in original.tensors))
    )
    head = original.metadata["qwen35.attention.head_count_kv"]["value"]
    require("qwen35.attention.head_count_kv", 4, max(head["items"]) or 2)
    rope = original.metadata["qwen35.rope.dimension_sections"]["value"]
    require("qwen35.rope.dimension_sections", 9, {"element_type": 5, "items": rope["items"] + [0]})
    require("qwen35.block_count", 4, base + count)
    require("qwen35.nextn_predict_layers", 4, count)
    # The COPY writer preserves the input ftype and writes GGML_QNT_VERSION=2.
    require("general.file_type", 4, original.metadata["general.file_type"]["value"])
    require("general.quantization_version", 4, 2)
    for key in ("split.no", "split.count", "split.tensors.count"):
        expected.pop(key, None)
    if set(expected) != set(copied.metadata):
        raise ValueError(f"Unexpected metadata keys: {set(expected) ^ set(copied.metadata)}")
    for key, value in expected.items():
        if value["sha256"] != copied.metadata[key]["sha256"]:
            raise ValueError(f"Unexpected metadata byte change: {key}")
    return base, count, changes


def compare_payloads(original, copied, first, second, shift):
    if (
        first["dimensions"] != second["dimensions"]
        or first["type"] != second["type"]
        or first["bytes"] != second["bytes"]
    ):
        raise ValueError("Tensor shape/type/size changed")
    if shift and first["type"] != 0:
        raise ValueError("This concrete audit expects F32 norm-shift sources")
    original.file.seek(first["position"])
    copied.file.seek(second["position"])
    length = first["bytes"]
    original_sha, copied_sha = hashlib.sha256(), hashlib.sha256()
    while length:
        take = min(CHUNK, length)
        a, b = original.read(take), copied.read(take)
        original_sha.update(a)
        copied_sha.update(b)
        if shift:
            expected = b"".join(struct.pack("<f", x[0] + 1.0) for x in struct.iter_unpack("<f", a))
            if expected != b:
                raise ValueError("F32 compatibility add-one values differ")
        elif a != b:
            raise ValueError("Unchanged tensor bytes differ")
        length -= take
    return original_sha.hexdigest(), copied_sha.hexdigest()


def audit(args):
    started = time.monotonic()
    provenance_bytes = args.provenance.read_bytes()
    provenance = json.loads(provenance_bytes)
    source = Path(provenance["source_path"])
    converted = Path(provenance["converted_path"])
    before = {"source": stat(source), "converted": stat(converted)}
    report = {
        "passed": False,
        "original_model_tag": provenance["original_model_tag"],
        "source_gguf_sha256": provenance["source_gguf_sha256"],
        "converted_gguf_sha256": provenance["converted_gguf_sha256"],
        "conversion": provenance["conversion"],
        "conversion_provenance_sha256": digest(provenance_bytes),
        "conversion_provenance_path": str(args.provenance),
        "full_file_hash_source": "Separate reviewer conversion-run.json; "
        "retained tensor payloads independently compared here",
        "scope": "Native text-only representation of the same active weights and quantization; "
        "embedded vision/projector omitted, not an Ollama environment claim",
        "inference_performed": False,
        "maximum_payload_chunk_bytes": CHUNK,
        "file_stat_before": before,
        "metadata_changes": [],
        "tensors": [],
        "omitted": [],
        "errors": [],
    }
    original = copied = None
    try:
        if (
            not provenance.get("original_sha_verified")
            or not provenance.get("source_unchanged")
            or provenance.get("returncode") != 0
        ):
            raise ValueError("Conversion provenance has not verified source identity")
        if (
            before["source"]["bytes"] != provenance["source_stat_after"]["size"]
            or before["source"]["mtime_ns"] != provenance["source_stat_after"]["mtime_ns"]
            or before["converted"]["bytes"] != provenance["converted_bytes"]
        ):
            raise ValueError("Current model files differ from conversion provenance")
        for name, expected in provenance["source_evidence"].items():
            if digest((args.provenance.parent / name).read_bytes()) != expected:
                raise ValueError("Pinned implementation source changed")
        original, copied = GGUF(source), GGUF(converted)
        base, count, report["metadata_changes"] = compare_metadata(original, copied)
        expected_names = set()
        for name, first in original.tensors.items():
            mapped, shift = mapped_tensor(name, base, count)
            if mapped is None:
                report["omitted"].append(
                    {
                        "name": name,
                        "bytes": first["bytes"],
                        "reason": "Official text-loader skip prefix",
                    }
                )
                continue
            if mapped in expected_names:
                raise ValueError(f"Ambiguous mapped tensor {mapped}")
            expected_names.add(mapped)
            second = copied.tensors.get(mapped)
            if second is None:
                raise ValueError(f"Missing retained tensor {mapped}")
            first_sha, second_sha = compare_payloads(original, copied, first, second, shift)
            report["tensors"].append(
                {
                    "source_name": name,
                    "converted_name": mapped,
                    "bytes": first["bytes"],
                    "type": first["type"],
                    "dimensions": first["dimensions"],
                    "source_sha256": first_sha,
                    "converted_sha256": second_sha,
                    "operation": "F32 add-one compatibility norm shift"
                    if shift
                    else "byte-identical",
                }
            )
        if expected_names != set(copied.tensors):
            raise ValueError(f"Unexpected converted tensors {set(copied.tensors) - expected_names}")
        report.update(
            metadata_verified=True,
            tokenizer_and_template_metadata_byte_identical=all(
                original.metadata[key]["sha256"] == copied.metadata[key]["sha256"]
                for key in original.metadata
                if key.startswith("tokenizer.")
            ),
            original_tensor_count=original.tensor_count,
            converted_tensor_count=copied.tensor_count,
            retained_tensor_count=len(expected_names),
            tensor_types=dict(Counter(str(x["type"]) for x in report["tensors"])),
            quantization_preserved=True,
            active_weights_preserved=True,
            compatibility_transform_count=sum(
                x["operation"] != "byte-identical" for x in report["tensors"]
            ),
            compatibility_transformed_bytes=sum(
                x["bytes"] for x in report["tensors"] if x["operation"] != "byte-identical"
            ),
            omitted_tensor_count=len(report["omitted"]),
            omitted_bytes=sum(x["bytes"] for x in report["omitted"]),
        )
        report["file_stat_after"] = {"source": stat(source), "converted": stat(converted)}
        report["files_unchanged_during_audit"] = report["file_stat_after"] == before
        report["passed"] = (
            report["files_unchanged_during_audit"]
            and report["tokenizer_and_template_metadata_byte_identical"]
        )
    except Exception as exc:
        report["errors"].append({"type": type(exc).__name__, "message": str(exc)})
    finally:
        for item in (original, copied):
            if item is not None:
                item.file.close()
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                key: value
                for key, value in report.items()
                if key not in {"tensors", "omitted", "metadata_changes"}
            },
            indent=2,
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    options = parser.parse_args()
    Path("/proc/self/oom_score_adj").write_text("1000")
    raise SystemExit(audit(options))
