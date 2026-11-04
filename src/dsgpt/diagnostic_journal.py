"""Bounded local failure context. No exception text, prompts, commands or credentials."""

import hashlib

from .diagnostic_details import ERROR_HELP, identifier, object_value
from .hardware import number


def capture(store, db, reason, correlation_id=None, payload=None):
    from .storage import canonical, uid, utcnow

    if reason != "manual" and reason not in ERROR_HELP:
        raise ValueError("Snapshot reason must be a registered diagnostic code")
    now, snapshot_id = utcnow(), uid()
    context = {
        "schema_version": 1,
        "captured_at": now,
        "reason": reason,
        "correlation_id": identifier(correlation_id),
    }
    if payload is None:
        # Capture in the failure transaction before another request changes state.
        # No subprocess or network call can delay a failed request here.
        context["work_task_counts"] = [
            dict(row)
            for row in db.execute("SELECT status,COUNT(*) AS count FROM work_tasks GROUP BY status")
        ]
        context["recent_events"] = [
            dict(row)
            for row in db.execute(
                "SELECT code,correlation_id,created_at FROM diagnostic_events "
                "ORDER BY id DESC LIMIT 20"
            )
        ]
        run = db.execute(
            "SELECT id,status,error_code,updated_at FROM runs WHERE id=?", (correlation_id,)
        ).fetchone()
        if run:
            context["request"] = dict(run)
            if context["request"]["error_code"] not in ERROR_HELP:
                context["request"]["error_code"] = None
        executions = []
        for row in db.execute(
            "SELECT id,task_id,status,result,cleanup_pending,updated_at FROM work_executions "
            "WHERE id=? OR task_id=? ORDER BY updated_at DESC LIMIT 5",
            (correlation_id, correlation_id),
        ):
            item = dict(row)
            result = object_value(item.pop("result"))
            item["exit_code"] = number(result.get("exit_code"), 65535, -255)
            executions.append(item)
        context["executions"] = executions
        context["hardware"] = "not_sampled_in_failure_transaction"
    else:
        context["system"] = payload
    encoded = canonical(context)
    if len(encoded.encode()) > store.diagnostic_snapshot_bytes:
        context = {
            "schema_version": 1,
            "captured_at": now,
            "reason": reason,
            "correlation_id": identifier(correlation_id),
            "context_omitted": "snapshot_size_limit",
        }
        encoded = canonical(context)
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    db.execute(
        "INSERT INTO diagnostic_snapshots VALUES(?,?,?,?,?,?)",
        (snapshot_id, reason, identifier(correlation_id), now, digest, encoded),
    )
    db.execute(
        "DELETE FROM diagnostic_snapshots WHERE id NOT IN "
        "(SELECT id FROM diagnostic_snapshots ORDER BY rowid DESC LIMIT ?)",
        (store.diagnostic_snapshot_retention,),
    )
    return {"id": snapshot_id, "reason": reason, "captured_at": now, "sha256": digest}


def history(store):
    return store.all(
        "SELECT id,reason,correlation_id,captured_at,sha256 FROM diagnostic_snapshots "
        "ORDER BY rowid DESC LIMIT 100"
    )


def export_snapshots(store, budget=2 * 1024 * 1024):
    files = {}
    for row in store.all(
        "SELECT id,payload FROM diagnostic_snapshots ORDER BY rowid DESC LIMIT 100"
    ):
        size = len(row["payload"].encode())
        if size > budget:
            break
        files[f"desktop/snapshots/{row['id']}.json"] = row["payload"]
        budget -= size
    return files
