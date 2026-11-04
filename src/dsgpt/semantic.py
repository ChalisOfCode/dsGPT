"""Durable opt-in local retrieval with transactional invalidation and live scope checks."""

import asyncio
import heapq
import json

from fastapi import HTTPException

from .embeddings import ASSET_IDS, MODEL_ID, EmbeddingError, LocalEmbedder

MAX_INDEX_CHUNKS = 100000


class SemanticIndex:
    def __init__(self, store, downloads, factory=LocalEmbedder):
        self.store, self.downloads, self.factory = store, downloads, factory
        self.engine = None
        self.error = None
        self.compute_lock = asyncio.Lock()
        self.worker = None
        self.wake = asyncio.Event()

    def settings(self):
        return self.store.one("SELECT * FROM semantic_settings WHERE id=1")

    def status(self):
        config = self.settings()
        return {
            "enabled": bool(config["enabled"]),
            "history_enabled": bool(config["history_enabled"]),
            "attachments_enabled": bool(config["attachments_enabled"]),
            "revision": config["revision"],
            "model_id": MODEL_ID,
            "language": "English",
            "device": "CPU",
            "dimensions": 384,
            "loaded": self.engine is not None,
            "error_code": self.error,
            "asset_ids": list(ASSET_IDS),
            "max_chunks": MAX_INDEX_CHUNKS,
            "chunks": self.store.one("SELECT count(*) AS n FROM semantic_chunks")["n"],
            "sources": self.store.all(
                "SELECT kind,status,count(*) AS count,sum(omitted_chars) AS omitted_chars "
                "FROM semantic_jobs GROUP BY kind,status ORDER BY kind,status"
            ),
            "automatic_history_context": False,
        }

    def _engine(self):
        if self.engine is None:
            try:
                self.engine = self.factory(self.downloads)
            except EmbeddingError:
                raise
            except Exception as exc:
                raise EmbeddingError("embedding_protocol_error") from exc
        return self.engine

    async def _compute(self, function):
        # A cancelled HTTP request does not cancel a native inference call. Keep the
        # serialization grant until that call actually ends; never overlap/unload it.
        async with self.compute_lock:
            self.downloads.busy_assets.update(ASSET_IDS)
            operation = asyncio.create_task(asyncio.to_thread(function))
            try:
                return await asyncio.shield(operation)
            except asyncio.CancelledError:
                await asyncio.gather(operation, return_exceptions=True)
                raise
            finally:
                self.downloads.busy_assets.difference_update(ASSET_IDS)

    async def configure(self, revision, enabled, history_enabled, attachments_enabled=None):
        if attachments_enabled is None:
            attachments_enabled = bool(self.settings()["attachments_enabled"]) if enabled else False
        if not enabled and (history_enabled or attachments_enabled):
            raise HTTPException(422, "Enable semantic retrieval before indexing history")
        if self.settings()["revision"] != revision:
            raise HTTPException(409, "Retrieval settings changed; reload before editing")
        if enabled:
            try:
                await self._compute(self._engine)
            except EmbeddingError as exc:
                self.error = str(exc)
                raise HTTPException(409, {"code": str(exc)}) from exc
        with self.store.transaction() as db:
            changed = db.execute(
                "UPDATE semantic_settings SET enabled=?,history_enabled=?,attachments_enabled=?,"
                "revision=revision+1 "
                "WHERE id=1 AND revision=?",
                (enabled, history_enabled, attachments_enabled, revision),
            ).rowcount
            if not changed:
                raise HTTPException(409, "Retrieval settings changed; reload before editing")
            if not enabled:
                db.execute("DELETE FROM semantic_chunks")
                db.execute("UPDATE semantic_jobs SET status='pending',error_code=NULL")
            elif not history_enabled:
                db.execute("DELETE FROM semantic_chunks WHERE kind='history'")
                db.execute(
                    "UPDATE semantic_jobs SET status='pending',error_code=NULL WHERE kind='history'"
                )
            if not attachments_enabled:
                db.execute("DELETE FROM semantic_chunks WHERE kind='attachment'")
                db.execute(
                    "UPDATE semantic_jobs SET status='pending',error_code=NULL "
                    "WHERE kind='attachment'"
                )
            # Explicit owner save is also a retry for failed/capacity-limited sources.
            db.execute(
                "UPDATE semantic_jobs SET status='pending',error_code=NULL WHERE status='failed'"
            )
        self.error = None
        if not enabled:
            await self._compute(lambda: setattr(self, "engine", None))
        self.wake.set()
        return self.status()

    def _source(self, db, kind, identifier):
        if kind == "memory":
            row = db.execute("SELECT * FROM memories WHERE id=?", (identifier,)).fetchone()
            if row:
                value = dict(row)
                return value, value["title"] + "\n" + value["content"]
        elif kind == "attachment":
            row = db.execute(
                "SELECT a.*,a.name AS title,m.conversation_id,c.title AS conversation_title,"
                "c.hidden,d.extraction FROM message_attachments a "
                "JOIN messages m ON m.id=a.message_id "
                "JOIN conversations c ON c.id=m.conversation_id "
                "LEFT JOIN attachment_documents d ON d.id=a.id "
                "WHERE a.id=? AND a.removed=0 AND a.text!=''",
                (identifier,),
            ).fetchone()
            if row:
                value = dict(row)
                return value, value["text"]
        else:
            row = db.execute(
                "SELECT m.*,c.title,c.hidden,h.source_node_id,h.content_sha256 "
                "FROM messages m JOIN conversations c ON c.id=m.conversation_id "
                "LEFT JOIN history_messages h ON h.message_id=m.id "
                "WHERE m.id=? AND m.status='completed' AND m.content!='' "
                "AND m.role IN ('user','assistant')",
                (identifier,),
            ).fetchone()
            if row:
                value = dict(row)
                return value, value["content"]
        return None

    async def process_one(self):
        config = self.settings()
        if not config["enabled"]:
            return False
        job = self.store.one(
            "SELECT * FROM semantic_jobs WHERE status='pending' AND (kind='memory' "
            "OR (kind='history' AND ?) OR (kind='attachment' AND ?)) "
            "ORDER BY CASE kind WHEN 'memory' THEN 0 ELSE 1 END,source_id LIMIT 1",
            (config["history_enabled"], config["attachments_enabled"]),
        )
        if not job:
            return False
        with self.store.connect() as db:
            source = self._source(db, job["kind"], job["source_id"])
        if not source:
            return False
        chunks, omitted = await self._compute(lambda: self._engine().document(source[1]))
        with self.store.transaction() as db:
            current = db.execute("SELECT * FROM semantic_settings WHERE id=1").fetchone()
            pending = db.execute(
                "SELECT generation FROM semantic_jobs WHERE kind=? AND source_id=?",
                (job["kind"], job["source_id"]),
            ).fetchone()
            if (
                current["revision"] != config["revision"]
                or not pending
                or pending[0] != job["generation"]
            ):
                return True  # Source/configuration changed during native inference; discard.
            count = db.execute("SELECT count(*) FROM semantic_chunks").fetchone()[0]
            if count + len(chunks) > MAX_INDEX_CHUNKS:
                db.execute(
                    "UPDATE semantic_jobs SET status='failed',error_code='index_capacity' "
                    "WHERE kind=? AND source_id=?",
                    (job["kind"], job["source_id"]),
                )
                return True
            db.executemany(
                "INSERT INTO semantic_chunks VALUES(?,?,?,?,?,?,?)",
                [
                    (job["kind"], job["source_id"], n, job["generation"], start, end, vector)
                    for n, (start, end, vector) in enumerate(chunks)
                ],
            )
            db.execute(
                "UPDATE semantic_jobs SET status='indexed',omitted_chars=?,error_code=NULL "
                "WHERE kind=? AND source_id=?",
                (omitted, job["kind"], job["source_id"]),
            )
        return True

    async def start(self):
        self.worker = asyncio.create_task(self._loop())

    async def stop(self):
        if self.worker:
            self.worker.cancel()
            await asyncio.gather(self.worker, return_exceptions=True)
            self.worker = None
        await self._compute(lambda: setattr(self, "engine", None))

    async def _loop(self):
        while True:
            self.wake.clear()
            if not self.error:
                try:
                    if await self.process_one():
                        await asyncio.sleep(0)  # Yield between bounded source batches.
                        continue
                except EmbeddingError as exc:
                    self.error = str(exc)
                except Exception:
                    self.error = "embedding_index_failed"
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=1)
            except TimeoutError:
                pass

    def _rank(self, query, kind, task_id, hidden, limit):
        import numpy as np

        vector = np.frombuffer(self._engine().query(query), dtype="<f4")
        join = (
            "JOIN memories m ON m.id=c.source_id WHERE c.kind='memory' AND m.task_id IS ?"
            if kind == "memory"
            else "JOIN messages m ON m.id=c.source_id "
            "JOIN conversations v ON v.id=m.conversation_id "
            "WHERE c.kind='history' AND m.status='completed' AND m.content!='' "
            "AND (v.hidden=0 OR ?)"
        )
        if kind == "attachment":
            join = (
                "JOIN message_attachments a ON a.id=c.source_id "
                "JOIN messages m ON m.id=a.message_id "
                "JOIN conversations v ON v.id=m.conversation_id "
                "WHERE c.kind='attachment' AND a.removed=0 AND a.text!='' "
                "AND (v.hidden=0 OR ?)"
            )
        with self.store.connect() as db:
            cursor = db.execute(
                "SELECT c.* FROM semantic_chunks c " + join + " ORDER BY c.source_id,c.ordinal",
                (task_id if kind == "memory" else hidden,),
            )
            best = []
            sequence = 0
            while rows := cursor.fetchmany(256):
                matrix = np.frombuffer(b"".join(r["vector"] for r in rows), dtype="<f4")
                # A simple reduction avoids NumPy/BLAS starting an extra CPU thread pool.
                scores = (matrix.reshape(-1, 384) * vector).sum(axis=1)
                for row, score in zip(rows, scores, strict=True):
                    if not np.isfinite(score):
                        continue
                    entry = (float(score), sequence, dict(row))
                    sequence += 1
                    if len(best) < limit:
                        heapq.heappush(best, entry)
                    elif score > best[0][0]:
                        heapq.heapreplace(best, entry)
        return sorted(best, reverse=True)

    async def search(self, query, kind="memory", task_id=None, hidden=False, limit=8):
        if kind not in {"memory", "history", "attachment"} or kind != "memory" and task_id:
            raise HTTPException(422, "Invalid retrieval scope")
        config = self.settings()
        if not config["enabled"] or (
            kind == "history"
            and not config["history_enabled"]
            or kind == "attachment"
            and not config["attachments_enabled"]
        ):
            raise HTTPException(409, "Semantic retrieval is disabled for this scope")
        try:
            ranked = await self._compute(lambda: self._rank(query, kind, task_id, hidden, limit))
        except EmbeddingError as exc:
            self.error = str(exc)
            raise HTTPException(503, {"code": str(exc)}) from exc
        except Exception as exc:
            self.error = "embedding_query_failed"
            raise HTTPException(503, {"code": self.error}) from exc
        if self.settings()["revision"] != config["revision"]:
            raise HTTPException(409, "Retrieval settings changed; retry the query")
        results = []
        # Re-read live sources after the worker yields. Deleted/edited/private-scope
        # rows cannot escape through cached vectors or an in-flight result.
        with self.store.connect() as db:
            db.execute("BEGIN")
            for score, _, chunk in ranked:
                job = db.execute(
                    "SELECT generation,status FROM semantic_jobs WHERE kind=? AND source_id=?",
                    (kind, chunk["source_id"]),
                ).fetchone()
                source = self._source(db, kind, chunk["source_id"])
                if not job or job[0] != chunk["generation"] or job[1] != "indexed" or not source:
                    continue
                value, text = source
                if kind == "memory" and value["task_id"] != task_id:
                    continue
                if kind != "memory" and value["hidden"] and not hidden:
                    continue
                record = {
                    "id": value["id"],
                    "kind": kind,
                    "title": value["title"],
                    "content": text[chunk["start"] : chunk["end"]],
                    "score": round(score, 6),
                    "start": chunk["start"],
                    "end": chunk["end"],
                    "partial": chunk["start"] != 0 or chunk["end"] != len(text),
                }
                if kind == "memory":
                    record.update(source=value["source"], revision=value["revision"])
                elif kind == "attachment":
                    record.update(
                        conversation_id=value["conversation_id"],
                        conversation_title=value["conversation_title"],
                        message_id=value["message_id"],
                        name=value["name"],
                        bytes=value["bytes"],
                        sha256=value["sha256"],
                        created_at=value["created_at"],
                        removed=False,
                    )
                    if value["extraction"]:
                        record["document"] = json.loads(value["extraction"])
                else:
                    record.update(
                        conversation_id=value["conversation_id"],
                        role=value["role"],
                        created_at=value["created_at"],
                        source_node_id=value["source_node_id"],
                        content_sha256=value["content_sha256"],
                    )
                results.append(record)
            join = (
                "JOIN memories m ON m.id=j.source_id WHERE j.kind='memory' AND m.task_id IS ?"
                if kind == "memory"
                else "JOIN messages m ON m.id=j.source_id "
                "JOIN conversations v ON v.id=m.conversation_id "
                "WHERE j.kind='history' AND (v.hidden=0 OR ?)"
            )
            if kind == "attachment":
                join = (
                    "JOIN message_attachments a ON a.id=j.source_id "
                    "JOIN messages m ON m.id=a.message_id "
                    "JOIN conversations v ON v.id=m.conversation_id "
                    "WHERE j.kind='attachment' AND a.removed=0 AND (v.hidden=0 OR ?)"
                )
            coverage = [
                dict(r)
                for r in db.execute(
                    "SELECT j.status,count(*) AS sources,sum(j.omitted_chars) AS omitted_chars "
                    "FROM semantic_jobs j " + join + " GROUP BY j.status",
                    (task_id if kind == "memory" else hidden,),
                )
            ]
        return {
            "method": "semantic",
            "model_id": MODEL_ID,
            "results": results,
            "coverage": coverage,
            "score_meaning": "Relative cosine similarity; not confidence or factual verification",
        }

    async def memories(self, query, task_id, byte_budget):
        response = await self.search(query, "memory", task_id)
        records, seen = [], set()
        for record in response["results"]:
            # This conservative floor is a retrieval heuristic, never a truth score.
            if record["id"] in seen or record["score"] < 0.50:
                continue
            # Prompt budgets may be smaller than an indexed chunk. Preserve exact
            # source offsets and disclose partial excerpts; never shorten user input.
            original = record["content"]
            record["content"] = ""
            overhead = len(json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode())
            excerpt = original.encode()[: max(0, byte_budget - overhead - 32)].decode(
                "utf-8", errors="ignore"
            )
            if not excerpt:
                continue
            record["content"] = excerpt
            record["end"] = record["start"] + len(excerpt)
            record["partial"] = record["partial"] or len(excerpt) != len(original)
            cost = len(json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode())
            if cost <= byte_budget:
                records.append(record)
                seen.add(record["id"])
                byte_budget -= cost
        return records
