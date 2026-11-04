import { useEffect, useRef, useState } from "react";
import { Client, openSource } from "./transport";
import type { Model } from "./types";

interface Asset {
  id: string;
  name: string;
  kind: string;
  size: number;
  license: string;
  source: string;
  sha256: string;
  purpose: string;
}
interface Download {
  id: string;
  asset_id: string;
  name: string;
  status: string;
  downloaded: number;
  total: number;
  error_code: string | null;
}
interface Runtime {
  id: string;
  platform: string;
  supported_here: boolean;
  installed: boolean;
  assets: string[];
}
interface Registered extends Model {
  runtime: string;
  managed: boolean;
  configuration_owned: boolean;
}
interface RuntimeStatus {
  state: string;
  model_id: string | null;
  busy: boolean;
  error_code: string | null;
}
const size = (bytes: number) => `${(bytes / 1024 ** 2).toFixed(1)} MiB`;
const resumable = (d: Download) =>
  ["paused", "cancelled", "failed"].includes(d.status);
const removable = (d: Download) => resumable(d) || d.status === "downloaded";

export function ModelsPanel({
  client,
  active,
  onModels,
}: {
  client: Client;
  active: boolean;
  onModels: (models: Model[]) => void;
}) {
  const [allowed, setAllowed] = useState<boolean | null>(null),
    [assets, setAssets] = useState<Asset[]>([]),
    [downloads, setDownloads] = useState<Download[]>([]),
    [runtimes, setRuntimes] = useState<Runtime[]>([]),
    [models, setModels] = useState<Registered[]>([]),
    [runtime, setRuntime] = useState<RuntimeStatus | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [refresh, setRefresh] = useState(0),
    [tab, setTab] = useState("library"),
    [confirm, setConfirm] = useState<{
      title: string;
      detail: string;
      path: string;
    } | null>(null);
  const [assetId, setAssetId] = useState(""),
    [runtimeId, setRuntimeId] = useState(""),
    [id, setId] = useState(""),
    [name, setName] = useState(""),
    [context, setContext] = useState("4096"),
    [output, setOutput] = useState("1024"),
    [gpu, setGpu] = useState("0"),
    [external, setExternal] = useState(false),
    [engine, setEngine] = useState("ollama"),
    [endpoint, setEndpoint] = useState("http://127.0.0.1:11434"),
    [runtimeModel, setRuntimeModel] = useState(""),
    [abliterated, setAbliterated] = useState(false);
  const epoch = useRef(0),
    mutating = useRef(false);
  useEffect(() => {
    if (!active || busy) return;
    const abort = new AbortController();
    const own = ++epoch.current;
    async function load() {
      try {
        const cap = await client.request<{
          permissions: { model_management: boolean };
        }>("/v1/capabilities", "GET", undefined, abort.signal);
        if (abort.signal.aborted || own !== epoch.current) return;
        setAllowed(cap.permissions.model_management);
        if (!cap.permissions.model_management) return;
        const [a, d, r, m, s] = await Promise.all([
          client.request<Asset[]>(
            "/v1/model-catalog",
            "GET",
            undefined,
            abort.signal,
          ),
          client.request<Download[]>(
            "/v1/downloads",
            "GET",
            undefined,
            abort.signal,
          ),
          client.request<Runtime[]>(
            "/v1/runtimes",
            "GET",
            undefined,
            abort.signal,
          ),
          client.request<Registered[]>(
            "/v1/models",
            "GET",
            undefined,
            abort.signal,
          ),
          client.request<RuntimeStatus>(
            "/v1/runtime/status",
            "GET",
            undefined,
            abort.signal,
          ),
        ]);
        if (abort.signal.aborted || own !== epoch.current) return;
        setAssets(a);
        setDownloads(d);
        setRuntimes(r);
        setModels(m);
        setRuntime(s);
        onModels(m);
      } catch (e) {
        if (!abort.signal.aborted && own === epoch.current) setError(String(e));
      }
    }
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      await load();
      if (!abort.signal.aborted) timer = setTimeout(poll, 2000);
    }
    void poll();
    return () => {
      abort.abort();
      clearTimeout(timer);
      epoch.current++;
    };
  }, [client, active, busy, refresh, onModels]);
  async function mutate(
    path: string,
    method = "POST",
    body?: unknown,
    message = "Updated. Review the current state below.",
  ) {
    if (mutating.current || !allowed) return;
    mutating.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await client.request(path, method, body);
      setNotice(message);
    } catch (e) {
      setError(
        `${String(e)} Check the refreshed state before retrying. Downloads must finish before installation; registrations must be forgotten before their files can be removed.`,
      );
    } finally {
      mutating.current = false;
      setBusy(false);
      setConfirm(null);
      setRefresh((v) => v + 1);
    }
  }
  const downloaded = (key: string) =>
    downloads.some((d) => d.asset_id === key && d.status === "downloaded");
  const canRegister =
    Number.isInteger(+context) &&
    +context >= 512 &&
    +context <= 131072 &&
    Number.isInteger(+output) &&
    +output >= 1 &&
    +output < +context &&
    /^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$/.test(id) &&
    !!name.trim() &&
    (external
      ? !!runtimeModel.trim()
      : downloaded(assetId) &&
        runtimes.some(
          (r) => r.id === runtimeId && r.installed && r.supported_here,
        ) &&
        Number.isInteger(+gpu) &&
        +gpu >= 0 &&
        +gpu <= 999);
  return (
    <section
      className="models-panel"
      aria-label="Models workspace"
      hidden={!active}
    >
      <h1>Models</h1>
      <p>
        Setup adds standard Qwen 3.5 models automatically while retaining your
        existing altered model. 9B favors responsiveness; 27B uses more memory
        and is slower on a 12 GB GPU. -A means abliterated; -NA means unaltered.
        These are local models, not hosted GPT models. The controls below are
        for optional manual model management.
      </p>
      <button
        disabled={busy}
        onClick={() => {
          setError("");
          setRefresh((v) => v + 1);
        }}
      >
        Refresh models
      </button>
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      {busy && (
        <p role="status">
          Applying change on your PC… Verification may take a while.
        </p>
      )}
      {allowed === null && !error && <p>Checking device permissions…</p>}
      {allowed === false && (
        <p>
          This device cannot manage models. On the desktop, generate a new
          pairing code with “Allow model management”, then pair this phone
          again.
        </p>
      )}
      {allowed && (
        <>
          <nav className="model-tabs" aria-label="Model settings">
            {[
              ["library", "Model Library"],
              ["runtimes", "Runtimes"],
              ["registered", "Available models"],
              ["add", "Add model"],
            ].map(([key, label]) => (
              <button
                key={key}
                aria-pressed={tab === key}
                onClick={() => setTab(key)}
              >
                {label}
              </button>
            ))}
          </nav>
          {tab === "library" && (
            <>
              <p>
                The current models are integration fixtures. Target GPU
                benchmarks and the final model recommendations are still
                pending.
              </p>
              {assets.map((a) => {
                const d = downloads.find((d) => d.asset_id === a.id);
                return (
                  <article
                    className="model-card"
                    key={a.id}
                    aria-label={a.name}
                  >
                    <h2>{a.name}</h2>
                    <p>
                      {a.kind === "model" ? "Model weights" : "Runtime archive"}{" "}
                      · {size(a.size)} · {a.license}
                    </p>
                    <p>{a.purpose}</p>
                    <details>
                      <summary>Source and verification</summary>
                      <p className="source-url">{a.source}</p>
                      <button
                        onClick={() =>
                          void openSource(a.source).catch((e) =>
                            setError(String(e)),
                          )
                        }
                      >
                        Open publisher page
                      </button>
                      <p className="source-url">SHA-256: {a.sha256}</p>
                    </details>
                    {d ? (
                      <>
                        <p>
                          {d.status} · {size(d.downloaded)} / {size(d.total)}
                          {d.error_code ? ` · ${d.error_code}` : ""}
                        </p>
                        <progress
                          value={d.downloaded}
                          max={d.total}
                          aria-label={`Download progress for ${a.name}`}
                        />
                        <div className="model-actions">
                          {["queued", "downloading", "verifying"].includes(
                            d.status,
                          ) && (
                            <button
                              disabled={busy}
                              onClick={() =>
                                void mutate(
                                  `/v1/downloads/${d.id}/actions`,
                                  "POST",
                                  { action: "pause" },
                                )
                              }
                            >
                              Pause download
                            </button>
                          )}
                          {resumable(d) && (
                            <button
                              disabled={busy}
                              onClick={() =>
                                void mutate(
                                  `/v1/downloads/${d.id}/actions`,
                                  "POST",
                                  { action: "resume" },
                                )
                              }
                            >
                              Resume download
                            </button>
                          )}
                          {[
                            "queued",
                            "downloading",
                            "verifying",
                            "paused",
                            "failed",
                          ].includes(d.status) && (
                            <button
                              disabled={busy}
                              onClick={() =>
                                void mutate(
                                  `/v1/downloads/${d.id}/actions`,
                                  "POST",
                                  { action: "cancel" },
                                  "Download cancelled. Partial files remain until you remove them.",
                                )
                              }
                            >
                              Cancel download
                            </button>
                          )}
                          {removable(d) && (
                            <button
                              disabled={busy}
                              onClick={() =>
                                setConfirm({
                                  title: `Remove ${a.name}?`,
                                  detail:
                                    "This deletes this dsGPT-owned download, including any partial file. Forget attached models and remove dependent runtime installations first. Existing Ollama and Prometheus files are preserved.",
                                  path: `/v1/downloads/${d.id}`,
                                })
                              }
                            >
                              Remove download…
                            </button>
                          )}
                        </div>
                      </>
                    ) : (
                      <button
                        disabled={busy}
                        onClick={() =>
                          void mutate(
                            "/v1/downloads",
                            "POST",
                            { asset_id: a.id },
                            "Download queued on your PC. It continues when this screen closes.",
                          )
                        }
                      >
                        Download asset
                      </button>
                    )}
                  </article>
                );
              })}
            </>
          )}
          {tab === "runtimes" && (
            <>
              <p>
                Managed runtime: {runtime?.state || "unknown"}
                {runtime?.model_id ? ` · ${runtime.model_id}` : ""}
                {runtime?.busy ? " · busy" : ""}
                {runtime?.error_code ? ` · ${runtime.error_code}` : ""}
              </p>
              <button
                disabled={busy || runtime?.busy || runtime?.state !== "loaded"}
                onClick={() =>
                  void mutate(
                    "/v1/runtime/unload",
                    "POST",
                    undefined,
                    "Managed model unloaded. Existing external runtimes are unchanged.",
                  )
                }
              >
                Unload managed model
              </button>
              {runtimes.map((r) => (
                <article className="model-card" key={r.id}>
                  <h2>{r.id}</h2>
                  <p>
                    {r.platform} ·{" "}
                    {r.supported_here
                      ? "Matches backend platform"
                      : "For a different backend platform"}{" "}
                    · {r.installed ? "Installed" : "Not installed"}
                  </p>
                  <p>
                    Required downloads:{" "}
                    {r.assets
                      .map(
                        (id) =>
                          `${id} (${downloaded(id) ? "verified" : "needed"})`,
                      )
                      .join(", ")}
                  </p>
                  {r.installed ? (
                    <button
                      disabled={busy || runtime?.busy}
                      onClick={() =>
                        setConfirm({
                          title: `Remove ${r.id}?`,
                          detail:
                            "This removes this dsGPT-owned runtime installation. Forget its attached models first. Downloaded archives remain available.",
                          path: `/v1/runtimes/${r.id}`,
                        })
                      }
                    >
                      Remove runtime…
                    </button>
                  ) : (
                    <button
                      disabled={
                        busy ||
                        runtime?.busy ||
                        !r.supported_here ||
                        !r.assets.every(downloaded)
                      }
                      onClick={() =>
                        void mutate(
                          `/v1/runtimes/${r.id}/install`,
                          "POST",
                          undefined,
                          "Runtime installed and verified. You can now add a downloaded model.",
                        )
                      }
                    >
                      Install runtime
                    </button>
                  )}
                </article>
              ))}
            </>
          )}
          {tab === "registered" && (
            <>
              {models.length === 0 && (
                <p>
                  No models configured. Start in Model Library or register an
                  existing local runtime.
                </p>
              )}
              {models.map((m) => (
                <article className="model-card" key={m.id}>
                  <h2>{m.label}</h2>
                  <p>
                    {m.id} · {m.runtime} ·{" "}
                    {m.managed ? "Managed by dsGPT" : "Existing local runtime"}
                  </p>
                  <p>
                    Context {m.context} · maximum output {m.output_tokens} ·
                    performance not benchmarked
                  </p>
                  {m.configuration_owned ? (
                    <p>Defined in the backend configuration file.</p>
                  ) : (
                    <button
                      disabled={busy || runtime?.busy}
                      onClick={() =>
                        setConfirm({
                          title: `Forget ${m.label}?`,
                          detail:
                            "This removes its registration from Chat and Work. Model files remain on disk. Active requests must finish or pause first.",
                          path: `/v1/models/${encodeURIComponent(m.id)}`,
                        })
                      }
                    >
                      Forget model…
                    </button>
                  )}
                </article>
              ))}
            </>
          )}
          {tab === "add" && (
            <form
              className="model-form"
              onSubmit={(e) => {
                e.preventDefault();
                if (canRegister)
                  void mutate(
                    external ? "/v1/models/register" : "/v1/models/managed",
                    "POST",
                    {
                      id,
                      name: name.trim(),
                      context: +context,
                      output_tokens: +output,
                      ...(external
                        ? {
                            runtime: engine,
                            endpoint,
                            runtime_model: runtimeModel,
                            abliterated,
                          }
                        : {
                            asset_id: assetId,
                            runtime_id: runtimeId,
                            gpu_layers: +gpu,
                          }),
                    },
                    "Model added. It is available in Chat and Work; loading is checked on first use.",
                  );
              }}
            >
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={external}
                  disabled={busy}
                  onChange={(e) => setExternal(e.target.checked)}
                />
                Use an existing local Ollama or llama.cpp runtime
              </label>
              <label>
                Model ID
                <input
                  aria-label="Model ID"
                  value={id}
                  maxLength={100}
                  disabled={busy}
                  onChange={(e) => setId(e.target.value)}
                  placeholder="my-local-model"
                  required
                  pattern="[A-Za-z0-9][A-Za-z0-9_.-]{0,99}"
                />
              </label>
              <label>
                Display name
                <input
                  aria-label="Display name"
                  value={name}
                  maxLength={200}
                  disabled={busy}
                  onChange={(e) => setName(e.target.value)}
                  required
                />
              </label>
              {external ? (
                <>
                  <p>
                    The runtime must already be running on the backend PC.
                    Registration verifies local model metadata and leaves its
                    weights unchanged.
                  </p>
                  <label>
                    Runtime type
                    <select
                      value={engine}
                      disabled={busy}
                      onChange={(e) => {
                        setEngine(e.target.value);
                        setEndpoint(
                          e.target.value === "ollama"
                            ? "http://127.0.0.1:11434"
                            : "http://127.0.0.1:8080",
                        );
                      }}
                    >
                      <option value="ollama">Ollama</option>
                      <option value="llama.cpp">llama.cpp</option>
                    </select>
                  </label>
                  <label>
                    Local runtime address
                    <input
                      aria-label="Local runtime address"
                      value={endpoint}
                      disabled={busy}
                      onChange={(e) => setEndpoint(e.target.value)}
                      required
                    />
                  </label>
                  <label>
                    Runtime model identifier
                    <input
                      aria-label="Runtime model identifier"
                      value={runtimeModel}
                      disabled={busy}
                      onChange={(e) => setRuntimeModel(e.target.value)}
                      required
                      maxLength={200}
                    />
                  </label>
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={abliterated}
                      disabled={busy}
                      onChange={(e) => setAbliterated(e.target.checked)}
                    />
                    Label this model as abliterated
                  </label>
                </>
              ) : (
                <>
                  <label>
                    Downloaded model
                    <select
                      aria-label="Downloaded model"
                      value={assetId}
                      disabled={busy}
                      onChange={(e) => setAssetId(e.target.value)}
                    >
                      <option value="">Choose verified weights</option>
                      {assets
                        .filter((a) => a.kind === "model" && downloaded(a.id))
                        .map((a) => (
                          <option key={a.id} value={a.id}>
                            {a.name}
                          </option>
                        ))}
                    </select>
                  </label>
                  <label>
                    Installed runtime
                    <select
                      aria-label="Installed runtime"
                      value={runtimeId}
                      disabled={busy}
                      onChange={(e) => {
                        setRuntimeId(e.target.value);
                        setGpu("0");
                      }}
                    >
                      <option value="">Choose a runtime</option>
                      {runtimes
                        .filter((r) => r.supported_here && r.installed)
                        .map((r) => (
                          <option key={r.id} value={r.id}>
                            {r.id}
                          </option>
                        ))}
                    </select>
                  </label>
                  <label>
                    GPU layers
                    <input
                      aria-label="GPU layers"
                      type="number"
                      min={0}
                      max={999}
                      value={gpu}
                      disabled={busy || !runtimeId.endsWith("windows-cuda12")}
                      onChange={(e) => setGpu(e.target.value)}
                      required
                    />
                  </label>
                  <small>
                    0 uses CPU. CUDA offload and suitable context sizes still
                    need testing on your GPU.
                  </small>
                </>
              )}
              <label>
                Context tokens
                <input
                  aria-label="Context tokens"
                  type="number"
                  min={512}
                  max={131072}
                  value={context}
                  disabled={busy}
                  onChange={(e) => setContext(e.target.value)}
                  required
                />
              </label>
              <label>
                Maximum output tokens
                <input
                  aria-label="Maximum output tokens"
                  type="number"
                  min={1}
                  max={Math.max(1, +context - 1)}
                  value={output}
                  disabled={busy}
                  onChange={(e) => setOutput(e.target.value)}
                  required
                />
              </label>
              <small>
                Output must be smaller than the context. These starting values
                are unbenchmarked.
              </small>
              <button
                className="primary"
                disabled={busy || runtime?.busy || !canRegister}
              >
                Add configured model
              </button>
            </form>
          )}
          {confirm && (
            <div
              className="model-confirm"
              role="dialog"
              aria-modal="false"
              aria-label={confirm.title}
            >
              <h2>{confirm.title}</h2>
              <p>{confirm.detail}</p>
              <button
                disabled={busy}
                onClick={() => void mutate(confirm.path, "DELETE")}
              >
                Confirm removal
              </button>
              <button disabled={busy} onClick={() => setConfirm(null)}>
                Keep it
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
