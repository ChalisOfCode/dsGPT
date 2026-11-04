import { ChatMenu, ChatFiles } from "./ChatMenu";
import { Icon } from "./Icon";
import { PhoneConnection } from "./PhoneConnection";
import { DocumentPicker } from "./Documents";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Client, connect, restore, disconnect, native } from "./transport";
import { nearBottom } from "./protocol";
import { ResearchReply } from "./ResearchReply";
import { ThinkingPicker, WebPicker } from "./GenerationControls";
import { DictationButton } from "./Dictation";
import { WorkPanel } from "./WorkPanel";
import { ToolSetupPanel } from "./ToolSetupPanel";
import { RecallPanel } from "./RecallPanel";
import { MemoryPanel } from "./MemoryPanel";
import { ModelsPanel } from "./ModelsPanel";
import { DevicesPanel } from "./DevicesPanel";
import { DiagnosticsPanel } from "./DiagnosticsPanel";
import {
  AttachmentComposer,
  AttachmentSelection,
  AttachmentHistory,
  validateAttachments,
  type DraftAttachment,
} from "./Attachments";
import { SearchPanel } from "./SearchPanel";
import { researchOptions, type ResearchCapabilities } from "./research";
import {
  terminal,
  type Conversation,
  type Message,
  type Model,
  type Snapshot,
  type Run,
} from "./types";
const read = (key: string) => {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
};
const save = (key: string, value: string) => {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* Storage can be disabled. */
  }
};
const pause = (ms: number, signal: AbortSignal) =>
  new Promise<void>((resolve) => {
    const timer = setTimeout(done, ms);
    function done() {
      clearTimeout(timer);
      signal.removeEventListener("abort", done);
      resolve();
    }
    signal.addEventListener("abort", done, { once: true });
  });
