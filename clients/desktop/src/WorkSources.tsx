import { useEffect, useRef, useState } from "react";
import { Client, openSource } from "./transport";

interface Source {
  source_id: string;
  generation?: number;
  url: string;
  status: string;
  error_code: string | null;
  title: string;
  final_url: string | null;
  retrieved_at: string | null;
  published_at: string | null;
  content_sha256: string | null;
  text_sha256: string | null;
  text_truncated: boolean;
  characters: number;
}
interface Excerpt extends Source {
  text?: string;
  offset?: number;
  next_offset?: number;
  error?: string;
}

export function WorkSources({
  client,
  taskId,
  revision,
  active,
  manageable,
  status,
  changed,
}: {
  client: Client;
  taskId: string;
  revision: number;
  active: boolean;
  manageable: boolean;
  status: string;
  changed: () => void;
}) {
  const [sources, setSources] = useState<Source[]>([]);
  const [limit, setLimit] = useState(50),
    [more, setMore] = useState(false);
  const [excerpt, setExcerpt] = useState<Excerpt | null>(null);
  const [error, setError] = useState(""),
    [loading, setLoading] = useState(false);
  const scope = useRef(0);
  useEffect(() => {
    scope.current++;
    setPending(null);
    setChanging(false);
    setAppliedRevision(0);
    setSources([]);
    setError("");
    return () => {
      scope.current++;
    };
  }, [client, taskId]);
  const [changing, setChanging] = useState(false);
  const [appliedRevision, setAppliedRevision] = useState(0);
  const [pending, setPending] = useState<{
    source: string;
    action: "refresh" | "remove";
    revision: number;
    request_id: string;
  } | null>(null);
  const read = useRef<AbortController | null>(null);
  useEffect(() => () => read.current?.abort(), []);
  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    void (async () => {
      try {
        const rows: Source[] = [];
        for (let offset = 0; offset < limit; offset += 50) {
          const batch = await client.request<Source[]>(
            `/v1/work/tasks/${taskId}/sources?limit=50&offset=${offset}`,
            "GET",
            undefined,
            controller.signal,
          );
          rows.push(...batch);
          if (batch.length < 50) break;
        }
        if (!controller.signal.aborted) {
          setSources(rows);
          setMore(rows.length >= limit);
        }
      } catch (e) {
        if (!controller.signal.aborted) setError(String(e));
      }
    })();
    return () => controller.abort();
  }, [client, taskId, revision, appliedRevision, active, limit]);

  async function change(request: NonNullable<typeof pending>) {
    if (changing) return;
    const epoch = scope.current;
    setChanging(true);
    setError("");
    setPending(request);
    read.current?.abort();
    setExcerpt(null);
    setLoading(false);
    try {
      const result = await client.request<{ revision: number }>(
        `/v1/work/tasks/${taskId}/sources/${request.source}/actions`,
        "POST",
        {
          action: request.action,
          revision: request.revision,
          request_id: request.request_id,
        },
      );
      if (scope.current !== epoch) return;
      setAppliedRevision(result.revision);
      setPending(null);
      changed();
    } catch (e) {
      if (scope.current !== epoch) return;
      setError(
        `${String(e)}. Retry this same request or clear it and review the current state.`,
      );
      changed();
    } finally {
      if (scope.current === epoch) setChanging(false);
    }
  }
  function begin(source: string, action: "refresh" | "remove") {
    void change({
      source,
      action,
      revision: Math.max(revision, appliedRevision),
      request_id: crypto.randomUUID(),
    });
  }
  useEffect(() => {
    read.current?.abort();
    setExcerpt(null);
    setLoading(false);
  }, [revision, client, taskId]);

  async function show(source: string, offset = 0) {
    read.current?.abort();
    const controller = new AbortController();
    read.current = controller;
    setLoading(true);
    setError("");
    try {
      const result = await client.request<Excerpt>(
        `/v1/work/tasks/${taskId}/sources/${source}?offset=${offset}`,
        "GET",
        undefined,
        controller.signal,
      );
      if (!controller.signal.aborted) setExcerpt(result);
    } catch (e) {
      if (!controller.signal.aborted) setError(String(e));
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }
  return (
    <section aria-label="Work reference sources">
      <h3>Reference sources</h3>
      <p>
        Pages are read when drafting starts or resumes. Saved snapshots are
        reused. Page text may be incomplete or incorrect; publication dates are
        unverified.
      </p>
      <p>
        Refresh clears the saved snapshot and fetches the page on the next start
        or resume. Remove clears the snapshot and excludes it from future source
        reads. Earlier receipts, summaries and generated files may still contain
        copied text.
      </p>
      {pending && (
        <div role="region" aria-label="Pending source change">
          <p>
            {pending.action} {pending.source}: response not confirmed.
          </p>
          <button disabled={changing} onClick={() => void change(pending)}>
            Retry same source change
          </button>
          <button
            disabled={changing}
            onClick={() => {
              setPending(null);
              setError("");
              changed();
            }}
          >
            Clear source request and reload
          </button>
        </div>
      )}
      {error && <p role="alert">{error}</p>}
      {!sources.length && <p>No reference sources added.</p>}
      {sources.map((s) => (
        <details key={s.source_id}>
          <summary>
            {s.source_id} · {s.status} · {s.title}
          </summary>
          <p className="content">
            Requested URL: {s.url} · snapshot generation {s.generation ?? 1}
          </p>
          {manageable && (
            <div>
              <button
                disabled={
                  changing ||
                  !!pending ||
                  ["queued", "running", "completed"].includes(status)
                }
                onClick={() => begin(s.source_id, "refresh")}
              >
                {s.status === "removed" ? "Restore and refresh" : "Refresh"}{" "}
                {s.source_id}
              </button>
              <button
                disabled={
                  changing ||
                  !!pending ||
                  s.status === "removed" ||
                  ["queued", "running"].includes(status)
                }
                onClick={() => begin(s.source_id, "remove")}
              >
                Remove {s.source_id}
              </button>
            </div>
          )}
          {s.final_url && <p className="content">Read URL: {s.final_url}</p>}
          {s.error_code && (
            <p>
              Read failed: {s.error_code}. Pause the task to retry failed reads.
            </p>
          )}
          {s.status === "retrieved" && (
            <>
              <p>
                Retrieved: {s.retrieved_at} · {s.characters} characters
                {s.text_truncated ? " · text was truncated" : ""}
              </p>
              {s.published_at && (
                <p>
                  Publication date from page metadata (unverified):{" "}
                  {s.published_at}
                </p>
              )}
              <p className="content">
                Content SHA-256: {s.content_sha256}
                <br />
                Extracted text SHA-256: {s.text_sha256}
              </p>
              <button onClick={() => void show(s.source_id)} disabled={loading}>
                Read saved {s.source_id}
              </button>
              <button
                onClick={() =>
                  void openSource(s.final_url || s.url).catch((e) =>
                    setError(String(e)),
                  )
                }
              >
                Open source {s.source_id}
              </button>
            </>
          )}
        </details>
      ))}
      {more && (
        <button onClick={() => setLimit((n) => n + 50)}>
          Load more sources
        </button>
      )}
      {excerpt && (
        <div role="region" aria-label="Saved source text">
          <h4>
            {excerpt.source_id} · {excerpt.title}
          </h4>
          <p>
            Characters {excerpt.offset ?? 0}–{excerpt.next_offset ?? 0} of{" "}
            {excerpt.characters}. This is saved text, not the live page.
          </p>
          {excerpt.error ? <p>{excerpt.error}</p> : <pre>{excerpt.text}</pre>}
          <button
            disabled={loading || !excerpt.offset}
            onClick={() => void show(excerpt.source_id)}
          >
            From beginning
          </button>
          <button
            disabled={
              loading ||
              (excerpt.next_offset ?? excerpt.characters) >= excerpt.characters
            }
            onClick={() => void show(excerpt.source_id, excerpt.next_offset)}
          >
            Next excerpt
          </button>
          <button
            onClick={() => {
              read.current?.abort();
              setLoading(false);
              setExcerpt(null);
            }}
          >
            Close saved text
          </button>
        </div>
      )}
    </section>
  );
}
