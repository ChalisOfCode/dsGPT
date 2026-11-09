import { useEffect, useRef, useState } from "react";
import { DictationButton } from "./Dictation";
import { WebPicker } from "./GenerationControls";
import { Icon } from "./Icon";
import { Client } from "./transport";
import type { Model } from "./types";
import { researchOptions } from "./research";
import { AttachmentComposer, type DraftAttachment } from "./Attachments";
import { DocumentPicker } from "./Documents";
import { WorkUploads } from "./WorkUploads";
import { WorkBuilds } from "./WorkBuilds";
import { WorkSources } from "./WorkSources";
import { WorkAccountReads } from "./WorkAccountReads";

interface Task {
  web_mode?: string;
  public_research?: {
    status: string;
    error_code: string | null;
    public_query: string | null;
    follow_links: boolean;
  };
  source_management?: boolean;
  id: string;
  title: string;
  requirements: string;
  status: string;
  revision: number;
  updated_at: string;
  execution_available: boolean;
  build_target?: string;
  code_execution_available?: boolean;
  blocker: string | null;
  references: {
    total: number;
    pending: number;
    retrieved: number;
    failed: number;
  };
  session: { model_id: string; step: number; summary: string } | null;
}
interface ProjectFile {
  path: string;
  sha256: string;
  bytes: number;
  revision: number;
}
interface Step {
  step: number;
  action: Record<string, unknown>;
  result: unknown;
  created_at: string;
}
const actions: Record<string, string[]> = {
  draft: ["start", "stop"],
  queued: ["pause", "stop"],
  running: ["pause", "stop"],
  paused: ["resume", "stop"],
  blocked: ["resume", "pause", "stop"],
  stopped: ["resume"],
};
const labels: Record<string, string> = {
  start: "Start drafting",
  pause: "Pause",
  resume: "Resume",
  stop: "Stop",
};
const status = (s: string, target = "source") =>
  s === "completed"
    ? target === "source"
      ? "Draft complete"
      : "Build complete"
    : s;

