import { useEffect, useRef, useState } from "react";
import { Client } from "./transport";

interface MemoryRow {
  id: string;
  task_id: string | null;
  title: string;
  content: string;
  source: string;
  revision: number;
  updated_at: string;
}
interface Capabilities {
  permissions: { chat: boolean; work: boolean; model_management: boolean };
  memory: { creation_retries: boolean };
}
interface Project {
  id: string;
  title: string;
}

export function MemoryPanel({
  client,
  active,
}: {
  client: Client;
  active: boolean;
}) {
  const [cap, setCap] = useState<Capabilities | null>(null),
    [projects, setProjects] = useState<Project[]>([]),
    [projectMore, setProjectMore] = useState(false);
  const [scope, setScope] = useState(""),
    [scopeTitle, setScopeTitle] = useState("Personal"),
    [query, setQuery] = useState(""),
    [rows, setRows] = useState<MemoryRow[]>([]),
    [more, setMore] = useState(false);
  const [editor, setEditor] = useState(false),
    [editing, setEditing] = useState<MemoryRow | null>(null),
    [title, setTitle] = useState(""),
    [content, setContent] = useState("");
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [deleting, setDeleting] = useState<MemoryRow | null>(null),
    [refresh, setRefresh] = useState(0);
  const creation = useRef<string | null>(null),
    epoch = useRef(0);
  async function loadProjects(append = false) {
    const batch = await client.request<Project[]>(
      `/v1/work/tasks?limit=50&offset=${append ? projects.length : 0}`,
    );
    setProjects((old) => (append ? [...old, ...batch] : batch));
    setProjectMore(batch.length === 50);
  }
  useEffect(() => {
    if (!active || cap) return;
    let live = true;
    client
      .request<Capabilities>("/v1/capabilities")
      .then((c) => {
        if (!live) return;
        if (!c.memory?.creation_retries)
          throw new Error(
            "Update the PC backend to 0.3.0.dev6 for memory controls.",
          );
        setCap(c);
      })
      .catch((e) => {
        if (live)
          setError(
            `${String(e)} Memory controls require backend 0.3.0.dev6 or newer. Check the connection and backend version.`,
          );
      });
    return () => {
      live = false;
    };
  }, [active, client, cap, refresh]);
  useEffect(() => {
    if (active && cap?.permissions.work)
      void loadProjects().catch((e) => setError(String(e)));
  }, [active, client, cap, refresh]);
  async function load(append = false) {
    const own = ++epoch.current;
    try {
      const params = new URLSearchParams({
        q: query,
        limit: "50",
        offset: String(append ? rows.length : 0),
      });
      if (scope) params.set("task_id", scope);
      const batch = await client.request<MemoryRow[]>(`/v1/memories?${params}`);
      if (own !== epoch.current) return;
      setRows((old) => (append ? [...old, ...batch] : batch));
      setMore(batch.length === 50);
    } catch (e) {
      if (own === epoch.current) setError(String(e));
    }
  }
  useEffect(() => {
    if (!active || !cap) return;
    const timer = setTimeout(() => void load(), 200);
    return () => {
      clearTimeout(timer);
      epoch.current++;
    };
  }, [active, cap, client, scope, query, refresh]);
  function edit(row: MemoryRow | null) {
    setEditing(row);
    setTitle(row?.title || "");
    setContent(row?.content || "");
    setEditor(true);
    creation.current = null;
    setError("");
    setNotice("");
  }
  async function save() {
    if (busy || !title.trim() || !content.trim()) return;
    setBusy(true);
    setError("");
    try {
      if (editing)
        await client.request(`/v1/memories/${editing.id}`, "PATCH", {
          revision: editing.revision,
          title: title.trim(),
          content: content.trim(),
        });
      else {
        creation.current ??= crypto.randomUUID();
        await client.request("/v1/memories", "POST", {
          request_id: creation.current,
          title: title.trim(),
          content: content.trim(),
          task_id: scope || null,
        });
      }
      setEditor(false);
      setEditing(null);
      creation.current = null;
      setQuery("");
      setNotice("Memory saved.");
    } catch (e) {
      setError(
        `${String(e)} Your editor is retained. For a conflict, cancel editing, inspect the current memory, then reopen it.`,
      );
    } finally {
      setBusy(false);
      setRefresh((n) => n + 1);
    }
  }
  async function remove() {
    if (!deleting || busy) return;
    setBusy(true);
    setError("");
    try {
      await client.request(
        `/v1/memories/${deleting.id}?revision=${deleting.revision}`,
        "DELETE",
      );
      setNotice(
        "Memory deleted from future retrieval. Existing chats and backups remain.",
      );
    } catch (e) {
      setError(
        `${String(e)} Check the refreshed memory before deleting again.`,
      );
    } finally {
      setDeleting(null);
      setBusy(false);
      setRefresh((n) => n + 1);
    }
  }
  const allowed = Boolean(
    cap && (scope ? cap.permissions.work : cap.permissions.chat),
  );
  return (
    <section
      hidden={!active}
      className="memory-panel"
      aria-label="Memory workspace"
    >
      <h1>Memory</h1>
      <p>
        Saved on your PC. Personal memories support Chat; project memories
        support that Work task. Retrieval currently uses matching words.
      </p>
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      <div className="memory-toolbar">
        <label>
          Memory scope
          <select
            value={scope}
            disabled={busy || editor || !!deleting}
            onChange={(e) => {
              epoch.current++;
              setScope(e.target.value);
              setScopeTitle(
                e.target.selectedOptions[0]?.text || "Selected project",
              );
              setQuery("");
              setRows([]);
              setError("");
              setNotice("");
            }}
          >
            <option value="">Personal</option>
            {scope && !projects.some((p) => p.id === scope) && (
              <option value={scope}>{scopeTitle}</option>
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
            disabled={busy || editor}
            onClick={() =>
              void loadProjects(true).catch((e) => setError(String(e)))
            }
          >
            Load more projects
          </button>
        )}
        <label>
          Search memories
          <input
            value={query}
            maxLength={1000}
            disabled={editor || !!deleting}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <button
          disabled={busy}
          onClick={() => {
            setError("");
            setRefresh((n) => n + 1);
          }}
        >
          Refresh memories
        </button>
        <button
          disabled={!allowed || busy || editor || !!deleting}
          onClick={() => edit(null)}
        >
          Add memory
        </button>
        <button
          disabled={!allowed || busy || editor || !!deleting}
          onClick={async () => {
            setBusy(true);
            setError("");
            try {
              if (await client.downloadMemory(scope || null))
                setNotice("Memory scope exported.");
            } catch (e) {
              setError(String(e));
            } finally {
              setBusy(false);
            }
          }}
        >
          Export scope JSON…
        </button>
      </div>
      {cap && !allowed && (
        <p>This device lacks permission for this memory scope.</p>
      )}
      {editor && (
        <form
          className="memory-editor"
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          <h2>{editing ? "Edit memory" : "Add memory"}</h2>
          <label>
            Memory title
            <input
              required
              maxLength={200}
              value={title}
              disabled={busy}
              onChange={(e) => {
                setTitle(e.target.value);
                creation.current = null;
              }}
            />
          </label>
          <label>
            Memory content
            <textarea
              aria-label="Memory content"
              required
              rows={6}
              maxLength={8000}
              value={content}
              disabled={busy}
              onChange={(e) => {
                setContent(e.target.value);
                creation.current = null;
              }}
            />
          </label>
          <div className="work-actions">
            <button
              className="primary"
              disabled={busy || !title.trim() || !content.trim()}
            >
              Save memory
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                setEditor(false);
                setEditing(null);
                setError("");
                creation.current = null;
              }}
            >
              Cancel editing
            </button>
          </div>
        </form>
      )}
      {deleting && (
        <div
          role="alertdialog"
          aria-label="Delete memory"
          className="memory-editor"
        >
          <h2>Delete “{deleting.title}”?</h2>
          <p>
            This removes it from future retrieval. Existing conversations and
            backups remain.
          </p>
          <div className="work-actions">
            <button disabled={busy} onClick={() => void remove()}>
              Delete memory
            </button>
            <button disabled={busy} onClick={() => setDeleting(null)}>
              Cancel
            </button>
          </div>
        </div>
      )}
      {rows.map((row) => (
        <article className="memory-card" key={row.id}>
          <h2>{row.title}</h2>
          <p className="content">{row.content}</p>
          <small>
            {row.source === "agent" ? "Saved by Work" : "Saved by you"} ·
            revision {row.revision} · {row.updated_at}
          </small>
          <div className="work-actions">
            <button
              disabled={busy || editor || !!deleting}
              onClick={() => edit(row)}
            >
              Edit {row.title}
            </button>
            <button
              disabled={busy || editor || !!deleting}
              onClick={() => {
                setDeleting(row);
                setError("");
                setNotice("");
              }}
            >
              Delete {row.title}
            </button>
          </div>
        </article>
      ))}
      {!rows.length && cap && <p>No memories found in this scope.</p>}
      {more && (
        <button disabled={busy || editor} onClick={() => void load(true)}>
          Load more memories
        </button>
      )}
    </section>
  );
}
