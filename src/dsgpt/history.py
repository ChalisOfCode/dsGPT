"""Atomic local import, source receipts, indexed search and explicit memory copies."""

import hashlib
import json
from uuid import UUID

from fastapi import HTTPException

from .history_archive import PARSER_VERSION, digest, select
from .memory import Memory, search_terms
from .storage import canonical, uid, utcnow


class History:
    def __init__(self, store):
        self.store = store

    def apply(self, archive, request_id, expected_sha256, source_ids=()):
        request_id = str(UUID(request_id))
        if archive["archive_sha256"] != expected_sha256:
            raise HTTPException(409, "Export changed since preview; preview it again")
        records = select(archive, source_ids)
        request_hash = digest([PARSER_VERSION, expected_sha256, sorted(set(source_ids))])
        now = utcnow()
        with self.store.transaction() as db:
            old = db.execute("SELECT * FROM history_batches WHERE id=?", (request_id,)).fetchone()
            if old:
                if old["request_hash"] != request_hash:
                    raise HTTPException(409, "Request ID was already used for a different import")
                return self._result(db, json.loads(old["result"]))
            result = {"batch_id": request_id, "archive_sha256": expected_sha256, "items": []}
            db.execute(
                "INSERT INTO history_batches VALUES(?,?,?,?,?)",
                (request_id, request_hash, expected_sha256, now, "{}"),
            )
            for record in records:
                existing = db.execute(
                    "SELECT conversation_id FROM history_sources "
                    "WHERE source_id=? AND source_sha256=?",
                    (record["source_id"], record["sha256"]),
                ).fetchone()
                removed = db.execute(
                    "SELECT 1 FROM history_tombstones WHERE source_id=?", (record["source_id"],)
                ).fetchone()
                if existing or removed:
                    result["items"].append(
                        {
                            "source_id": record["source_id"],
                            "conversation_id": existing[0] if existing else None,
                            "outcome": "blocked_removed_source" if removed else "duplicate",
                        }
                    )
                    continue
                chat_id = uid()
                created = record["created_at"] or now
                updated = record["updated_at"] or record["created_at"] or now
                db.execute(
                    "INSERT INTO conversations(id,title,created_at,updated_at) VALUES(?,?,?,?)",
                    (chat_id, record["title"], created, updated),
                )
                db.execute(
                    "INSERT INTO history_sources VALUES(?,?,?,?,?,?,?,?,?,?,?,?,0)",
                    (
                        chat_id,
                        record["source_id"],
                        record["sha256"],
                        record["title"],
                        record["created_at"],
                        record["updated_at"],
                        record["current_node"],
                        record["member"],
                        canonical(record["omissions"]),
                        PARSER_VERSION,
                        request_id,
                        now,
                    ),
                )
                for ordinal, message in enumerate(record["messages"], 1):
                    message_id = uid()
                    db.execute(
                        "INSERT INTO messages VALUES(?,?,?,?,?,?,?)",
                        (
                            message_id,
                            chat_id,
                            message["role"],
                            message["content"],
                            "completed",
                            ordinal,
                            message["created_at"] or created,
                        ),
                    )
                    db.execute(
                        "INSERT INTO history_messages VALUES(?,?,?,?)",
                        (
                            message_id,
                            message["source_node_id"],
                            message["created_at"],
                            hashlib.sha256(message["content"].encode()).hexdigest(),
                        ),
                    )
                result["items"].append(
                    {
                        "source_id": record["source_id"],
                        "conversation_id": chat_id,
                        "outcome": "imported",
                    }
                )
            db.execute(
                "UPDATE history_batches SET result=? WHERE id=?", (canonical(result), request_id)
            )
            return self._result(db, result)

    @staticmethod
    def _result(db, result):
        # A retry is a receipt, not permission to restore removed material.
        for item in result["items"]:
            item["removed"] = bool(
                db.execute(
                    "SELECT 1 FROM history_tombstones WHERE source_id=?", (item["source_id"],)
                ).fetchone()
            )
        return result

    def provenance(self, chat_id):
        row = self.store.one(
            "SELECT s.*,b.archive_sha256 FROM history_sources s "
            "JOIN history_batches b ON b.id=s.batch_id WHERE conversation_id=?",
            (chat_id,),
        )
        if not row:
            raise HTTPException(404, "Imported conversation not found")
        row["omissions"] = json.loads(row["omissions"])
        return row

    def list(self, limit=100, offset=0):
        return self.store.all(
            "SELECT conversation_id,source_id,source_sha256,source_title,imported_at,removed "
            "FROM history_sources ORDER BY imported_at,conversation_id LIMIT ? OFFSET ?",
            (limit, offset),
        )

    def search(self, query, hidden=False, limit=50, offset=0):
        terms = search_terms(query)
        if not terms:
            return []
        return self.store.all(
            "SELECT m.id AS message_id,m.conversation_id,m.role,m.created_at,m.ordinal,"
            "c.title,substr(m.content,1,600) AS excerpt,s.source_id,s.source_sha256,"
            "h.source_node_id FROM messages_fts f JOIN messages m ON m.rowid=f.rowid "
            "JOIN conversations c ON c.id=m.conversation_id "
            "LEFT JOIN history_messages h ON h.message_id=m.id "
            "LEFT JOIN history_sources s ON s.conversation_id=m.conversation_id "
            "WHERE messages_fts MATCH ? AND c.hidden=? AND (h.message_id IS NULL OR s.removed=0) "
            "ORDER BY rank,m.id LIMIT ? OFFSET ?",
            (terms, int(hidden), limit, offset),
        )

    def remove(self, chat_id):
        with self.store.transaction() as db:
            source = db.execute(
                "SELECT source_id FROM history_sources WHERE conversation_id=?", (chat_id,)
            ).fetchone()
            if not source:
                raise HTTPException(404, "Imported conversation not found")
            source_id = source[0]
            active = db.execute(
                "SELECT 1 FROM runs r JOIN history_sources s "
                "ON s.conversation_id=r.conversation_id "
                "WHERE s.source_id=? AND r.status IN ('queued','running')",
                (source_id,),
            ).fetchone()
            if active:
                raise HTTPException(409, "Wait for or cancel active runs before removing history")
            if db.execute(
                "SELECT 1 FROM history_tombstones WHERE source_id=?", (source_id,)
            ).fetchone():
                return {"removed": True, "source_id": source_id}
            now = utcnow()
            db.execute("INSERT INTO history_tombstones VALUES(?,?)", (source_id, now))
            db.execute(
                "UPDATE messages SET content='' WHERE id IN ("
                "SELECT h.message_id FROM history_messages h JOIN messages m ON m.id=h.message_id "
                "JOIN history_sources s ON s.conversation_id=m.conversation_id "
                "WHERE s.source_id=?)",
                (source_id,),
            )
            # Keep a locally edited title and all locally added turns; clear source titles.
            db.execute(
                "UPDATE conversations SET title=CASE WHEN title=(SELECT source_title "
                "FROM history_sources WHERE conversation_id=conversations.id) "
                "THEN 'Removed imported chat' ELSE title END,revision=revision+1,updated_at=? "
                "WHERE id IN (SELECT conversation_id FROM history_sources WHERE source_id=?)",
                (now, source_id),
            )
            db.execute(
                "UPDATE history_sources SET removed=1,source_title=NULL WHERE source_id=?",
                (source_id,),
            )
        return {"removed": True, "source_id": source_id}

    def promote(self, message_id, request_id, title, task_id=None):
        # A single transaction covers source validation and the new memory receipt.
        memory = Memory(self.store)
        memory.check_project(task_id)
        with self.store.transaction() as db:
            row = db.execute(
                "SELECT m.*,h.source_node_id,h.content_sha256,s.source_id,s.removed "
                "FROM history_messages h JOIN messages m ON m.id=h.message_id "
                "JOIN history_sources s ON s.conversation_id=m.conversation_id WHERE m.id=?",
                (message_id,),
            ).fetchone()
            if not row:
                raise HTTPException(404, "Imported message not found")
            if row["removed"]:
                raise HTTPException(410, "Imported source was removed")
            if len(row["content"]) > 8000:
                raise HTTPException(422, "Message exceeds the 8000-character memory limit")
            source = canonical(
                {
                    "kind": "chatgpt-import",
                    "source_id": row["source_id"],
                    "source_node_id": row["source_node_id"],
                    "sha256": row["content_sha256"],
                    "conversation_id": row["conversation_id"],
                    "message_id": message_id,
                }
            )
            return memory.create(title, row["content"], task_id, source, request_id, transaction=db)
