import { useEffect, useState } from "react";
import { Client, openSource } from "./transport";
import { citationParts, type ResearchSources } from "./research";
import { terminal, type Message } from "./types";

export function ResearchReply({
  client,
  message,
}: {
  client: Client;
  message: Message;
}) {
  const [data, setData] = useState<ResearchSources | null>(null);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const active = !terminal(message.status);
  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      try {
        const result = await client.request<ResearchSources>(
          `/v1/runs/${message.run_id}/sources`,
        );
        if (live) {
          setData(result);
          setError("");
        }
      } catch {
        if (live)
          setError("Sources are unavailable. Try again when connected.");
      }
      if (live && active) timer = setTimeout(load, 1500);
    };
    void load();
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [client, message.run_id, active, retry]);
  const sources = data?.sources ?? [];
  return (
    <>
      <div className="content">
        {message.content
          ? citationParts(message.content, sources).map((part, i) =>
              part.source ? (
                <button
                  key={i}
                  className="citation"
                  onClick={() => setOpen(true)}
                  aria-label={`View source ${part.text}`}
                >
                  [{part.text}]
                </button>
              ) : (
                <span key={i}>
                  {part.text.replace(/\\([\\`*_[\]<>#])/g, "$1")}
                </span>
              ),
            )
          : active
            ? "Research is continuing on your PC…"
            : "Research ended without a completed answer."}
      </div>
      <button
        className="sources-toggle"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        {open ? "Hide sources" : "View sources"}
        {data ? ` (${sources.length})` : ""}
      </button>
      {open && (
        <section className="source-panel" aria-label="Research sources">
          <h3>Research sources</h3>
          <p>
            These pages were retrieved for this reply. Check the original page
            for important claims.
          </p>
          {!data && !error && <p>Loading sources…</p>}
          {error && (
            <p role="alert">
              {error}{" "}
              <button onClick={() => setRetry((n) => n + 1)}>
                Retry sources
              </button>
            </p>
          )}
          {data && !data.retrieval_complete && <p>Retrieving sources…</p>}
          {data?.warnings.length ? (
            <p>Some search engines or pages were unavailable.</p>
          ) : null}
          {sources.map((source) => (
            <div className="source-card" key={source.id}>
              <strong>
                {source.status === "retrieved"
                  ? `S${sources.filter((s) => s.status === "retrieved").findIndex((s) => s.id === source.id) + 1} · `
                  : ""}
                {source.title || "Source"}
              </strong>
              <div className="source-url">{source.final_url || source.url}</div>
              <small>
                {source.status === "retrieved"
                  ? `Retrieved ${source.retrieved_at ?? ""}`
                  : source.status === "pending"
                    ? "Retrieval pending"
                    : "This page could not be read"}
              </small>
              {source.status === "retrieved" && (
                <>
                  <button
                    onClick={() =>
                      openSource(source.final_url || source.url).catch(() =>
                        setError(
                          "This source could not be opened in your browser.",
                        ),
                      )
                    }
                  >
                    Open source
                  </button>
                  <details>
                    <summary>Source details</summary>
                    {source.published_at && (
                      <p>
                        Publication date from page metadata (unverified):{" "}
                        {source.published_at}
                      </p>
                    )}
                    <p className="source-url">
                      Content SHA-256: {source.content_sha256}
                    </p>
                  </details>
                </>
              )}
            </div>
          ))}
        </section>
      )}
    </>
  );
}
