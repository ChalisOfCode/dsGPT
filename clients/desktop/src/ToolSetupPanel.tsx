import { useEffect, useRef, useState } from "react";
import { Client } from "./transport";
interface Setup {
  docker_installed: boolean;
  sandbox: { configured: boolean; ready: boolean; error_code: string | null };
  job: {
    id: string;
    status: string;
    error_code: string | null;
    log: string;
  } | null;
  help: string;
}
export function ToolSetupPanel({
  client,
  active,
}: {
  client: Client;
  active: boolean;
}) {
  const [state, setState] = useState<Setup | null>(null),
    [owner, setOwner] = useState(false);
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const request = useRef<string | null>(null);
  useEffect(() => {
    if (!active) return;
    let live = true;
    async function refresh() {
      try {
        const c = await client.request<{
          permissions: { search_administration: boolean };
        }>("/v1/capabilities");
        if (!live) return;
        setOwner(c.permissions.search_administration);
        if (!c.permissions.search_administration) return;
        const s = await client.request<Setup>("/v1/tools/setup");
        if (live) {
          setState(s);
          if (s.job?.id === request.current && s.job?.status !== "running")
            request.current = null;
        }
      } catch (e) {
        if (live) setError(String(e));
      }
    }
    void refresh();
    const timer = setInterval(() => void refresh(), 3000);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [client, active]);
  return (
    <section hidden={!active} aria-label="Isolated tool setup">
      <h2>Document and development tools</h2>
      <p>
        Install the local tools for PDF text, OCR, images, spreadsheets,
        presentations and isolated builds. Downloads contain public software
        only. Docker Desktop with Linux containers must be running on the PC.
      </p>
      {error && <p role="alert">{error}</p>}
      {!owner ? (
        <p>The desktop owner manages tool installation.</p>
      ) : (
        <>
          <p>
            {state?.sandbox.ready
              ? "Isolated tools verified"
              : (state?.sandbox.error_code ?? "Checking tools…")}
          </p>
          {state && !state.docker_installed && (
            <p>
              Install Docker Desktop on the PC, start Linux containers, then
              return here. Your chats and files stay on the PC.
            </p>
          )}
          <button
            disabled={
              busy ||
              state?.job?.status === "running" ||
              !state?.docker_installed
            }
            onClick={async () => {
              setBusy(true);
              setError("");
              request.current ??= crypto.randomUUID();
              try {
                await client.request(
                  `/v1/tools/setup/${request.current}`,
                  "POST",
                );
                setState(await client.request<Setup>("/v1/tools/setup"));
              } catch (e) {
                setError(String(e) + " Retry uses the same setup request.");
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy
              ? "Starting…"
              : state?.job?.status === "running"
                ? "Installing tools…"
                : "Install / repair isolated tools"}
          </button>
          <button
            disabled={
              busy ||
              !state?.sandbox.configured ||
              state?.job?.status === "running"
            }
            onClick={async () => {
              setBusy(true);
              setError("");
              try {
                await client.request("/v1/work/sandbox/probe", "POST");
                setState(await client.request<Setup>("/v1/tools/setup"));
              } catch (e) {
                setError(String(e));
              } finally {
                setBusy(false);
              }
            }}
          >
            Verify installed tools
          </button>
          {state?.job && (
            <>
              <p>
                Setup: {state.job.status} {state.job.error_code}
              </p>
              <details>
                <summary>Setup log</summary>
                <pre>{state.job.log}</pre>
              </details>
            </>
          )}
        </>
      )}
    </section>
  );
}