export function WorkPanel({
  client,
  models,
  model,
  effort,
  active,
}: {
  client: Client;
  models: Model[];
  model: string;
  effort: string;
  active: boolean;
}) {
  const [tasks, setTasks] = useState<Task[]>([]),
    [more, setMore] = useState(false);
  const [selected, setSelected] = useState<string | null>(() => {
    try {
      return localStorage.getItem(`dsgpt:${client.origin}:work`);
    } catch {
      return null;
    }
  });
  const [task, setTask] = useState<Task | null>(null),
    [files, setFiles] = useState<ProjectFile[]>([]),
    [steps, setSteps] = useState<Step[]>([]);
  const [sourceFiles, setSourceFiles] = useState<DraftAttachment[]>([]);
  const [pickingSource, setPickingSource] = useState(false);
  const [target, setTarget] = useState("auto");
  const [webMode, setWebMode] = useState("auto");
  const [dictating, setDictating] = useState(false);
  const [startNow, setStartNow] = useState(true);
  const [showTasks, setShowTasks] = useState(false);
  const [publicQuery, setPublicQuery] = useState("");
  const [followLinks, setFollowLinks] = useState(false);
  const [title, setTitle] = useState(""),
    [requirements, setRequirements] = useState("");
  useEffect(() => {
    request.current = null;
  }, [model, effort, webMode]);
  const [note, setNote] = useState(""),
    [editModel, setEditModel] = useState("");
  const [editWeb, setEditWeb] = useState("");
  const [references, setReferences] = useState(""),
    [extraReferences, setExtraReferences] = useState(""),
    [retrySources, setRetrySources] = useState(false);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [refresh, setRefresh] = useState(0);
  const editRevision = useRef<number | null>(null);
  const request = useRef<string | null>(null),
    current = useRef(selected),
    generation = useRef(0);
  const listCount = useRef(50);
  current.current = selected;
  function choose(id: string | null) {
    editRevision.current = null;
    setRefresh((n) => n + 1);
    current.current = id;
    generation.current++;
    setSelected(id);
    setTask(null);
    setFiles([]);
    setSteps([]);
    setNote("");
    setEditModel("");
    setEditWeb("");
    setExtraReferences("");
    setRetrySources(false);
    setError("");
    setNotice("");
    try {
      if (id) localStorage.setItem(`dsgpt:${client.origin}:work`, id);
      else localStorage.removeItem(`dsgpt:${client.origin}:work`);
    } catch {
      /* optional navigation state */
    }
  }
  function accept(t: Task) {
    setTask((old) => (old?.id === t.id && old.revision > t.revision ? old : t));
  }
  useEffect(() => {
    if (!active) return;
    const controller = new AbortController(),
      epoch = ++generation.current;
    let timer: ReturnType<typeof setTimeout>;
    async function sync() {
      try {
        const rows: Task[] = [];
        for (let offset = 0; offset < listCount.current; offset += 50) {
          const batch = await client.request<Task[]>(
            `/v1/work/tasks?limit=50&offset=${offset}`,
            "GET",
            undefined,
            controller.signal,
          );
          rows.push(...batch);
          if (batch.length < 50) break;
        }
        if (epoch !== generation.current || controller.signal.aborted) return;
        setTasks([...new Map(rows.map((t) => [t.id, t])).values()]);
        setMore(rows.length >= listCount.current);
        if (selected) {
          const t = await client.request<Task>(
            `/v1/work/tasks/${selected}`,
            "GET",
            undefined,
            controller.signal,
          );
          const [f, s] = await Promise.all([
            client.request<ProjectFile[]>(
              `/v1/work/tasks/${selected}/files`,
              "GET",
              undefined,
              controller.signal,
            ),
            client.request<Step[]>(
              `/v1/work/tasks/${selected}/steps?after=${Math.max(0, (t.session?.step ?? 0) - 100)}&limit=100`,
              "GET",
              undefined,
              controller.signal,
            ),
          ]);
          if (epoch !== generation.current || controller.signal.aborted) return;
          accept(t);
          setFiles(f);
          setSteps(s);
        }
      } catch (e) {
        if (!controller.signal.aborted && epoch === generation.current)
          setError(String(e));
      } finally {
        if (!controller.signal.aborted && epoch === generation.current)
          timer = setTimeout(sync, 1500);
      }
    }
    void sync();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [active, client, selected, refresh]);
  async function act(action: string) {
    if (!task || busy) return;
    const id = task.id;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const t = await client.request<Task>(
        `/v1/work/tasks/${id}/actions`,
        "POST",
        { action, revision: task.revision },
      );
      if (current.current === id) accept(t);
    } catch (e) {
      setError(
        `${String(e)} The task will refresh; check its state before retrying.`,
      );
    } finally {
      setBusy(false);
      setRefresh((n) => n + 1);
    }
  }
  async function create() {
    if (busy || dictating || pickingSource || !requirements.trim()) return;
    setBusy(true);
    setError("");
    request.current ??= crypto.randomUUID();
    try {
      const urls = researchOptions(true, references).urls;
      if (urls.length) await requireReferences();
      if (publicQuery.trim() || followLinks) {
        const c = await client.request<{
          work?: { public_query_and_links?: boolean };
        }>("/v1/capabilities");
        if (!c.work?.public_query_and_links)
          throw Error("Update the PC backend for Work web research.");
      }
      const t = await client.request<Task>("/v1/work/tasks", "POST", {
        title: title.trim() || requirements.trim().split("\n")[0].slice(0, 90),
        start: startNow,
        reasoning_effort: effort,
        web_mode: sourceFiles.length && webMode !== "on" ? "off" : webMode,
        build_target: target,
        ...(sourceFiles.length
          ? {
              upload_ids: sourceFiles
                .filter((f) => f.upload_id)
                .map((f) => f.upload_id),
              source_files: sourceFiles
                .filter((f) => !f.upload_id)
                .map((f) =>
                  f.original_base64
                    ? { name: f.name, original_base64: f.original_base64 }
                    : { name: f.name, text: f.text },
                ),
            }
          : {}),
        requirements: requirements.trim(),
        model_id: model || models[0]?.id || null,
        request_id: request.current,
        ...(urls.length ? { reference_urls: urls } : {}),
        ...(publicQuery.trim() || followLinks
          ? {
              public_query: publicQuery.trim() || null,
              follow_links: followLinks,
            }
          : {}),
      });
      request.current = null;
      setTitle("");
      setRequirements("");
      setSourceFiles([]);
      setReferences("");
      setPublicQuery("");
      setFollowLinks(false);
      choose(t.id);
      accept(t);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
      setRefresh((n) => n + 1);
    }
  }
  async function requireReferences() {
    const cap = await client.request<{
      work?: { reference_sources?: boolean };
    }>("/v1/capabilities");
    if (!cap.work?.reference_sources)
      throw new Error(
        "Work reference sources require PC backend 0.3.0.dev9 or newer.",
      );
  }
  async function revise(resume = false) {
    if (
      !task ||
      busy ||
      (!note.trim() &&
        !editModel &&
        !editWeb &&
        !extraReferences.trim() &&
        !retrySources)
    )
      return;
    const id = task.id;
    setBusy(true);
    setError("");
    try {
      const urls = researchOptions(true, extraReferences).urls;
      if (urls.length || retrySources) await requireReferences();
      const t = await client.request<Task>(`/v1/work/tasks/${id}`, "PATCH", {
        revision: editRevision.current ?? task.revision,
        ...(resume
          ? { resume: true, reasoning_effort: effort, model_id: model }
          : {}),
        ...(note.trim() ? { note: note.trim() } : {}),
        ...(editModel ? { model_id: editModel } : {}),
        ...(urls.length ? { reference_urls: urls } : {}),
        ...(retrySources ? { retry_sources: true } : {}),
        ...(editWeb ? { web_mode: editWeb } : {}),
      });
      if (current.current === id) {
        accept(t);
        setNote("");
        setEditModel("");
        setEditWeb("");
        setExtraReferences("");
        setRetrySources(false);
        editRevision.current = null;
      }
    } catch (e) {
      setError(
        `${String(e)} Reloaded task state must be reviewed before retrying.`,
      );
    } finally {
      setBusy(false);
      setRefresh((n) => n + 1);
    }
  }
  return (
    <section
      className="work-panel"
      hidden={!active}
      aria-label="Work workspace"
    >
      <div className="work-heading">
        <h1>Work</h1>
        <button onClick={() => choose(null)} disabled={busy}>
          New task
        </button>
      </div>
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      <button
        className="work-history-toggle"
        onClick={() => setShowTasks(!showTasks)}
      >
        {showTasks ? "Hide tasks" : "Recent tasks"}
      </button>
      <div className={`work-grid${showTasks ? " with-history" : ""}`}>
        <nav aria-label="Work tasks" hidden={!showTasks}>
          <button onClick={() => setRefresh((n) => n + 1)}>
            Refresh tasks
          </button>
          {tasks.map((t) => (
            <button
              key={t.id}
              className={selected === t.id ? "selected" : ""}
              disabled={busy}
              onClick={() => choose(t.id)}
            >
              <strong>{t.title}</strong>
              <small>{status(t.status, t.build_target)}</small>
            </button>
          ))}
          {!tasks.length && <p>No tasks loaded.</p>}
          {more && (
            <button
              onClick={() => {
                listCount.current += 50;
                setRefresh((n) => n + 1);
              }}
            >
              Load more tasks
            </button>
          )}
        </nav>
        <div className="work-detail">
          {!selected ? (
            <div className="work-welcome">
              <h2>What can we get done?</h2>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  void create();
                }}
              >
                <div className="composer work-composer">
                  <textarea
                    aria-label="Work prompt"
                    placeholder="Work with dsGPT"
                    rows={3}
                    maxLength={1500000}
                    value={requirements}
                    disabled={busy}
                    onChange={(e) => {
                      setRequirements(e.target.value);
                      request.current = null;
                    }}
                    onKeyDown={(e) => {
                      if (
                        e.key === "Enter" &&
                        !e.shiftKey &&
                        !e.nativeEvent.isComposing
                      ) {
                        e.preventDefault();
                        void create();
                      }
                    }}
                  />
                  <div className="work-composer-actions">
                    <WebPicker
                      value={
                        sourceFiles.length && webMode !== "on" ? "off" : webMode
                      }
                      onChange={setWebMode}
                      disabled={busy}
                    />
                    <span className="spacer" />
                    <DictationButton
                      client={client}
                      value={requirements}
                      active={active}
                      onChange={(value) => {
                        setRequirements(value);
                        request.current = null;
                      }}
                      disabled={busy}
                      onError={setError}
                      onListening={setDictating}
                    />
                    <button
                      className="icon-button send-button primary"
                      type="submit"
                      aria-label="Send Work prompt"
                      disabled={
                        busy ||
                        dictating ||
                        pickingSource ||
                        !requirements.trim() ||
                        !model
                      }
                    >
                      <Icon name="up" />
                    </button>
                  </div>
                </div>
                <small className="composer-note">
                  {dictating
                    ? "Listening locally — words appear in your prompt."
                    : "Tasks continue on your PC. Describe the result you want; press Enter to start."}
                </small>
                <details className="work-options">
                  <summary>Add files and task options</summary>
                  <WorkUploads
                    client={client}
                    files={sourceFiles}
                    onChange={(files) => {
                      setSourceFiles(files);
                      request.current = null;
                    }}
                    busy={busy || pickingSource}
                    onPicking={setPickingSource}
                    onError={setError}
                  />

                  <AttachmentComposer
                    files={sourceFiles.filter((f) => !f.upload_id)}
                    onChange={(files) => {
                      const combined = [
                        ...sourceFiles.filter((f) => f.upload_id),
                        ...files,
                      ];
                      if (combined.length > 4) {
                        setError("Choose up to four Work inputs");
                        return;
                      }
                      setSourceFiles(combined);
                      request.current = null;
                    }}
                    busy={busy || pickingSource}
                    scope={`work:${client.origin}`}
                    onPicking={setPickingSource}
                    onError={setError}
                    purpose="work"
                  />
                  <DocumentPicker
                    client={client}
                    work
                    files={sourceFiles.filter((f) => !f.upload_id)}
                    onChange={(files) => {
                      const combined = [
                        ...sourceFiles.filter((f) => f.upload_id),
                        ...files,
                      ];
                      if (combined.length > 4) {
                        setError("Choose up to four Work inputs");
                        return;
                      }
                      setSourceFiles(combined);
                      request.current = null;
                    }}
                    busy={busy || pickingSource}
                    scope={`work:${client.origin}`}
                    onPicking={setPickingSource}
                    onError={setError}
                  />

                  <label>
                    Output target
                    <select
                      value={target}
                      onChange={(e) => {
                        setTarget(e.target.value);
                        request.current = null;
                      }}
                      disabled={busy}
                    >
                      <option value="auto">Automatic from your prompt</option>
                      <option value="source">Source files only</option>
                      <option value="files">Built files</option>
                      <option value="exe">Windows EXE</option>
                      <option value="apk">Android APK</option>
                    </select>
                  </label>
                  <label>
                    <input
                      type="checkbox"
                      checked={startNow}
                      onChange={(e) => {
                        setStartNow(e.target.checked);
                        request.current = null;
                      }}
                    />
                    Start immediately
                  </label>
                  <label>
                    Task title (optional)
                    <input
                      value={title}
                      maxLength={300}
                      onChange={(e) => {
                        setTitle(e.target.value);
                        request.current = null;
                      }}
                    />
                  </label>
                  <label>
                    Public reference URLs (optional)
                    <textarea
                      value={references}
                      rows={2}
                      onChange={(e) => {
                        setReferences(e.target.value);
                        request.current = null;
                      }}
                    />
                  </label>
                  <label>
                    Public search query (optional)
                    <input
                      value={publicQuery}
                      maxLength={500}
                      onChange={(e) => {
                        setPublicQuery(e.target.value);
                        request.current = null;
                      }}
                    />
                  </label>
                  <label>
                    <input
                      type="checkbox"
                      checked={followLinks}
                      onChange={(e) => {
                        setFollowLinks(e.target.checked);
                        request.current = null;
                      }}
                    />
                    Follow public source links
                  </label>
                  <p>
                    Web Auto can research again throughout the task. With files,
                    it stays off unless you choose Web On. Web On allows public
                    queries based on your task and errors; keep sensitive
                    details out of tasks that use it. A separate public query
                    limits the initial search when Web is off.
                  </p>
                </details>
              </form>
            </div>
          ) : !task ? (
            <p>Loading task…</p>
          ) : (
            <>
              <h2>{task.title}</h2>
              <p className="work-status" aria-label="Task status">
                {status(task.status, task.build_target)} · revision{" "}
                {task.revision} · {task.session?.step ?? 0} steps
              </p>
              <p>
                Model:{" "}
                {models.find((m) => m.id === task.session?.model_id)?.label ||
                  task.session?.model_id ||
                  "None selected"}
              </p>
              {task.blocker && (
                <p role="status">
                  {task.blocker === "local_vision_model_required"
                    ? "Choose a locally installed Ollama vision model to interpret the attached images."
                    : task.blocker}
                </p>
              )}
              {task.public_research &&
                (task.public_research.public_query ||
                  task.public_research.follow_links) && (
                  <p>
                    Public research: {task.public_research.status}. Query:{" "}
                    {task.public_research.public_query || "none"}. Link
                    following:{" "}
                    {task.public_research.follow_links ? "enabled" : "off"}.{" "}
                    {task.public_research.error_code &&
                      `${task.public_research.error_code}. Pause and retry failed sources after correcting the search service.`}
                  </p>
                )}
              {active && (
                <WorkAccountReads
                  key={task.id + ":" + task.revision}
                  client={client}
                  task={task.id}
                  revision={task.revision}
                />
              )}
              <div className="work-actions">
                {(actions[task.status] || []).map((a) => (
                  <button
                    key={a}
                    disabled={
                      busy ||
                      (["start", "resume"].includes(a) &&
                        !task.execution_available)
                    }
                    onClick={() => void act(a)}
                  >
                    {a === "start" &&
                    task.build_target &&
                    task.build_target !== "source"
                      ? "Start build"
                      : labels[a]}
                  </button>
                ))}
              </div>
              <p className="content work-response">
                {task.session?.summary || "No drafting step recorded yet."}
              </p>
              <details>
                <summary>Requirements</summary>
                <pre>{task.requirements}</pre>
              </details>
              {!["queued", "running"].includes(task.status) && (
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    void revise(true);
                  }}
                >
                  <label>
                    Add instructions
                    <textarea
                      value={note}
                      maxLength={1500000}
                      disabled={busy}
                      onChange={(e) => {
                        editRevision.current ??= task.revision;
                        setNote(e.target.value);
                      }}
                    />
                  </label>
                  <DictationButton
                    client={client}
                    value={note}
                    onChange={(value) => {
                      editRevision.current ??= task.revision;
                      setNote(value);
                    }}
                    active={active}
                    disabled={busy}
                    onError={setError}
                    onListening={setDictating}
                  />
                  <button
                    type="submit"
                    className="primary"
                    disabled={busy || dictating || !note.trim()}
                  >
                    Send follow-up
                  </button>
                  <details>
                    <summary>Task update options</summary>
                    <label>
                      Change Work model
                      <select
                        value={editModel}
                        disabled={busy}
                        onChange={(e) => {
                          editRevision.current ??= task.revision;
                          setEditModel(e.target.value);
                        }}
                      >
                        <option value="">Keep current model</option>
                        {models.map((m) => (
                          <option key={m.id} value={m.id}>
                            {m.label}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      Add public reference URLs
                      <textarea
                        rows={3}
                        maxLength={24600}
                        value={extraReferences}
                        disabled={busy}
                        onChange={(e) => {
                          editRevision.current ??= task.revision;
                          setExtraReferences(e.target.value);
                        }}
                      />
                    </label>
                    <p>
                      Up to six public HTTPS URLs, one per line. New pages are
                      read on start or resume; already saved URLs are reused.
                    </p>
                    {!!task.references?.failed && (
                      <label className="checkbox-label">
                        <input
                          type="checkbox"
                          checked={retrySources}
                          disabled={busy}
                          onChange={(e) => {
                            editRevision.current ??= task.revision;
                            setRetrySources(e.target.checked);
                          }}
                        />
                        Retry failed sources on start or resume
                      </label>
                    )}
                    <label>
                      Research during this task
                      <select
                        value={
                          editWeb || (task.web_mode === "off" ? "off" : "on")
                        }
                        disabled={busy}
                        onChange={(e) => {
                          editRevision.current ??= task.revision;
                          setEditWeb(e.target.value);
                        }}
                      >
                        <option value="off">Web Off</option>
                        <option value="on">Web On</option>
                      </select>
                    </label>
                    <p>
                      Web On allows public queries based on this task and its
                      errors, including attached material. Save the change, then
                      resume.
                    </p>
                    <button
                      type="button"
                      onClick={() => void revise()}
                      disabled={
                        busy ||
                        (!note.trim() &&
                          !editModel &&
                          !editWeb &&
                          !extraReferences.trim() &&
                          !retrySources)
                      }
                    >
                      Save task update
                    </button>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => {
                        setNote("");
                        setEditModel("");
                        setEditWeb("");
                        setExtraReferences("");
                        setRetrySources(false);
                        editRevision.current = null;
                        setError("");
                        setRefresh((n) => n + 1);
                      }}
                    >
                      Clear update and reload
                    </button>
                  </details>
                </form>
              )}
              <details className="work-evidence">
                <summary>Sources and execution details</summary>
                {task.references ? (
                  <WorkSources
                    key={`sources:${task.id}`}
                    client={client}
                    taskId={task.id}
                    revision={task.revision}
                    active={active}
                    manageable={!!task.source_management}
                    status={task.status}
                    changed={() => setRefresh((n) => n + 1)}
                  />
                ) : (
                  <p>
                    Reference sources require PC backend 0.3.0.dev9 or newer.
                  </p>
                )}
              </details>
              {task.build_target && task.build_target !== "source" && (
                <WorkBuilds
                  key={`builds:${task.id}`}
                  client={client}
                  taskId={task.id}
                  revision={task.revision}
                  active={active}
                  target={task.build_target}
                  ready={!!task.code_execution_available}
                />
              )}
              <h3>Files ({files.length})</h3>
              <button
                disabled={busy || !files.length}
                onClick={async () => {
                  setBusy(true);
                  setError("");
                  try {
                    if (await client.downloadWork(task.id))
                      setNotice(
                        "Source archive saved. Generated code has not been built or tested.",
                      );
                  } catch (e) {
                    setError(String(e));
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Save source ZIP…
              </button>
              {files.map((f) => (
                <details key={f.path}>
                  <summary>
                    {f.path} · {f.bytes} bytes
                  </summary>
                  <small>
                    Revision {f.revision} · SHA256 {f.sha256}
                  </small>
                </details>
              ))}
              <details className="work-evidence">
                <summary>Recent activity</summary>
                <p>
                  Latest 100 recorded steps. Generated text is shown as data; no
                  commands are run.
                </p>
                {[...steps].reverse().map((s) => (
                  <details key={s.step}>
                    <summary>
                      Step {s.step} ·{" "}
                      {String(s.action.tool || "invalid action")} ·{" "}
                      {String(s.action.summary || "")}
                    </summary>
                    <pre>
                      {JSON.stringify(
                        { action: s.action, result: s.result },
                        null,
                        2,
                      )}
                    </pre>
                  </details>
                ))}
              </details>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
