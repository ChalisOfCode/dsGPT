"""User-declared public reference snapshots. Model tools read stored data only."""

import hashlib
import json
import re

from fastapi import HTTPException

from .storage import canonical, utcnow
from .web_retrieval import PublicReader, ResearchError, public_url


class WorkReferences:
    def __init__(self, store, reader=None):
        self.store = store
        self.reader = reader or PublicReader()

    @staticmethod
    def allow_links(db, task_id):
        return bool(
            db.execute(
                "SELECT 1 FROM work_research WHERE task_id=? AND follow_links=1 UNION ALL "
                "SELECT 1 FROM generation_options WHERE kind='work' AND id=? "
                "AND web_mode IN ('auto','on') LIMIT 1",
                (task_id, task_id),
            ).fetchone()
        )

    @staticmethod
    def normalize(urls):
        if urls is None:
            return []
        if not isinstance(urls, list) or len(urls) > 6:
            raise HTTPException(422, "Supply up to six public reference URLs per update")
        try:
            return list(dict.fromkeys(public_url(url) for url in urls))
        except ResearchError as exc:
            raise HTTPException(422, "Reference URL must be an allowed public HTTPS page") from exc

    @staticmethod
    def append(db, task_id, urls):
        number = db.execute(
            "SELECT COALESCE(MAX(CAST(substr(source_id,2) AS INTEGER)),0) "
            "FROM work_sources WHERE task_id=?",
            (task_id,),
        ).fetchone()[0]
        for url in urls:
            if db.execute(
                "SELECT 1 FROM work_sources WHERE task_id=? AND url=?", (task_id, url)
            ).fetchone():
                continue
            number += 1
            now = utcnow()
            db.execute(
                "INSERT INTO work_sources(task_id,source_id,url,status,document,error_code,"
                "created_at,updated_at) VALUES(?,?,?,'pending',NULL,NULL,?,?)",
                (task_id, f"S{number}", url, now, now),
            )

    def counts(self, task_id):
        counts = {"pending": 0, "retrieved": 0, "failed": 0}
        for row in self.store.all(
            "SELECT status,COUNT(*) AS n FROM work_sources WHERE task_id=? GROUP BY status",
            (task_id,),
        ):
            counts[row["status"]] = row["n"]
        return {"total": sum(counts.values()), **counts}

    @staticmethod
    def public(row, include_text=False):
        document = json.loads(row["document"]) if row["document"] else {}
        text = document.get("text", "")
        result = {
            "source_id": row["source_id"],
            "generation": row["generation"],
            "url": row["url"],
            "status": row["status"],
            "error_code": row["error_code"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "title": document.get("title", row["url"]),
            "final_url": document.get("final_url"),
            "retrieved_at": document.get("retrieved_at"),
            "published_at": document.get("published_at"),
            "content_sha256": document.get("content_sha256"),
            "text_sha256": document.get("text_sha256"),
            "text_truncated": document.get("text_truncated", False),
            "characters": len(text),
        }
        if include_text:
            result["text"] = text
        return result

    def list(self, task_id, limit=50, offset=0):
        return [
            self.public(row)
            for row in self.store.all(
                "SELECT * FROM work_sources WHERE task_id=? "
                "ORDER BY CAST(substr(source_id,2) AS INTEGER) LIMIT ? OFFSET ?",
                (task_id, limit, offset),
            )
        ]

    def pending(self, task_id):
        return self.store.one(
            "SELECT * FROM work_sources WHERE task_id=? AND status='pending' "
            "ORDER BY CAST(substr(source_id,2) AS INTEGER) LIMIT 1",
            (task_id,),
        )

    async def fetch(self, source):
        try:
            document = await self.reader.read(source["url"])
            with self.store.connect() as db:
                permission = self.allow_links(db, source["task_id"])
            if not permission:
                document.pop("links", None)
            else:
                links = []
                for candidate in document.get("links", [])[:60]:
                    try:
                        links.append(public_url(candidate))
                    except ResearchError:
                        pass
                document["links"] = list(dict.fromkeys(links))
            document["text_sha256"] = hashlib.sha256(document["text"].encode()).hexdigest()
            return document, None
        except ResearchError as exc:
            return None, str(exc)

    @staticmethod
    def save(db, task_id, source_id, document, error):
        status = "retrieved" if document is not None else "failed"
        db.execute(
            "UPDATE work_sources SET status=?,document=?,error_code=?,updated_at=? "
            "WHERE task_id=? AND source_id=? AND status='pending'",
            (
                status,
                canonical(document) if document is not None else None,
                error,
                utcnow(),
                task_id,
                source_id,
            ),
        )
        return {"source_id": source_id, "status": status, "error_code": error}

    @staticmethod
    def tool_list(db, task_id, offset):
        rows = db.execute(
            "SELECT * FROM work_sources WHERE task_id=? "
            "AND status!='removed' ORDER BY CAST(substr(source_id,2) AS INTEGER) LIMIT 10 OFFSET ?",
            (task_id, offset),
        ).fetchall()
        total = db.execute(
            "SELECT COUNT(*) FROM work_sources WHERE task_id=? AND status!='removed'", (task_id,)
        ).fetchone()[0]
        return {
            "sources": [
                {
                    "source_id": r["source_id"],
                    "generation": r["generation"],
                    "status": r["status"],
                    "title": WorkReferences.public(r)["title"][:160],
                    "url": r["url"][:180],
                    "url_truncated": len(r["url"]) > 180,
                }
                for r in rows
            ],
            "total": total,
            "offset": offset,
            "next_offset": offset + len(rows),
        }

    @staticmethod
    def read(db, task_id, source_id, offset=0):
        row = db.execute(
            "SELECT * FROM work_sources WHERE task_id=? AND source_id=?", (task_id, source_id)
        ).fetchone()
        if not row:
            return {"error": "source_not_found"}
        metadata = WorkReferences.public(row)
        if row["status"] != "retrieved":
            return {**metadata, "error": "source_not_retrieved"}
        text = json.loads(row["document"])["text"]
        excerpt = text[offset:].encode()[:3000].decode("utf-8", errors="ignore")
        result = {
            **metadata,
            "text": excerpt,
            "offset": offset,
            "next_offset": offset + len(excerpt),
        }
        if WorkReferences.allow_links(db, task_id):
            result["links"] = [
                {"index": i, "url": url}
                for i, url in enumerate(json.loads(row["document"]).get("links", [])[:60])
            ]
        return result

    @staticmethod
    def find(db, task_id, source_id, query, offset=0):
        row = db.execute(
            "SELECT * FROM work_sources WHERE task_id=? AND source_id=?",
            (task_id, source_id),
        ).fetchone()
        if not row or row["status"] != "retrieved":
            return {"error": "source_not_retrieved"}
        text = json.loads(row["document"])["text"]
        matches = []
        for match in re.compile(re.escape(query), re.IGNORECASE).finditer(text, offset):
            matches.append(
                {
                    "offset": match.start(),
                    "excerpt": text[max(0, match.start() - 80) : match.end() + 160],
                }
            )
            if len(matches) == 6:
                break
        return {
            **WorkReferences.public(row),
            "matches": matches,
            "next_offset": matches[-1]["offset"] + len(query) if len(matches) == 6 else None,
        }

    @staticmethod
    def export(db, task_id):
        return [
            WorkReferences.public(row, include_text=True)
            for row in db.execute(
                "SELECT * FROM work_sources WHERE task_id=? "
                "ORDER BY CAST(substr(source_id,2) AS INTEGER)",
                (task_id,),
            )
        ]
