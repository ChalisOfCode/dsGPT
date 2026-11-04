import { useEffect, useRef, useState } from "react";
import { AttachmentHistory, AttachmentRecord } from "./Attachments";
import { HistoryImport } from "./HistoryImport";
import { Client } from "./transport";

interface Settings {
  revision: number;
  enabled: boolean;
  history_enabled: boolean;
  attachments_enabled: boolean;
  loaded: boolean;
  error_code: string | null;
  chunks: number;
  sources: unknown[];
}
interface Imported {
  conversation_id: string;
  source_id: string;
  source_title: string | null;
  removed: number;
  imported_at: string;
}
interface Match {
  id?: string;
  message_id?: string;
  conversation_id?: string;
  title: string;
  content?: string;
  excerpt?: string;
  score?: number;
  source?: string;
  kind?: string;
  conversation_title?: string;
  name?: string;
  bytes?: number;
  sha256?: string;
  created_at?: string;
  removed?: boolean;
  document?: AttachmentRecord["document"];
}

export function RecallPanel({
  client,
  active,
}: {
  client: Client;
  active: boolean;
}) {
  const [owner, setOwner] = useState(false),
    [chat, setChat] = useState(false);
  const [projects, setProjects] = useState<{ id: string; title: string }[]>([]);
  const [projectMore, setProjectMore] = useState(false);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [imports, setImports] = useState<Imported[]>([]),
    [more, setMore] = useState(false);
  const [query, setQuery] = useState(""),
    [scope, setScope] = useState("history");
  const [semantic, setSemantic] = useState(false),
    [hidden, setHidden] = useState(false);
  const [matches, setMatches] = useState<Match[]>([]),
    [coverage, setCoverage] = useState("");
  const [receipt, setReceipt] = useState(""),
    [removing, setRemoving] = useState<Imported | null>(null);
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const [attachmentSearch, setAttachmentSearch] = useState(false);
  const [attachmentSemantic, setAttachmentSemantic] = useState(false);
  const epoch = useRef(0);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    if (!active) return;
    let live = true;
    (async () => {
      try {
        const c = await client.request<{
          attachments?: { keyword_search?: boolean; semantic_search?: boolean };
          permissions: {
            chat: boolean;
            work: boolean;
            search_administration: boolean;
          };
        }>("/v1/capabilities");
        if (!live) return;
        setOwner(c.permissions.search_administration);
        setChat(c.permissions.chat);
        setAttachmentSearch(!!c.attachments?.keyword_search);
        setAttachmentSemantic(!!c.attachments?.semantic_search);
        if (!c.permissions.chat) setScope("none");
        if (c.permissions.work) {
          const p = await client.request<{ id: string; title: string }[]>(
            "/v1/work/tasks?limit=50",
          );
          if (live) {
            setProjects(p);
            setProjectMore(p.length === 50);
          }
        }
        if (c.permissions.search_administration) {
          const [s, i] = await Promise.all([
            client.request<Settings>("/v1/retrieval/settings"),
            client.request<Imported[]>("/v1/history/imports?limit=50"),
          ]);
          if (live) {
            setSettings(s);
            setImports(i);
            setMore(i.length === 50);
          }
        }
      } catch (e) {
        if (live) setError(String(e));
      }
    })();
    return () => {
      live = false;
      epoch.current++;
    };
  }, [client, active, refresh]);
  function clearResults() {
    epoch.current++;
    setMatches([]);
    setCoverage("");
    setReceipt("");
    setError("");
  }
  async function search() {
    const own = ++epoch.current;
    setBusy(true);
    setError("");
    setMatches([]);
    setCoverage("");
    setReceipt("");
    try {
      if (semantic) {
        const r = await client.request<{
          results: Match[];
          coverage: unknown;
          score_meaning: string;
        }>("/v1/retrieval/search", "POST", {
          query,
          kind:
            scope === "attachments"
              ? "attachment"
              : scope === "history"
                ? "history"
                : "memory",
          task_id: ["history", "personal", "attachments"].includes(scope)
            ? null
            : scope,
          hidden: ["history", "attachments"].includes(scope) && hidden,
          limit: 20,
        });
        if (own === epoch.current) {
          setMatches(r.results);
          setCoverage(
            r.score_meaning + "\nIndex coverage: " + JSON.stringify(r.coverage),
          );
        }
      } else {
        const path =
          scope === "attachments"
            ? `/v1/attachments/search?q=${encodeURIComponent(query)}&hidden=${hidden}&limit=50`
            : scope === "history"
              ? `/v1/history/search?q=${encodeURIComponent(query)}&hidden=${hidden}&limit=50`
              : `/v1/memories?q=${encodeURIComponent(query)}&limit=50${scope === "personal" ? "" : `&task_id=${scope}`}`;
        const r = await client.request<Match[]>(path);
        if (own === epoch.current) {
          setMatches(r);
          setCoverage(
            "Keyword search · first 50 matches. Narrow your query for additional results.",
          );
        }
      }
    } catch (e) {
      if (own === epoch.current) setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section hidden={!active} aria-label="History and retrieval">
      <h1>History and retrieval</h1>
      <p>
        Search private history or one memory scope. Results are excerpts, not
        verified facts. Nothing is copied into memory or sent to a model
        automatically.
      </p>
      {error && <p role="alert">{error}</p>}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void search();
        }}
      >
        <label>
          Retrieval scope
          <select
            value={scope}
            disabled={busy}
            onChange={(e) => {
              setScope(e.target.value);
              if (e.target.value === "attachments") setSemantic(false);
              clearResults();
            }}
          >
            {!chat && <option value="none">Choose a project</option>}
            {chat && (
              <>
                <option value="history">Chat history</option>
                {attachmentSearch && (
                  <option value="attachments">Saved attachments</option>
                )}
                <option value="personal">Personal memory</option>
              </>
            )}
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.title}
              </option>
            ))}
          </select>
        </label>
        {projectMore && (
          <button
            type="button"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                const p = await client.request<{ id: string; title: string }[]>(
                  `/v1/work/tasks?limit=50&offset=${projects.length}`,
                );
                setProjects((old) => [...old, ...p]);
                setProjectMore(p.length === 50);
              } catch (e) {
                setError(String(e));
              } finally {
                setBusy(false);
              }
            }}
          >
            Load more projects
          </button>
        )}
        <label>
          Search method
          <select
            value={semantic ? "semantic" : "keyword"}
            disabled={busy}
            onChange={(e) => {
              setSemantic(e.target.value === "semantic");
              clearResults();
            }}
          >
            <option value="keyword">Keywords</option>
            <option
              value="semantic"
              disabled={scope === "attachments" && !attachmentSemantic}
            >
              Local semantic retrieval
            </option>
          </select>
        </label>
        {["history", "attachments"].includes(scope) && (
          <label>
            <input
              type="checkbox"
              checked={hidden}
              disabled={busy}
              onChange={(e) => {
                setHidden(e.target.checked);
                clearResults();
              }}
            />
            {semantic ? "Include hidden chats" : "Search hidden chats only"}
          </label>
        )}
        <label>
          Search private content
          <input
            value={query}
            maxLength={1000}
            disabled={busy}
            onChange={(e) => {
              setQuery(e.target.value);
              clearResults();
            }}
          />
        </label>
        <button disabled={busy || !query.trim() || scope === "none"}>
          Search private content
        </button>
      </form>
      {scope === "attachments" && (
        <p>
          Search saved attachment text locally. Semantic indexing is a separate
          opt-in. Review extraction notices for omissions and OCR errors.
        </p>
      )}
      {coverage && <p className="content">{coverage}</p>}
      {matches.map((m, i) => (
        <article key={i}>
          <h3>{m.title}</h3>
          <p className="content">{m.content ?? m.excerpt}</p>
          {m.score !== undefined && (
            <p>Similarity: {m.score} · not confidence</p>
          )}
          {m.kind === "attachment" && m.conversation_id && (
            <>
              <p>Chat: {m.conversation_title}</p>
              <AttachmentHistory
                client={client}
                chatId={m.conversation_id}
                files={[m as AttachmentRecord]}
                onRemoved={(id) =>
                  setMatches((old) => old.filter((row) => row.id !== id))
                }
              />
            </>
          )}
          {m.conversation_id && m.kind !== "attachment" && (
            <button
              disabled={busy}
              onClick={async () => {
                const own = epoch.current;
                setBusy(true);
                setReceipt("");
                try {
                  const r = await client.request(
                    `/v1/conversations/${m.conversation_id}/import`,
                  );
                  if (own === epoch.current)
                    setReceipt(JSON.stringify(r, null, 2));
                } catch (e) {
                  setError(
                    `${String(e)} Locally created chats have no import receipt.`,
                  );
                } finally {
                  setBusy(false);
                }
              }}
            >
              Review import provenance
            </button>
          )}
        </article>
      ))}
      {receipt && (
        <details open>
          <summary>Import receipt and omissions</summary>
          <pre>{receipt}</pre>
        </details>
      )}
      {owner && (
        <>
          <h2>Local retrieval settings</h2>
          <p>
            Uses the pinned English CPU embedding model. Required assets must be
            installed on the PC. History indexing is a separate opt-in.
          </p>
          {settings && (
            <>
              <p>
                {settings.loaded
                  ? "Embedding model loaded"
                  : "Embedding model not loaded"}{" "}
                · {settings.chunks} indexed chunks ·{" "}
                {settings.error_code ?? "No reported error"}
              </p>
              <pre>{JSON.stringify(settings.sources, null, 2)}</pre>
              {["enabled", "history_enabled", "attachments_enabled"].map(
                (key) => (
                  <label key={key}>
                    <input
                      type="checkbox"
                      disabled={busy}
                      checked={
                        settings[
                          key as
                            | "enabled"
                            | "history_enabled"
                            | "attachments_enabled"
                        ]
                      }
                      onChange={async (e) => {
                        const value = e.target.checked;
                        setBusy(true);
                        setError("");
                        try {
                          setSettings(
                            await client.request<Settings>(
                              "/v1/retrieval/settings",
                              "PATCH",
                              {
                                revision: settings.revision,
                                enabled: settings.enabled,
                                history_enabled: settings.history_enabled,
                                attachments_enabled:
                                  settings.attachments_enabled,
                                [key]: value,
                              },
                            ),
                          );
                          clearResults();
                        } catch (e) {
                          setError(
                            `${String(e)} Refresh settings before retrying.`,
                          );
                        } finally {
                          setBusy(false);
                        }
                      }}
                    />
                    {key === "enabled"
                      ? "Enable local semantic retrieval"
                      : key === "history_enabled"
                        ? "Index chat history locally"
                        : "Index attachment text locally"}
                  </label>
                ),
              )}
              <button
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    setSettings(
                      await client.request<Settings>("/v1/retrieval/settings"),
                    );
                  } catch (e) {
                    setError(String(e));
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Refresh retrieval settings
              </button>
            </>
          )}
          <h2>Imported history</h2>
          <HistoryImport
            origin={client.origin}
            onImported={() => {
              clearResults();
              setRefresh((n) => n + 1);
            }}
          />
          <button
            disabled={busy}
            onClick={() => {
              clearResults();
              setRefresh((n) => n + 1);
            }}
          >
            Refresh imported history
          </button>
          <p>
            Archives are imported locally on the PC with preview and hash
            acceptance. Remote archive upload is not enabled.
          </p>
          {imports.map((row) => (
            <article key={row.conversation_id}>
              <h3>{row.source_title ?? "Removed source"}</h3>
              <p>{row.imported_at}</p>
              <button
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    setReceipt(
                      JSON.stringify(
                        await client.request(
                          `/v1/conversations/${row.conversation_id}/import`,
                        ),
                        null,
                        2,
                      ),
                    );
                  } catch (e) {
                    setError(String(e));
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Review source receipt
              </button>
              {!row.removed && (
                <button disabled={busy} onClick={() => setRemoving(row)}>
                  Remove imported source…
                </button>
              )}
            </article>
          ))}
          {more && (
            <button
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  const rows = await client.request<Imported[]>(
                    `/v1/history/imports?limit=50&offset=${imports.length}`,
                  );
                  setImports((old) => [...old, ...rows]);
                  setMore(rows.length === 50);
                } catch (e) {
                  setError(String(e));
                } finally {
                  setBusy(false);
                }
              }}
            >
              Load more imports
            </button>
          )}
          {removing && (
            <div role="alertdialog" aria-label="Confirm source removal">
              <p>
                Remove every imported version of source {removing.source_id}?
                Imported text is erased and reimport is blocked. Locally added
                turns and explicitly copied memories remain.
              </p>
              <button
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    await client.request(
                      `/v1/history/imports/${removing.conversation_id}`,
                      "DELETE",
                    );
                    const id = removing.source_id;
                    setImports((old) =>
                      old.map((r) =>
                        r.source_id === id
                          ? { ...r, removed: 1, source_title: null }
                          : r,
                      ),
                    );
                    setRemoving(null);
                    clearResults();
                  } catch (e) {
                    setError(String(e));
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Confirm source removal
              </button>
              <button disabled={busy} onClick={() => setRemoving(null)}>
                Keep source
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
