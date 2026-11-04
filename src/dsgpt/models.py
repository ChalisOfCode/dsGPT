"""Persist verified local runtime registrations without changing runtime model files."""

import json
from dataclasses import asdict, replace

import httpx
from fastapi import HTTPException

from .config import Model
from .inference import InferenceError, LocalInference
from .storage import canonical, utcnow


class ModelRegistry:
    def __init__(self, store, models, validator=None):
        self.store, self.models = store, models
        self.validator = validator or LocalInference()
        self.configured_ids = set(models)
        for row in store.all("SELECT definition FROM model_records"):
            model = Model(**json.loads(row["definition"]))
            if model.id in models and models[model.id] != model:
                raise ValueError("Model ID conflicts with saved configuration; resolve explicitly")
            models[model.id] = model

    async def register(self, definition):
        try:
            model = Model(**definition)
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, "Invalid local model configuration") from exc
        if model.id in self.models:
            raise HTTPException(409, "Model ID already configured; choose a new ID")
        try:
            async with self.validator.client(model) as client:
                provenance = await self.validator.validate_local_model(client, model)
            if provenance["digest"]:
                model = replace(model, expected_digest=provenance["digest"])
        except (InferenceError, httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise HTTPException(
                422, "Local model verification failed; check the runtime and weights"
            ) from exc
        now = utcnow()
        # Async verification may have yielded while another owner request registered the ID.
        with self.store.transaction() as db:
            if (
                model.id in self.models
                or db.execute("SELECT id FROM model_records WHERE id=?", (model.id,)).fetchone()
            ):
                raise HTTPException(409, "Model ID already configured")
            db.execute(
                "INSERT INTO model_records VALUES(?,?,?)", (model.id, canonical(asdict(model)), now)
            )
        self.models[model.id] = model
        return {
            "id": model.id,
            "label": model.label,
            "verified_at": now,
            "digest": model.expected_digest,
            "bytes": provenance["bytes"],
            "verification": "local_runtime_metadata",
            "weights_modified": False,
        }

    def forget(self, model_id):
        if model_id in self.configured_ids:
            raise HTTPException(409, "Model is managed by the configuration file")
        with self.store.transaction() as db:
            active = db.execute(
                "SELECT 1 FROM runs WHERE model_id=? AND status IN ('queued','running')",
                (model_id,),
            ).fetchone()
            active_work = db.execute(
                "SELECT 1 FROM work_sessions s JOIN work_tasks t ON t.id=s.task_id "
                "WHERE s.model_id=? AND t.status IN ('queued','running')",
                (model_id,),
            ).fetchone()
            if active or active_work:
                raise HTTPException(
                    409, "Wait for or pause the active requests before forgetting this model"
                )
            if not db.execute("DELETE FROM model_records WHERE id=?", (model_id,)).rowcount:
                raise HTTPException(404, "Saved model configuration not found")
        self.models.pop(model_id, None)
        return {"forgotten": True, "weights_deleted": False}
