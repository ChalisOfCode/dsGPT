"""Allowlisted troubleshooting data from durable receipts, never private tool output."""

import hashlib
import json
from uuid import UUID

from .hardware import number

METRICS = {
    "total_duration",
    "load_duration",
    "eval_count",
    "eval_duration",
    "prompt_eval_count",
    "prompt_eval_duration",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "first_text_seconds",
    "elapsed_seconds",
    "thinking_chunks",
}
ERROR_HELP = {
    "work_no_progress": (
        "Work stopped after repeated unsuccessful actions. "
        "Review the saved task and tool results before resuming."
    ),
    "runtime_out_of_memory": (
        "The local runtime reported insufficient memory. Free RAM, reduce "
        "context or select a smaller model, then retry."
    ),
    "gpu_out_of_memory": (
        "The local runtime reported insufficient GPU memory. Unload other "
        "models, reduce context or GPU layers, then retry."
    ),
    "cuda_error": (
        "The local runtime reported a CUDA failure. Check the NVIDIA driver "
        "and restart the runtime before retrying."
    ),
    "model_load_failed": (
        "The local runtime could not load the model. Check the model files and available RAM/VRAM."
    ),
    "work_step_failed": "A Work step failed. Review the task checkpoint before resuming.",
    "build_failed": (
        "An isolated build or test failed. Review its saved compiler/test output in Work."
    ),
    "build_interrupted": (
        "An isolated tool execution was interrupted. Review its durable receipt before retrying."
    ),
    "backend_exception": (
        "An unexpected backend error occurred. A sanitized context snapshot "
        "was saved when storage was available."
    ),
    "database_failed": (
        "Database access failed. Check available disk space and restore a "
        "verified backup if integrity is damaged."
    ),
    "run_interrupted": (
        "A reply was interrupted. Partial output remains available; no request was replayed."
    ),
    "runtime_unavailable": "Start the configured local inference runtime and check its model.",
    "local_model_required": "Install and verify the selected model in the local runtime.",
    "local_vision_model_required": "Select a verified local model that supports images.",
    "context_exceeded": "Shorten the context or select a tested larger context configuration.",
    "runtime_context_mismatch": "Match the configured context to the running local server.",
    "model_digest_changed": "Verify the changed local model before using it again.",
    "output_limit": (
        "The model reached its output limit. If no answer appeared, reasoning may have "
        "used the budget. Select a model that supports disabling reasoning or raise the "
        "output limit within the context budget."
    ),
    "empty_model_response": (
        "The local model finished without an answer or tool action. Check it with a short Chat "
        "prompt and confirm its local runtime is responding. Try another installed model or "
        "turn off thinking if supported, then resume. No tool action was executed for this reply."
    ),
    "inference_failed": "Local inference failed. Check runtime health and available memory.",
    "inference_diagnostics_full": "Restart the backend to recover interrupted inference receipts.",
    "runtime_protocol_error": "The local runtime returned an incomplete or invalid response.",
    "research_failed": "A public research tool failed. Check its saved source status.",
    "managed_runtime_start_failed": "The managed local runtime could not start.",
    "managed_runtime_start_timeout": "The managed local runtime did not become ready in time.",
    "managed_runtime_integrity_failed": "Verify or reinstall the local runtime package.",
    "managed_runtime_unavailable": "The managed runtime is unavailable; verify its installation.",
    "backend_restarted": "The backend restarted; partial output is preserved without replay.",
    "backend_stopped_or_cancelled": "The reply was interrupted; partial output is preserved.",
}


def identifier(value):
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        return None


def object_value(value):
    try:
        result = json.loads(value or "{}")
        return result if isinstance(result, dict) else {}
    except (ValueError, TypeError):
        return {}


def model_details(model):
    return {
        "reference": hashlib.sha256(model.id.encode()).hexdigest()[:16],
        "runtime": model.runtime,
        "context_tokens": model.context,
        "output_token_limit": model.output_tokens,
        "abliterated": model.abliterated,
    }


def inference_details(store, models):
    recent = store.all("SELECT * FROM runs ORDER BY updated_at DESC LIMIT 50")
    reports = []
    for run in recent:
        values = {}
        events = store.all(
            "SELECT kind,payload FROM events WHERE run_id=? AND kind IN ('timing','metrics') "
            "ORDER BY id DESC LIMIT 20",
            (run["id"],),
        )
        for event in reversed(events):
            data = object_value(event["payload"])
            for key in METRICS:
                value = number(data.get(key), 1e18)
                if value is not None:
                    values[key] = value
        # Ollama reports nanoseconds. Do not infer throughput from wall time or characters.
        for count, duration, key in (
            ("eval_count", "eval_duration", "generation_tokens_per_second"),
            ("prompt_eval_count", "prompt_eval_duration", "prompt_tokens_per_second"),
        ):
            if count in values and values.get(duration, 0) > 0:
                rate = number(values[count] * 1e9 / values[duration], 1e12)
                if rate is not None:
                    values[key] = rate
        model = models.get(run["model_id"])
        reports.append(
            {
                "request_id": identifier(run["id"]),
                "updated_at": run["updated_at"],
                "status": run["status"],
                "model": model_details(model)
                if model
                else {"configuration": "no_longer_registered"},
                "metrics": values,
                "error_code": run["error_code"]
                if run["error_code"] in ERROR_HELP
                else "unclassified_failure"
                if run["error_code"]
                else None,
            }
        )
    return {
        "recent_requests": reports,
        "limit": 50,
        "configured_models": len(models),
        "limitations": [
            "Model names, endpoints and paths are excluded.",
            "Missing metrics were not reported by the runtime.",
            "Historical model settings are the current registration, if available.",
        ],
    }


def work_details(store):
    from .work_inference import recent

    rows = store.all(
        "SELECT id,task_id,status,result,cleanup_pending,created_at,updated_at "
        "FROM work_executions ORDER BY updated_at DESC LIMIT 50"
    )
    executions = []
    for row in rows:
        result = object_value(row.pop("result"))
        row["id"], row["task_id"] = identifier(row["id"]), identifier(row["task_id"])
        row["exit_code"] = number(result.get("exit_code"), 65535, -255)
        row["cleanup_pending"] = bool(row["cleanup_pending"])
        executions.append(row)
    return {
        "recent_executions": executions,
        "recent_inference_attempts": recent(store),
        "inference_attempt_retention": 200,
        "limit": 50,
        "task_counts": store.all("SELECT status,COUNT(*) AS count FROM work_tasks GROUP BY status"),
        "limitations": [
            "Commands, filenames, project contents and raw build/test logs are excluded.",
            "Work inference configuration is frozen per attempt, not current registration.",
            "Configured digest is a pin, not an observed runtime measurement.",
            "Stream completion does not establish a valid action or successful tool execution.",
            "Review private compiler details in the authenticated Work log viewer.",
        ],
    }


def recent_errors(store):
    rows = store.all(
        "SELECT code,correlation_id,created_at FROM diagnostic_events ORDER BY id DESC LIMIT 200"
    )
    return [{**row, "help": ERROR_HELP[row["code"]]} for row in rows if row["code"] in ERROR_HELP]