export function App() {
  const [effort, setEffort] = useState("auto");
  const [webMode, setWebMode] = useState("auto");
  const [dictating, setDictating] = useState(false);
  const [phoneRequest, setPhoneRequest] = useState(0);
  const [lastMode, setLastMode] = useState<"chat" | "work">("chat");
  const [sidebarOpen, setSidebarOpen] = useState(
    () => read("dsgpt:sidebar") !== "closed",
  );
  const [theme, setTheme] = useState(() => {
    const saved = read("dsgpt:theme");
    return saved === "light" || saved === "dark" ? saved : "system";
  });
  const [toolsOpen, setToolsOpen] = useState(false);
  const toolsRef = useRef<HTMLDivElement>(null);
  const toolsButton = useRef<HTMLButtonElement>(null);
  const messageInput = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const system = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      document.documentElement.dataset.theme =
        theme === "system" ? (system.matches ? "dark" : "light") : theme;
    };
    apply();
    save("dsgpt:theme", theme);
    system.addEventListener("change", apply);
    return () => system.removeEventListener("change", apply);
  }, [theme]);
  useEffect(() => {
    save("dsgpt:sidebar", sidebarOpen ? "open" : "closed");
  }, [sidebarOpen]);
  useEffect(() => {
    if (!toolsOpen) return;
    const outside = (event: PointerEvent) => {
      if (!toolsRef.current?.contains(event.target as Node))
        setToolsOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setToolsOpen(false);
        toolsButton.current?.focus();
      }
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [toolsOpen]);
  const [client, setClient] = useState<Client | null>(null),
    [origin, setOrigin] = useState("http://127.0.0.1:8765"),
    [token, setToken] = useState(""),
    [error, setError] = useState("");
  const [chats, setChats] = useState<Conversation[]>([]),
    [models, setModels] = useState<Model[]>([]),
    [selected, setSelected] = useState<string | null>(null),
    [model, setModel] = useState("");
  const [page, setPage] = useState<
      | "chat"
      | "settings"
      | "hidden"
      | "diagnostics"
      | "work"
      | "memory"
      | "models"
      | "devices"
      | "search"
      | "recall"
    >("chat"),
    [query, setQuery] = useState(""),
    [more, setMore] = useState(false),
    [busy, setBusy] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]),
    [draft, setDraft] = useState(""),
    [run, setRun] = useState<Run | null>(null),
    [refresh, setRefresh] = useState(0),
    [following, setFollowing] = useState(true),
    [connection, setConnection] = useState("");
  const [filesChat, setFilesChat] = useState<Conversation | null>(null);
  const [deleteChat, setDeleteChat] = useState<Conversation | null>(null);
  const [deletingChat, setDeletingChat] = useState(false);
  const [attachments, setAttachments] = useState<DraftAttachment[]>([]),
    [attachmentEpoch, setAttachmentEpoch] = useState(0),
    [attachmentPicking, setAttachmentPicking] = useState(false);
  const [diagnostics, setDiagnostics] = useState<unknown>(null);
  const [diagnosticDevices, setDiagnosticDevices] = useState<
    { id: string; name: string; role: string; revoked: number }[]
  >([]);
  const [diagnosticDevice, setDiagnosticDevice] = useState("");
  const [includeBuildLogs, setIncludeBuildLogs] = useState(false);
  const [research, setResearch] = useState(false),
    [searchWeb, setSearchWeb] = useState(false),
    [sourceURLs, setSourceURLs] = useState(""),
    [researchCapability, setResearchCapability] =
      useState<ResearchCapabilities | null>(null);
  const viewport = useRef<HTMLDivElement>(null),
    follow = useRef(true),
    restoring = useRef(true),
    chatRef = useRef<string | null>(null),
    listEpoch = useRef(0),
    requestId = useRef<string | null>(null);
  useEffect(() => {
    setAttachments([]);
    setAttachmentEpoch((n) => n + 1);
  }, [client]);
  useEffect(() => {
    setToolsOpen(false);
  }, [page, selected, attachments.length]);
  useLayoutEffect(() => {
    const input = messageInput.current;
    if (input) {
      input.style.height = "auto";
      input.style.height = `${Math.min(input.scrollHeight, 200)}px`;
    }
  }, [draft, page, client, sidebarOpen]);
  const key = (id: string) => `dsgpt:${client?.origin}:position:${id}`;
  useEffect(() => {
    if (!client || !["chat", "search"].includes(page)) return;
    const controller = new AbortController();
    async function refreshCapabilities() {
      if (document.visibilityState !== "visible") return;
      try {
        const cap = await client!.request<ResearchCapabilities>(
          "/v1/research/capabilities",
          "GET",
          undefined,
          controller.signal,
        );
        if (!controller.signal.aborted) {
          setResearchCapability(cap);
          if (!cap.search_configured) setSearchWeb(false);
        }
      } catch {
        /* Existing connection controls report failures; never enable research here. */
      }
    }
    void refreshCapabilities();
    const timer = setInterval(() => void refreshCapabilities(), 5000);
    window.addEventListener("focus", refreshCapabilities);
    return () => {
      controller.abort();
      clearInterval(timer);
      window.removeEventListener("focus", refreshCapabilities);
    };
  }, [client, page]);
  const [setupStatus, setSetupStatus] = useState("");
  useEffect(() => {
    if (!client) return;
    let live = true;
    async function poll() {
      try {
        const [available, status] = await Promise.all([
          client!.request<Model[]>("/v1/models"),
          client!.request<{
            status: string;
            message: string;
            percent?: number;
          }>("/v1/setup/experience"),
        ]);
        if (live) {
          setModels(available);
          setSetupStatus(
            status.status === "succeeded"
              ? ""
              : (status.message || "") +
                  (status.percent == null ? "" : ` ${status.percent}%`),
          );
        }
      } catch {
        /* Other connection state handles disconnection. */
      }
    }
    void poll();
    const timer = setInterval(() => void poll(), 10000);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [client]);

  function persist() {
    if (chatRef.current && viewport.current)
      save(
        key(chatRef.current),
        JSON.stringify({
          top: viewport.current.scrollTop,
          follow: follow.current,
        }),
      );
  }
  function switchMode(mode: "chat" | "work") {
    persist();
    setLastMode(mode);
    setPage(mode);
  }
  useEffect(() => {
    if (page === "chat" || page === "work") setLastMode(page);
  }, [page]);
  async function loadChats(append = false) {
    if (!client) return;
    const epoch = ++listEpoch.current;
    try {
      const batch = await client.request<Conversation[]>(
        `/v1/conversations?hidden=${page === "hidden"}&q=${encodeURIComponent(query)}&limit=100&offset=${append ? chats.length : 0}`,
      );
      if (epoch === listEpoch.current) {
        setChats((old) => [
          ...new Map(
            (append ? [...old, ...batch] : batch).map((c) => [c.id, c]),
          ).values(),
        ]);
        setMore(batch.length === 100);
      }
    } catch (e) {
      setError(String(e));
    }
  }
  useEffect(() => {
    let live = true;
    restore()
      .then((c) => {
        if (live) setClient(c);
      })
      .catch(() => {
        if (live) setError("Stored connection unavailable. Connect again.");
      });
    return () => {
      live = false;
    };
  }, []);
  useEffect(() => {
    if (!client) return;
    let live = true;
    const previous = read(`dsgpt:${client.origin}:selected`);
    if (previous)
      client
        .request<Conversation>(`/v1/conversations/${previous}`)
        .then((c) => {
          if (live && !c.hidden) {
            setSelected(c.id);
            if (c.model_id) setModel(c.model_id);
          }
        })
        .catch(() => {});
    return () => {
      live = false;
    };
  }, [client]);
  useEffect(() => {
    if (!client) return;
    let live = true;
    setResearchCapability(null);
    client
      .request<ResearchCapabilities>("/v1/research/capabilities")
      .then((cap) => {
        if (live) {
          setResearchCapability(cap);
          setSearchWeb(Boolean(cap.search_configured));
        }
      })
      .catch(() => {
        if (live) setResearchCapability(null);
      });
    client
      .request<Model[]>("/v1/models")
      .then((m) => {
        if (live) {
          setModels(m);
          setModel((v) => v || m[0]?.id || "");
        }
      })
      .catch((e) => setError(String(e)));
    return () => {
      live = false;
    };
  }, [client]);
  useEffect(() => {
    setModel((current) =>
      models.some((m) => m.id === current) ? current : models[0]?.id || "",
    );
  }, [models]);
  useEffect(() => {
    const timer = setTimeout(() => void loadChats(), 120);
    return () => {
      clearTimeout(timer);
      listEpoch.current++;
    };
  }, [client, page, query, refresh]);
  useEffect(() => {
    if (!client || !selected || page !== "chat") return;
    const abort = new AbortController();
    const signal = abort.signal;
    const id = selected;
    chatRef.current = id;
    restoring.current = true;
    setMessages([]);
    setRun(null);
    setConnection("Loading conversation");
    let first = true;
    const all: Message[] = [];
    let lastOrdinal = 0;
    async function sync() {
      while (!signal.aborted) {
        try {
          let after = Math.max(0, lastOrdinal - 2);
          for (;;) {
            const batch = await client!.request<Message[]>(
              `/v1/conversations/${id}/messages?after=${after}&limit=200`,
              "GET",
              undefined,
              signal,
            );
            for (const message of batch) {
              const index = all.findIndex((m) => m.id === message.id);
              if (index >= 0) all[index] = message;
              else all.push(message);
            }
            if (batch.length) {
              after = batch[batch.length - 1].ordinal;
              lastOrdinal = after;
            }
            if (batch.length < 200) break;
          }
          const snap = await client!.request<Snapshot | null>(
            `/v1/conversations/${id}/latest-run`,
            "GET",
            undefined,
            signal,
          );
          if (signal.aborted) return;
          if (snap) {
            const i = all.findIndex((m) => m.id === snap.message.id);
            if (i >= 0) all[i] = snap.message;
            else all.push(snap.message);
          }
          if (first) {
            let pos: { top: number; follow: boolean } | null = null;
            try {
              pos = JSON.parse(read(key(id)) || "null");
            } catch {}
            follow.current = pos?.follow ?? true;
            setFollowing(follow.current);
            first = false;
          }
          all.sort((a, b) => a.ordinal - b.ordinal);
          setMessages([...all]);
          setRun(snap?.run ?? null);
          setConnection("Connected");
          if (!snap || terminal(snap.run.status)) {
            await pause(1800, signal);
            continue;
          }
          if (native) {
            await pause(250, signal);
            continue;
          }
          let cursor = snap.cursor;
          await client!.events(snap.run.id, cursor, signal, (event) => {
            if (signal.aborted || event.id <= cursor) return;
            cursor = event.id;
            if (event.kind === "delta")
              setMessages((old) =>
                old.map((m) =>
                  m.id === snap.message.id
                    ? {
                        ...m,
                        content: m.content + String(event.data.text ?? ""),
                        status: "running",
                      }
                    : m,
                ),
              );
            if (terminal(event.kind)) {
              setRun((r) => (r ? { ...r, status: event.kind } : r));
              setMessages((old) =>
                old.map((m) =>
                  m.id === snap.message.id ? { ...m, status: event.kind } : m,
                ),
              );
            }
          });
        } catch (e) {
          if (signal.aborted) return;
          setConnection("Reconnecting…");
          await pause(1600, signal);
        }
      }
    }
    void sync();
    return () => {
      persist();
      abort.abort();
      chatRef.current = null;
    };
  }, [client, selected, page, refresh]);
  useLayoutEffect(() => {
    const el = viewport.current;
    if (!el || !messages.length) return;
    if (restoring.current) {
      let pos: null | { top: number } = null;
      try {
        pos = JSON.parse(read(key(selected!)) || "null");
      } catch {}
      el.scrollTop = follow.current ? el.scrollHeight : (pos?.top ?? 0);
      restoring.current = false;
    } else if (follow.current) el.scrollTop = el.scrollHeight;
  }, [messages]);
  useEffect(() => {
    const handler = () => persist();
    window.addEventListener("pagehide", handler);
    return () => window.removeEventListener("pagehide", handler);
  });
  function choose(c: Conversation) {
    setAttachments([]);
    setAttachmentEpoch((n) => n + 1);
    save(`dsgpt:${client?.origin}:selected`, c.id);
    persist();
    setSelected(c.id);
    setPage("chat");
    if (c.model_id) setModel(c.model_id);
    setDraft("");
    setResearch(false);
    setSourceURLs("");
    requestId.current = null;
    setError("");
  }
  function newChat() {
    persist();
    setSelected(null);
    setMessages([]);
    setRun(null);
    setPage("chat");
    setAttachments([]);
    setAttachmentEpoch((n) => n + 1);
    setDraft("");
    setResearch(false);
    setSourceURLs("");
    requestId.current = null;
  }
  async function eraseChat() {
    if (!client || !deleteChat || deletingChat) return;
    setDeletingChat(true);
    try {
      await client.request(`/v1/conversations/${deleteChat.id}`, "DELETE");
      if (selected === deleteChat.id) newChat();
      if (filesChat?.id === deleteChat.id) setFilesChat(null);
      setChats(chats.filter((c) => c.id !== deleteChat.id));
      setDeleteChat(null);
      setRefresh((n) => n + 1);
    } catch (e) {
      setError(String(e));
    } finally {
      setDeletingChat(false);
    }
  }
  async function change(c: Conversation, values: Record<string, unknown>) {
    document
      .querySelectorAll("details[open]")
      .forEach((el) => el.removeAttribute("open"));
    try {
      await client!.request(`/v1/conversations/${c.id}`, "PATCH", {
        revision: c.revision,
        ...values,
      });
      if (values.hidden && selected === c.id) setSelected(null);
      setRefresh((x) => x + 1);
    } catch (e) {
      setError(String(e));
      setRefresh((x) => x + 1);
    }
  }
  async function send() {
    if (dictating) return;
    if (
      !client ||
      !draft.trim() ||
      !model ||
      busy ||
      attachmentPicking ||
      (run && !terminal(run.status))
    )
      return;
    setBusy(true);
    setError("");
    try {
      if (attachments.length) {
        validateAttachments(attachments);
        if (research)
          throw new Error("Turn off Research to send private text files.");
        const capabilities = await client.request<{
          attachments?: { chat_text_files?: boolean };
        }>("/v1/capabilities");
        if (!capabilities.attachments?.chat_text_files)
          throw new Error(
            "Text attachments require backend 0.3.0.dev11 or newer. Your selected files are retained.",
          );
      }
      const options = research
        ? researchOptions(searchWeb, sourceURLs)
        : undefined;
      let id = selected;
      if (!id) {
        const c = await client.request<Conversation>(
          "/v1/conversations",
          "POST",
          { title: draft.trim().slice(0, 80) },
        );
        id = c.id;
        setSelected(id);
        save(`dsgpt:${client.origin}:selected`, id);
      }
      requestId.current ??= crypto.randomUUID();
      await client.request(`/v1/conversations/${id}/messages`, "POST", {
        request_id: requestId.current,
        content: draft,
        model_id: model,
        reasoning_effort: effort,
        web_mode: attachments.length || research ? "off" : webMode,
        ...(options ? { research: options } : {}),
        ...(attachments.length
          ? {
              attachments: attachments.map((f) =>
                f.original_base64
                  ? { name: f.name, original_base64: f.original_base64 }
                  : { name: f.name, text: f.text },
              ),
            }
          : {}),
      });
      requestId.current = null;
      setAttachments([]);
      setDraft("");
      follow.current = true;
      setFollowing(true);
      setRefresh((x) => x + 1);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  if (!client)
    return (
      <div className="connect">
        <div className="logo">
          ds<span>GPT</span>
        </div>
        <h1>Your models. Your workspace.</h1>
        <p>Connect to the backend running on your Windows PC.</p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            setBusy(true);
            connect(origin, token)
              .then((c) => {
                setClient(c);
                setToken("");
                setError("");
              })
              .catch((e) => setError(String(e)))
              .finally(() => setBusy(false));
          }}
        >
          <label>
            Backend address
            <input
              value={origin}
              onChange={(e) => setOrigin(e.target.value)}
              required
            />
          </label>
          <label>
            Owner credential
            <input
              type="password"
              autoComplete="off"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              required
            />
          </label>
          <button className="primary" disabled={busy}>
            {busy ? "Connecting…" : "Connect to dsGPT"}
          </button>
        </form>
        {error && <p role="alert">{error}</p>}
        <small>
          {native
            ? "Credentials stay in Windows Credential Manager."
            : "Development browser: credentials remain in memory for this session."}
        </small>
      </div>
    );
  return (
    <div className={`shell${sidebarOpen ? "" : " sidebar-closed"}`}>
      <aside aria-label="Sidebar">
        <div className="sidebar-heading">
          <div className="logo">
            ds<span>GPT</span>
          </div>
          <button
            className="icon-button"
            aria-label={sidebarOpen ? "Collapse sidebar" : "Expand sidebar"}
            title={sidebarOpen ? "Collapse sidebar" : "Expand sidebar"}
            onClick={() => setSidebarOpen(!sidebarOpen)}
          >
            <Icon name="sidebar" />
          </button>
        </div>

        <button
          className={`nav-button${page === "work" ? " selected" : ""}`}
          aria-label="Work"
          title="Work"
          onClick={() => {
            persist();
            setPage("work");
          }}
        >
          <Icon name="work" />
          <span className="nav-label">Work</span>
        </button>
        <label className="search">
          <Icon name="search" />
          <span className="sr">Search chats</span>
          <input
            placeholder="Search chats"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <div className="chatlist">
          <div className="list-heading">Your chats</div>
          {chats
            .filter((c) => !c.hidden && page !== "hidden")
            .map((c) => (
              <div className="chatrow" key={c.id}>
                <button
                  className={selected === c.id ? "selected" : ""}
                  onClick={() => choose(c)}
                >
                  {c.pinned ? "◆ " : ""}
                  {c.title}
                </button>
                <ChatMenu
                  chat={c}
                  change={(c, v) => void change(c, v)}
                  remove={setDeleteChat}
                  files={setFilesChat}
                />
              </div>
            ))}
          {more && page !== "hidden" && (
            <button onClick={() => void loadChats(true)}>
              Load more chats
            </button>
          )}
        </div>
        <button
          className={`nav-button settings${page === "settings" ? " selected" : ""}`}
          aria-label="Settings"
          title="Settings"
          onClick={() => {
            persist();
            setPage("settings");
          }}
        >
          <Icon name="settings" />
          <span className="nav-label">Settings</span>
        </button>
        <div className="local">
          <span className="status-dot" />{" "}
          <span className="nav-label">Your local workspace</span>
        </div>
      </aside>
      {filesChat && (
        <ChatFiles
          key={filesChat.id}
          client={client}
          chat={filesChat}
          onClose={() => setFilesChat(null)}
        />
      )}
      {deleteChat && (
        <div className="modal-backdrop">
          <section
            className="chat-files"
            role="dialog"
            aria-modal="true"
            aria-label="Delete chat"
          >
            <h2>Delete “{deleteChat.title}”?</h2>
            <p>
              This removes the chat, messages and attached files from dsGPT on
              your devices. Saved memories and existing backups remain.
            </p>
            <div className="work-actions">
              <button
                autoFocus
                disabled={deletingChat}
                onClick={() => setDeleteChat(null)}
              >
                Cancel
              </button>
              <button disabled={deletingChat} onClick={() => void eraseChat()}>
                {deletingChat ? "Deleting…" : "Delete chat"}
              </button>
            </div>
          </section>
        </div>
      )}
      <main>
        <header>
          <div className="header-identity">
            <button
              className="icon-button"
              aria-label={sidebarOpen ? "Close sidebar" : "Open sidebar"}
              onClick={() => setSidebarOpen(!sidebarOpen)}
            >
              <Icon name="sidebar" />
            </button>
            <button
              className="icon-button"
              aria-label="New chat"
              title="New chat"
              onClick={newChat}
            >
              <Icon name="new" />
            </button>
            <div className="page-title">
              {page === "chat"
                ? chats.find((c) => c.id === selected)?.title || "New chat"
                : page === "work"
                  ? "Work"
                  : page.charAt(0).toUpperCase() + page.slice(1)}
            </div>
            {page === "chat" && chats.find((c) => c.id === selected) && (
              <ChatMenu
                chat={chats.find((c) => c.id === selected)!}
                change={(c, v) => void change(c, v)}
                remove={setDeleteChat}
                files={setFilesChat}
              />
            )}
          </div>
          <div
            className="mode-switch"
            role="tablist"
            aria-label="Workspace mode"
          >
            {(["chat", "work"] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                role="tab"
                aria-selected={lastMode === mode}
                tabIndex={lastMode === mode ? 0 : -1}
                onClick={() => switchMode(mode)}
                onKeyDown={(event) => {
                  if (
                    ["ArrowLeft", "ArrowRight", "Home", "End"].includes(
                      event.key,
                    )
                  ) {
                    event.preventDefault();
                    const next =
                      event.key === "Home"
                        ? "chat"
                        : event.key === "End"
                          ? "work"
                          : mode === "chat"
                            ? "work"
                            : "chat";
                    switchMode(next);
                    const tabs =
                      event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>(
                        "button",
                      );
                    tabs?.[next === "chat" ? 0 : 1]?.focus();
                  }
                }}
              >
                <Icon name={mode} />
                {mode === "chat" ? "Chat" : "Work"}
              </button>
            ))}
          </div>
          <div className="header-actions">
            {["chat", "work"].includes(page) && (
              <select
                aria-label="Model"
                value={model}
                disabled={busy}
                onChange={(e) => {
                  setModel(e.target.value);
                  requestId.current = null;
                }}
              >
                {models.map((m) => (
                  <option value={m.id} key={m.id}>
                    {m.label}
                  </option>
                ))}
              </select>
            )}
            {["chat", "work"].includes(page) && (
              <ThinkingPicker
                client={client}
                model={model}
                value={effort}
                onChange={(value) => {
                  setEffort(value);
                  requestId.current = null;
                }}
                disabled={busy}
              />
            )}
            <PhoneConnection
              key={client.origin}
              client={client}
              request={phoneRequest}
            />
          </div>
        </header>
        {setupStatus && (
          <div className="setup-progress" role="status">
            {setupStatus}
          </div>
        )}
        {error && (
          <div className="error" role="alert">
            {error}
            <button onClick={() => setError("")}>Dismiss</button>
          </div>
        )}
        {page === "chat" ? (
          <div className={`chat-view${messages.length ? "" : " empty"}`}>
            <div
              ref={viewport}
              className="messages"
              onScroll={() => {
                if (restoring.current) return;
                follow.current = nearBottom(viewport.current!);
                setFollowing(follow.current);
                persist();
              }}
            >
              {messages.length ? (
                messages.map((m) => (
                  <article key={m.id} className={m.role}>
                    <div className="speaker">
                      {m.role === "user" ? "You" : "dsGPT"}
                      {m.role === "assistant" && m.status !== "completed" && (
                        <small> · {m.status}</small>
                      )}
                    </div>
                    {m.research && m.run_id ? (
                      <ResearchReply client={client} message={m} />
                    ) : (
                      <div className="content">
                        {m.content || "Waiting for the local model…"}
                      </div>
                    )}
                    {m.run_error_code && (
                      <p role="status">
                        {m.run_error_code === "context_exceeded"
                          ? "This message and its files exceed the model’s context. Choose a larger context/model or send less text. Nothing was silently shortened."
                          : m.run_error_code === "local_vision_model_required"
                            ? "Choose a locally installed Ollama model with vision support to interpret this image. No pixels were sent to a text-only model."
                            : `Reply stopped: ${m.run_error_code}`}
                      </p>
                    )}
                    {!!m.attachments?.length && (
                      <AttachmentHistory
                        client={client}
                        chatId={m.conversation_id}
                        files={m.attachments}
                      />
                    )}
                  </article>
                ))
              ) : (
                <div className="welcome">
                  <h1>What can I help with?</h1>
                </div>
              )}
            </div>
            <div className="composer-wrap">
              {!following && (
                <button
                  className="jump"
                  onClick={() => {
                    follow.current = true;
                    setFollowing(true);
                    if (viewport.current)
                      viewport.current.scrollTop =
                        viewport.current.scrollHeight;
                    persist();
                  }}
                >
                  ↓ Jump to latest
                </button>
              )}
              <AttachmentSelection
                files={attachments}
                onChange={(files) => {
                  setAttachments(files);
                  requestId.current = null;
                }}
                busy={busy || attachmentPicking}
              />
              <div className="composer">
                <div className="composer-tools" ref={toolsRef}>
                  <button
                    ref={toolsButton}
                    className="icon-button add-button"
                    aria-label="Add files and tools"
                    title="Add files and tools"
                    aria-expanded={toolsOpen}
                    aria-controls="composer-tools-panel"
                    onClick={() => setToolsOpen(!toolsOpen)}
                  >
                    <Icon name="plus" />
                  </button>
                  <div
                    id="composer-tools-panel"
                    className="tools-popover"
                    hidden={!toolsOpen}
                  >
                    <div className="popover-heading">Add to your message</div>
                    <DocumentPicker
                      compact
                      client={client}
                      files={attachments}
                      onChange={(files) => {
                        setAttachments(files);
                        requestId.current = null;
                      }}
                      busy={busy || attachmentPicking || research}
                      scope={`${client.origin}:${selected || "new"}:${attachmentEpoch}`}
                      onPicking={setAttachmentPicking}
                      onError={setError}
                    />
                    <AttachmentComposer
                      compact
                      showSelection={false}
                      files={attachments}
                      onChange={(files) => {
                        setAttachments(files);
                        requestId.current = null;
                      }}
                      busy={busy || research || attachmentPicking}
                      scope={`${client.origin}:${selected || "new"}:${attachmentEpoch}`}
                      onPicking={setAttachmentPicking}
                      onError={setError}
                    />

                    <label>
                      <input
                        type="checkbox"
                        checked={research}
                        disabled={
                          !researchCapability?.public_page_reading ||
                          busy ||
                          !!attachments.length ||
                          attachmentPicking
                        }
                        onChange={(e) => {
                          setResearch(e.target.checked);
                          setToolsOpen(false);
                          messageInput.current?.focus();
                          requestId.current = null;
                        }}
                      />{" "}
                      Research this message
                    </label>
                  </div>
                </div>
                <textarea
                  ref={messageInput}
                  rows={1}
                  aria-label="Message"
                  placeholder="Ask anything"
                  value={draft}
                  disabled={busy}
                  onChange={(e) => {
                    setDraft(e.target.value);
                    requestId.current = null;
                  }}
                  onKeyDown={(e) => {
                    if (
                      e.key === "Enter" &&
                      !e.shiftKey &&
                      !e.nativeEvent.isComposing
                    ) {
                      e.preventDefault();
                      void send();
                    }
                  }}
                />
                <DictationButton
                  client={client}
                  value={draft}
                  onChange={(value) => {
                    setDraft(value);
                    requestId.current = null;
                  }}
                  disabled={busy}
                  onError={setError}
                  onListening={setDictating}
                />
                {run && !terminal(run.status) ? (
                  <button
                    className="icon-button send-button"
                    aria-label="Stop"
                    title="Stop generating"
                    onClick={() =>
                      client
                        .request(`/v1/runs/${run.id}/cancel`, "POST")
                        .catch((e) => setError(String(e)))
                    }
                  >
                    <Icon name="stop" />
                  </button>
                ) : (
                  <button
                    className="icon-button send-button primary"
                    aria-label="Send ↑"
                    title="Send message"
                    disabled={
                      busy ||
                      dictating ||
                      attachmentPicking ||
                      !draft.trim() ||
                      !model
                    }
                    onClick={() => void send()}
                  >
                    <Icon name="up" />
                  </button>
                )}
              </div>
              <div className="research-controls">
                <WebPicker
                  value={attachments.length ? "off" : webMode}
                  onChange={(value) => {
                    setWebMode(value);
                    requestId.current = null;
                  }}
                  disabled={busy || !!attachments.length || research}
                />
                <small>
                  {dictating
                    ? "Listening locally — words appear here as you speak. Stop to review and send."
                    : attachments.length
                      ? "Web auto is off while private files are attached."
                      : researchCapability?.search_configured
                        ? "Auto searches when needed and shows sources. Queries use this prompt only."
                        : "Web search is preparing on the PC. Auto uses local answers until ready."}
                </small>
                {research && (
                  <div className="research-options">
                    <div className="research-heading">
                      <span>
                        <Icon name="globe" /> Research
                      </span>
                      <button
                        className="icon-button"
                        aria-label="Turn off Research"
                        onClick={() => {
                          setResearch(false);
                          requestId.current = null;
                        }}
                      >
                        <Icon name="close" />
                      </button>
                    </div>
                    <label>
                      <input
                        type="checkbox"
                        checked={searchWeb}
                        disabled={
                          !researchCapability?.search_configured || busy
                        }
                        onChange={(e) => {
                          setSearchWeb(e.target.checked);
                          requestId.current = null;
                        }}
                      />{" "}
                      Search the web
                    </label>
                    {!researchCapability?.search_configured && (
                      <small>
                        Web search is not configured on your PC. You can still
                        read source URLs.
                      </small>
                    )}
                    <textarea
                      aria-label="Source URLs"
                      placeholder="Public HTTPS source URLs, one per line (up to six)"
                      value={sourceURLs}
                      rows={2}
                      disabled={busy}
                      onChange={(e) => {
                        setSourceURLs(e.target.value);
                        requestId.current = null;
                      }}
                    />
                    <small>
                      {searchWeb
                        ? "Queries based on this message go to public search services. "
                        : "Your PC will read the supplied public pages. "}
                      Earlier messages, attached files and saved memories are
                      not sent with research queries.
                    </small>
                  </div>
                )}
              </div>
              <small className="composer-note" role="status">
                {connection ||
                  (attachmentPicking
                    ? "Reading your file…"
                    : "dsGPT can make mistakes. Check important information.")}
              </small>
            </div>
          </div>
        ) : page === "settings" ? (
          <section>
            <h1>Settings</h1>
            <div className="appearance-setting">
              <div>
                <h2>Appearance</h2>
                <p>Choose how your workspace looks.</p>
              </div>
              <select
                aria-label="Theme"
                value={theme}
                onChange={(e) => setTheme(e.target.value)}
              >
                <option value="system">System</option>
                <option value="light">Light</option>
                <option value="dark">Dark</option>
              </select>
            </div>
            <h2>Models</h2>
            <p>
              Ollama runs the AI on your PC. Standard models keep their original
              training; “-A” marks an altered (abliterated) model. “-NA” means
              unaltered. Setup adds the standard Qwen 3.5 options automatically
              and keeps your existing model. Thinking choices come from the
              selected model, so they may differ from ChatGPT.
            </p>
            <button onClick={() => setPage("models")}>Open Models →</button>
            <h2>Web search</h2>
            <p>
              Web Auto lets your local model decide when public sources would
              help. dsGPT prepares its search service automatically, searches,
              reads pages and cites saved sources. Search queries leave your PC;
              attached files, previous messages and saved memories are excluded.
              Choose Off for private prompts.
            </p>
            <button onClick={() => setPage("search")}>
              Web search status →
            </button>
            <h2>Memory</h2>
            <p>
              Save facts and preferences you want dsGPT to reuse. Memories and
              chat history stay in your PC profile. You can inspect, edit,
              export or delete memories; deleting a memory does not erase text
              already copied into old conversations.
            </p>
            <h2>Your setup and limits</h2>
            <p>
              On a 12 GB GPU / 32 GB RAM PC, Qwen 3.5 9B is the responsive
              standard option; 27B uses RAM as well as GPU memory and can be
              much slower. Chat and Work share one GPU. Local models are not
              GPT-6 and cannot be promised ChatGPT’s quality or context length.
              File limits and model context still apply.
            </p>
            <p>
              Keep your PC awake, Ollama running, and Tailscale connected for
              phone access. Docker supplies isolated builds, document tools and
              web search; you do not need to use its interface. Wireless
              debugging is only for installing/updating or repairing the phone
              connection. Turn it off between updates: Chat, Work, dictation and
              Tailscale still work. This removes the debugging access path and
              avoids its background activity; battery impact varies by device.
            </p>
            <p>
              Live dictation is local: English speech on the PC, or your Pixel’s
              on-device speech recognizer. Allow microphone access once. Words
              can be revised as recognition improves; stop recording to edit
              before sending. No audio recordings are saved.
            </p>
            <button onClick={() => setPage("memory")}>Open Memory →</button>
            <button onClick={() => setPage("recall")}>
              History and retrieval →
            </button>
            <h2>Chats</h2>
            <button onClick={() => setPage("hidden")}>Hidden Chats →</button>
            <h2>Diagnostics</h2>
            <button
              onClick={() => {
                setPage("diagnostics");
                client
                  .request<typeof diagnosticDevices>("/v1/devices")
                  .then(setDiagnosticDevices)
                  .catch((e) => setError(String(e)));
                client
                  .request("/v1/diagnostics/overview")
                  .then(setDiagnostics)
                  .catch((e) => setError(String(e)));
              }}
            >
              Open Diagnostics →
            </button>
            <h2>Connected Devices</h2>
            <button onClick={() => setPage("devices")}>
              Pair a phone / Connected Devices →
            </button>
            <h2>Connection</h2>
            <p>{client.origin}</p>
            <button
              onClick={() =>
                disconnect()
                  .then(() => {
                    setClient(null);
                    setSelected(null);
                    setMessages([]);
                  })
                  .catch((e) => setError(String(e)))
              }
            >
              Disconnect this app
            </button>
          </section>
        ) : page === "hidden" ? (
          <section>
            <button onClick={() => setPage("settings")}>
              ← Settings / Chats
            </button>
            <h1>Hidden Chats</h1>
            <p>
              Hidden chats keep their pin and remain excluded from normal
              search.
            </p>
            {chats.map((c) => (
              <div className="hiddenrow" key={c.id}>
                <span>
                  {c.pinned ? "◆ " : ""}
                  {c.title}
                </span>
                <button onClick={() => void change(c, { hidden: false })}>
                  Unhide
                </button>
              </div>
            ))}
            {more && (
              <button onClick={() => void loadChats(true)}>Load more</button>
            )}
          </section>
        ) : page === "diagnostics" ? (
          <section>
            <button onClick={() => setPage("settings")}>← Settings</button>
            <h1>Diagnostics</h1>
            <p>
              Sanitized backend measurements. Conversation contents and
              credentials are excluded.
            </p>
            <label>
              Include cached phone diagnostics{" "}
              <select
                aria-label="Diagnostic phone"
                value={diagnosticDevice}
                onChange={(e) => {
                  setDiagnosticDevice(e.target.value);
                  setDiagnostics(null);
                }}
              >
                <option value="">Desktop only</option>
                {diagnosticDevices
                  .filter((d) => d.role !== "owner" && !d.revoked)
                  .map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name}
                    </option>
                  ))}
              </select>
            </label>
            {diagnosticDevice && (
              <>
                <p>
                  Cached snapshots show their collection time. A fresh snapshot
                  requires consent on the phone.
                </p>
                <button
                  onClick={() =>
                    client
                      .request(
                        `/v1/diagnostics/collections/${diagnosticDevice}`,
                        "POST",
                      )
                      .then(setDiagnostics)
                      .catch((e) => setError(String(e)))
                  }
                >
                  Request fresh phone snapshot
                </button>
              </>
            )}
            <DiagnosticsPanel value={diagnostics} />
            <button
              onClick={() =>
                client
                  .request("/v1/diagnostics/snapshots", "POST")
                  .then(() => client.request("/v1/diagnostics/overview"))
                  .then(setDiagnostics)
                  .catch((e) => setError(String(e)))
              }
            >
              Save snapshot now
            </button>
            <label>
              <input
                type="checkbox"
                checked={includeBuildLogs}
                onChange={(e) => {
                  setIncludeBuildLogs(e.target.checked);
                  setDiagnostics(null);
                }}
              />
              Include build/test output
            </label>
            {includeBuildLogs && (
              <p>
                Project text, paths or unrecognized secrets may remain. Review
                each included log before sharing.
              </p>
            )}
            {!!diagnostics &&
              typeof diagnostics === "object" &&
              "id" in diagnostics &&
              "sha256" in diagnostics && (
                <button
                  onClick={() =>
                    client
                      .downloadDiagnostics(
                        String(diagnostics.id),
                        String(diagnostics.sha256),
                      )
                      .catch((e) => setError(String(e)))
                  }
                >
                  Save reviewed export…
                </button>
              )}
            <button
              onClick={() =>
                client
                  .request("/v1/diagnostics/exports/preview", "POST", {
                    ...(diagnosticDevice
                      ? { mobile_device: diagnosticDevice }
                      : {}),
                    include_work_logs: includeBuildLogs,
                  })
                  .then(setDiagnostics)
                  .catch((e) => setError(String(e)))
              }
            >
              Preview export
            </button>
          </section>
        ) : null}
        <ToolSetupPanel
          key={`tools:${client.origin}`}
          client={client}
          active={page === "settings"}
        />
        <WorkPanel
          client={client}
          models={models}
          model={model}
          effort={effort}
          active={page === "work"}
        />
        <MemoryPanel client={client} active={page === "memory"} />
        <RecallPanel
          key={`recall:${client.origin}`}
          client={client}
          active={page === "recall"}
        />
        <SearchPanel
          key={`search:${client.origin}`}
          client={client}
          active={page === "search"}
        />
        <DevicesPanel
          key={`devices:${client.origin}`}
          client={client}
          active={page === "devices"}
          onConnectPhone={() => setPhoneRequest((n) => n + 1)}
        />
        <ModelsPanel
          key={client.origin}
          client={client}
          active={page === "models"}
          onModels={setModels}
        />
      </main>
    </div>
  );
}
