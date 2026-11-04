import { useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { native } from "./transport";

interface Preview {
  archive_sha256: string;
  selected_conversations: number;
  selected_messages: number;
  conversations: {
    source_id: string;
    title: string;
    messages: number;
    omissions: unknown;
  }[];
  limitations: string[];
}
export function HistoryImport({
  origin,
  onImported,
}: {
  origin: string;
  onImported: () => void;
}) {
  const [preview, setPreview] = useState<Preview | null>(null);
  const [accepted, setAccepted] = useState(false),
    [busy, setBusy] = useState(false);
  const [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const request = useRef<string | null>(null);
  if (!native || origin !== "http://127.0.0.1:18765") return null;
  return (
    <section aria-label="Local archive import">
      <h3>Import a local ChatGPT archive</h3>
      <p>
        Choose a ZIP or conversations JSON on this PC. The original archive
        stays on this PC and is never uploaded. Only supported visible text from
        each conversation's active branch is imported.
      </p>
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      <button
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          setError("");
          setNotice("");
          try {
            const p = await invoke<Preview | null>("preview_history_import");
            if (p) {
              setPreview(p);
              setAccepted(false);
              request.current = crypto.randomUUID();
            }
          } catch (e) {
            setError(String(e));
          } finally {
            setBusy(false);
          }
        }}
      >
        Choose archive and preview…
      </button>
      {preview && (
        <>
          <p>
            {preview.selected_conversations} conversations ·{" "}
            {preview.selected_messages} messages
          </p>
          <p>Archive SHA256: {preview.archive_sha256}</p>
          <ul>
            {preview.limitations.map((text, i) => (
              <li key={i}>{text}</li>
            ))}
          </ul>
          <details>
            <summary>Review conversations and omitted content</summary>
            {preview.conversations.map((c) => (
              <article key={c.source_id}>
                <h4>{c.title}</h4>
                <p>{c.messages} supported messages</p>
                <pre>{JSON.stringify(c.omissions, null, 2)}</pre>
              </article>
            ))}
          </details>
          <label>
            <input
              type="checkbox"
              checked={accepted}
              disabled={busy}
              onChange={(e) => setAccepted(e.target.checked)}
            />
            I reviewed the omissions and accept restarting the backend to
            import. Active work may be interrupted; finish or pause it first.
          </label>
          <button
            disabled={busy || !accepted}
            onClick={async () => {
              setBusy(true);
              setError("");
              try {
                await invoke("apply_history_import", {
                  sha256: preview.archive_sha256,
                  requestId: request.current,
                  confirmRestart: accepted,
                });
                setPreview(null);
                setAccepted(false);
                request.current = null;
                setNotice(
                  "Import recorded and backend restarted. Review imported sources below.",
                );
                onImported();
              } catch (e) {
                setError(
                  `${String(e)} This request retains its retry identity. Review imported history before retrying.`,
                );
              } finally {
                setBusy(false);
              }
            }}
          >
            Import reviewed archive
          </button>
        </>
      )}
    </section>
  );
}
