"""Verified local BGE inference. No provider, from_pretrained, GPU, or network APIs."""

import hashlib
import os

from .catalog import CATALOG
from .downloads import DownloadError, secure_file

MODEL_ID = "bge-small-en-v1-5"
ASSET_IDS = (MODEL_ID + "-onnx", MODEL_ID + "-tokenizer")
DIMENSIONS = 384
MAX_SOURCE_CHARS = 131072
MAX_CHUNKS = 256
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class EmbeddingError(Exception):
    pass


def verified_bytes(downloads, asset_id):
    asset = CATALOG[asset_id]
    row = downloads.store.one("SELECT status FROM downloads WHERE asset_id=?", (asset_id,))
    if not row or row["status"] != "downloaded":
        raise EmbeddingError("embedding_assets_required")
    try:
        with secure_file(downloads.paths(asset)[1], os.O_RDONLY) as file:
            content = file.read(asset.size + 1)
    except (OSError, DownloadError) as exc:
        raise EmbeddingError("embedding_integrity_failed") from exc
    if len(content) != asset.size or hashlib.sha256(content).hexdigest() != asset.sha256:
        raise EmbeddingError("embedding_integrity_failed")
    return content


class LocalEmbedder:
    def __init__(self, downloads):
        try:
            import numpy as np
            import onnxruntime as ort
            from tokenizers import Tokenizer
        except ImportError as exc:
            raise EmbeddingError("embedding_dependencies_required") from exc
        self.np = np
        self.tokenizer = Tokenizer.from_str(verified_bytes(downloads, ASSET_IDS[1]).decode())
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()
        ort.disable_telemetry_events()
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        options.add_session_config_entry("session.inter_op.allow_spinning", "0")
        # Bytes prevent an ONNX external-data reference from resolving a local path.
        self.session = ort.InferenceSession(
            verified_bytes(downloads, ASSET_IDS[0]),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        if self.session.get_providers() != ["CPUExecutionProvider"] or {
            v.name for v in self.session.get_inputs()
        } != {"input_ids", "attention_mask", "token_type_ids"}:
            raise EmbeddingError("embedding_protocol_error")

    def _vectors(self, sequences):
        np = self.np
        width = max(len(v) + 2 for v in sequences)
        ids = np.zeros((len(sequences), width), dtype=np.int64)
        mask = np.zeros_like(ids)
        for index, sequence in enumerate(sequences):
            if len(sequence) > 510:
                raise EmbeddingError("embedding_protocol_error")
            tokens = [101, *sequence, 102]
            ids[index, : len(tokens)] = tokens
            mask[index, : len(tokens)] = 1
        values = self.session.run(
            None,
            {
                "input_ids": ids,
                "attention_mask": mask,
                "token_type_ids": np.zeros_like(ids),
            },
        )[0]
        if values.shape != (len(sequences), width, DIMENSIONS):
            raise EmbeddingError("embedding_protocol_error")
        values = values[:, 0, :].astype(np.float32)  # Publisher's CLS pooling, not mean pooling.
        norms = np.linalg.norm(values, axis=1, keepdims=True)
        if not np.isfinite(values).all() or not np.isfinite(norms).all() or (norms <= 0).any():
            raise EmbeddingError("embedding_protocol_error")
        return values / norms

    def document(self, text):
        encoding = self.tokenizer.encode(text[:MAX_SOURCE_CHARS], add_special_tokens=False)
        result = []
        positions = list(range(0, len(encoding.ids), 352))[:MAX_CHUNKS]
        for batch in range(0, len(positions), 4):
            offsets = positions[batch : batch + 4]
            sequences = [encoding.ids[p : p + 384] for p in offsets]
            for pos, tokens, vector in zip(
                offsets, sequences, self._vectors(sequences), strict=True
            ):
                start = encoding.offsets[pos][0]
                end = encoding.offsets[pos + len(tokens) - 1][1]
                result.append((start, end, vector.astype("<f4").tobytes()))
        omitted = max(0, len(text) - (result[-1][1] if result else 0))
        return result, omitted

    def query(self, text):
        tokens = self.tokenizer.encode(QUERY_PREFIX + text, add_special_tokens=False).ids[:510]
        return self._vectors([tokens])[0].astype("<f4").tobytes()
