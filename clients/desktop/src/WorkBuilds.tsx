import { useEffect, useRef, useState } from "react";
import { Client } from "./transport";

interface Receipt {
  id: string;
  step: number;
  status: string;
  snapshot_sha256: string;
  cleanup_pending: boolean;
}
interface Artifact {
  id: string;
  execution_id: string;
  path: string;
  bytes: number;
  sha256: string;
}

export function WorkBuilds({
  client,
  taskId,
  revision,
  active,
  target,
  ready,
}: {
  client: Client;
  taskId: string;
  revision: number;
  active: boolean;
  target: string;
  ready: boolean;
}) {
  const [receipts, setReceipts] = useState<Receipt[]>([]);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [limit, setLimit] = useState(50);
  const [detail, setDetail] = useState("");
  const [validation, setValidation] = useState("");
  const generation = useRef(0);
  useEffect(() => {
    generation.current += 1;
    setDetail("");
    setValidation("");
  }, [taskId, revision, active]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try {
        const r: Receipt[] = [],
          a: Artifact[] = [];
        for (let offset = 0; offset < limit; offset += 50) {
          const [rr, aa] = await Promise.all([
            client.request<Receipt[]>(
              `/v1/work/tasks/${taskId}/executions?limit=50&offset=${offset}`,
              "GET",
              undefined,
              controller.signal,
            ),
            client.request<Artifact[]>(
              `/v1/work/tasks/${taskId}/artifacts?limit=50&offset=${offset}`,
              "GET",
              undefined,
              controller.signal,
            ),
          ]);
          r.push(...rr);
          a.push(...aa);
          if (rr.length < 50 && aa.length < 50) break;
        }
        if (!controller.signal.aborted) {
          setReceipts(r);
          setArtifacts(a);
        }
      } catch (e) {
        if (!controller.signal.aborted) setError(String(e));
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(refresh, 2500);
      }
    }
    void refresh();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [client, taskId, revision, active, limit]);
  return (
    <section aria-label="Build evidence">
      <h3>Results</h3>
      {error && <p role="alert">{error}</p>}
      <details>
        <summary>Build details</summary>
        <p>Build target: {target}</p>
        <p>
          {ready
            ? "Isolated runner ready."
            : "Isolated runner unavailable. Check PC configuration and probe status."}{" "}
          Interrupted commands are never replayed automatically.
        </p>
        <h4>Execution receipts</h4>
        {receipts.map((r) => (
          <details key={r.id}>
            <summary>
              Step {r.step} · {r.status}
              {r.cleanup_pending ? " · cleanup pending" : ""}
            </summary>
            <p>Source snapshot SHA256: {r.snapshot_sha256}</p>
            <button
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                setDetail("");
                setValidation("");
                try {
                  const version = generation.current;
                  const response = await client.request<Record<string, unknown>>(
                    `/v1/work/tasks/${taskId}/executions/${r.id}`,
                  );
                  if (version === generation.current) {
                    setDetail(JSON.stringify(response, null, 2));
                    const value = response.document_validation_summary;
                    setValidation(typeof value === "string" && value.length <= 2000 ? value : "");
                  }
                } catch (e) {
                  setError(String(e));
                } finally {
                  setBusy(false);
                }
              }}
            >
              Read receipt and logs
            </button>
          </details>
        ))}
        {!!detail && (
          <details open>
            <summary>Recorded command and result</summary>
            <pre>{detail}</pre>
          </details>
        )}
      </details>
      {validation && <p role="status" aria-label="Document validation">{validation}</p>}
      <h4>Downloads</h4>
      <p>
        Artifacts belong to the recorded execution; earlier outputs may predate
        current source changes.
      </p>
      {artifacts.map((a) => (
        <details key={a.id}>
          <summary>
            {a.path} · {a.bytes} bytes
          </summary>
          <p>Execution: {a.execution_id}</p>
          <p>SHA256: {a.sha256}</p>
          <button
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await client.downloadArtifact(
                  taskId,
                  a.id,
                  a.sha256,
                  a.bytes,
                  a.path,
                );
              } catch (e) {
                setError(String(e));
              } finally {
                setBusy(false);
              }
            }}
          >
            Save artifact…
          </button>
        </details>
      ))}
      {!artifacts.length && <p>No collected artifacts yet.</p>}
      {(receipts.length >= limit || artifacts.length >= limit) && (
        <button onClick={() => setLimit((n) => n + 50)}>
          Load more build evidence
        </button>
      )}
    </section>
  );
}
