"""Read-only public rendering. Browser has no network; host brokers bounded public GETs."""

import asyncio
import base64
import hashlib
import json
from pathlib import Path
from urllib.parse import urljoin

import httpx

from . import browser_worker
from .downloads import PublicHTTPS
from .storage import canonical, uid, utcnow
from .web_retrieval import ResearchError, limited_body, public_url, validate_public_request

POLL = """import json,pathlib
p=pathlib.Path('/work/.dsgpt-browser/bridge')
rows=[]
for f in sorted(p.glob('*.request'))[:32]:
 if not f.with_suffix('.response').exists() and f.stat().st_size<8192:
  rows.append(json.loads(f.read_text()))
print(json.dumps(rows))"""
RESPOND = """import json,pathlib,sys
value=json.load(sys.stdin)
p=pathlib.Path('/work/.dsgpt-browser/bridge')/str(int(value['id']))
t=p.with_suffix('.tmp');t.write_text(json.dumps(value['response']))
t.replace(p.with_suffix('.response'))"""


class PublicBrowser:
    def __init__(self, store, builds, transport_factory=None):
        self.store, self.builds = store, builds
        self.transport_factory = transport_factory or (
            lambda: PublicHTTPS(validator=validate_public_request)
        )

    async def resource(self, raw):
        url = public_url(raw)
        async with asyncio.timeout(15):
            async with httpx.AsyncClient(
                transport=self.transport_factory(),
                trust_env=False,
                follow_redirects=False,
                timeout=10,
                headers={"Accept-Encoding": "identity"},
            ) as client:
                for _attempt in range(6):
                    client.cookies.clear()
                    async with client.stream("GET", public_url(url)) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            target = public_url(urljoin(url, response.headers.get("location", "")))
                            return b"", [{"name": "Location", "value": target}], url, 302
                        if response.status_code != 200:
                            raise ResearchError("research_resource_unavailable")
                        body = await limited_body(response, 2 * 1024**2)
                        content_type = response.headers.get(
                            "content-type", "application/octet-stream"
                        )
                        if len(content_type) > 200 or any(ord(c) < 32 for c in content_type):
                            raise ResearchError("research_resource_type_invalid")
                        headers = [{"name": "Content-Type", "value": content_type}]
                        if response.headers.get("access-control-allow-origin") == "*":
                            headers.append({"name": "Access-Control-Allow-Origin", "value": "*"})
                        return body, headers, url, 200
        raise ResearchError("research_too_many_redirects")

    async def render(self, raw):
        url = public_url(raw)
        if not self.builds.ready or not self.builds.sandbox:
            raise ResearchError("research_browser_tools_not_ready")
        if self.builds.lock.locked():
            raise ResearchError("research_browser_tools_busy")
        async with self.builds.lock:
            identifier, now = uid(), utcnow()
            with self.store.transaction() as db:
                db.execute(
                    "INSERT INTO work_executions(id,action,snapshot_sha256,image_id,status,"
                    "created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                    (
                        identifier,
                        '{"tool":"public_browser_read"}',
                        hashlib.sha256(url.encode()).hexdigest(),
                        self.builds.image,
                        "running",
                        now,
                        now,
                    ),
                )
            resources, seen, total = [], set(), 0

            async def broker(name):
                nonlocal total
                sandbox = self.builds.sandbox
                while True:
                    code, out, _, _ = await sandbox.cli(
                        ["container", "exec", "--", name, "python3", "-I", "-c", POLL],
                        timeout=5,
                        limit=65536,
                    )
                    if code:
                        await asyncio.sleep(0.1)
                        continue
                    rows = json.loads(out)
                    if not isinstance(rows, list) or len(rows) > 32:
                        raise ResearchError("research_invalid_browser_request")
                    for row in rows:
                        number = row.get("id")
                        if type(number) is not int or not 1 <= number <= 32 or number in seen:
                            continue
                        seen.add(number)
                        result = {"error": "resource_blocked"}
                        try:
                            if row.get("method") != "GET" or total >= 8 * 1024**2:
                                raise ResearchError("research_browser_budget_exceeded")
                            body, headers, final, status = await self.resource(row.get("url"))
                            total += len(body)
                            if total > 8 * 1024**2:
                                raise ResearchError("research_browser_budget_exceeded")
                            result = {
                                "body": base64.b64encode(body).decode(),
                                "headers": headers,
                                "status": status,
                            }
                            resources.append(
                                {
                                    "url": public_url(row["url"]),
                                    "final_url": final,
                                    "bytes": len(body),
                                    "sha256": hashlib.sha256(body).hexdigest(),
                                }
                            )
                        except Exception:
                            # Browser-controlled URLs are untrusted. No address, protocol, DNS,
                            # size or transport failure may fall back to a direct browser request.
                            pass
                        await sandbox.checked(
                            ["container", "exec", "-i", "--", name, "python3", "-I", "-c", RESPOND],
                            data=canonical({"id": number, "response": result}).encode(),
                            timeout=5,
                        )
                    await asyncio.sleep(0.1)

            files = []
            for name, content in {
                ".dsgpt-browser/worker.py": Path(browser_worker.__file__).read_text(),
                ".dsgpt-browser/request.json": canonical({"public_url": url, "steps": []}),
            }.items():
                files.append(
                    {
                        "path": name,
                        "content": content,
                        "sha256": hashlib.sha256(content.encode()).hexdigest(),
                    }
                )
            try:
                output = await self.builds.sandbox.execute(
                    identifier,
                    files,
                    ["/usr/bin/python3", "-I", ".dsgpt-browser/worker.py"],
                    [".dsgpt-browser/result.json"],
                    90,
                    broker=broker,
                )
                if output["exit_code"] != 0 or len(output["artifacts"]) != 1:
                    raise ResearchError("research_browser_render_failed")
                payload = output["artifacts"][0]["content"]
                if len(payload) > 100000:
                    raise ResearchError("research_browser_output_too_large")
                page = json.loads(payload)
                text = page["text"]
                if not isinstance(text, str) or not text.strip() or len(text) > 12000:
                    raise ResearchError("research_no_readable_content")
                links = []
                for candidate in page.get("links", [])[:60]:
                    try:
                        links.append(public_url(candidate))
                    except ResearchError:
                        pass
                with self.store.transaction() as db:
                    db.execute(
                        "UPDATE work_executions SET status='completed',cleanup_pending=0,"
                        "result=?,updated_at=? WHERE id=?",
                        ('{"rendered":true}', utcnow(), identifier),
                    )
                return {
                    "url": url,
                    "final_url": public_url(page["url"]),
                    "text": text,
                    "title": str(page.get("title", ""))[:300],
                    "links": list(dict.fromkeys(links)),
                    "retrieved_at": utcnow(),
                    "published_at": None,
                    "published_at_source": None,
                    "content_type": "text/html",
                    "text_truncated": len(text) >= 12000,
                    "content_sha256": hashlib.sha256(text.encode()).hexdigest(),
                    "hash_basis": "rendered_text_utf8",
                    "resources": resources,
                    "rendering": "isolated_chromium_public_get_broker",
                    "notice": "Bounded read-only rendering; no login, cookies, POSTs or private "
                    "addresses. Some resources may be blocked.",
                }
            except Exception as exc:
                with self.store.transaction() as db:
                    db.execute(
                        "UPDATE work_executions SET status='failed',result=?,updated_at=? "
                        "WHERE id=?",
                        ('{"error":"public_browser_failed"}', utcnow(), identifier),
                    )
                if isinstance(exc, ResearchError):
                    raise
                raise ResearchError("research_browser_render_failed") from exc
