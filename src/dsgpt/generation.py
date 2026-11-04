"""Per-request controls, persisted with accepted work rather than global model state."""

from dataclasses import replace

from .inference import InferenceError


def controls(info):
    metadata = info.get("thinking")
    values = metadata.get("values") if isinstance(metadata, dict) else None
    if not isinstance(values, list):
        values = [False, True] if "thinking" in info.get("capabilities", []) else []
    choices = [{"id": "auto", "label": "Model default"}]
    for value in values:
        if isinstance(value, bool):
            item = {"id": "on" if value else "off", "label": "Thinking" if value else "Instant"}
        elif isinstance(value, str) and 0 < len(value) <= 40:
            item = {"id": value, "label": value.replace("_", " ").title()}
        else:
            continue
        if item not in choices:
            choices.append(item)
    return choices


def think_value(effort, local):
    if effort is None:
        return local.get("think", False)  # Preserve old clients' answer-first behavior.
    if effort == "auto":
        return None
    if effort not in {choice["id"] for choice in local.get("thinking_choices", [])}:
        raise InferenceError("thinking_control_unsupported")
    return {"on": True, "off": False}.get(effort, effort)


def save(db, kind, identifier, effort=None, web_mode="off"):
    db.execute(
        "INSERT INTO generation_options(kind,id,effort,web_mode) VALUES(?,?,?,?)",
        (kind, identifier, effort, web_mode),
    )


def options(store, kind, identifier):
    return store.one(
        "SELECT * FROM generation_options WHERE kind=? AND id=?", (kind, identifier)
    ) or {
        "effort": None,
        "web_mode": "off",
        "web_planned": 1,
    }


def for_request(store, kind, identifier, model):
    output = model.output_tokens
    if kind == "work":
        # Short JSON/file actions still need more room than a 1024-token chat answer.
        output = min(max(output, 2048), max(1, model.context // 3))
    return replace(
        model, output_tokens=output, reasoning_effort=options(store, kind, identifier)["effort"]
    )
