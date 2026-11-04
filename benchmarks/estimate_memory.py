"""Arithmetic estimates only; no throughput or measured residency is inferred."""

import json

GIB = 1024**3
rows = []
for context in [8192, 16384, 24576, 32768]:
    for bits in [16, 8, 4]:
        rows.append(
            {
                "model": "Qwen3.5-9B",
                "context_tokens": context,
                "cache_bits": bits,
                "attention_kv_gib": 2 * 8 * 4 * 256 * context * (bits / 8) / GIB,
                "excludes": [
                    "recurrent_state",
                    "quantization_metadata",
                    "runtime_buffers",
                    "vision_encoder",
                    "display_vram",
                    "model_weights",
                ],
            }
        )
print(
    json.dumps(
        {
            "classification": "calculated_not_measured",
            "source": "https://huggingface.co/Qwen/Qwen3.5-9B",
            "weight_lower_bounds_gib": {
                str(parameters): {
                    "Q" + str(bits): parameters * 1e9 * bits / 8 / GIB for bits in [4, 5, 6]
                }
                for parameters in [8, 9, 12, 14, 20, 30]
            },
            "attention_cache": rows,
            "warning": "Raw bit-count lower bounds are not GGUF sizes or runtime VRAM. "
            "Other architectures need their own layer layouts and cache accounting.",
        },
        indent=2,
    )
)
