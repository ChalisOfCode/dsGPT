import { useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { Client, native } from "./transport";

export interface DraftAttachment {
  name: string;
  text: string;
  original_base64?: string;
  upload_id?: string;
  upload_bytes?: number;
  document?: { notice: string };
}
export interface AttachmentRecord {
  id: string;
  message_id: string;
  name: string;
  bytes: number;
  sha256: string;
  created_at: string;
  removed: boolean;
  document?: { notice: string };
}
const extensions = new Set(
  "txt md markdown rst csv tsv json jsonl yaml yml toml ini xml py js jsx ts tsx css html htm rs kt kts java go rb php c h cpp hpp cs swift sql sh ps1 log tex".split(
    " ",
  ),
);
export function validateAttachments(files: DraftAttachment[]) {
  if (files.length > 4)
    throw new Error("Use up to four text files per message.");
  let total = 0,
    originals = 0;
  for (const file of files) {
    const stem = file.name.split(".")[0].toUpperCase();
    if (
      !file.name ||
      file.name.length > 160 ||
      /[\\/<>:"|?*\x00-\x1f\x7f]/.test(file.name) ||
      /[ .]$/.test(file.name) ||
      /^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$/.test(stem) ||
      !(file.original_base64
        ? /\.(docx|pdf|png|jpe?g|webp|xlsx|pptx|zip)$/i.test(file.name)
        : extensions.has(file.name.split(".").pop()?.toLowerCase() || "")) ||
      file.name.lastIndexOf(".") <= 0
    )
      throw new Error(
        "Choose a supported text/code file with a portable filename.",
      );
    if (/[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(file.text))
      throw new Error("Binary/control data is not supported.");
    if (file.original_base64) {
      const size = atob(file.original_base64).length;
      originals += size;
      if (size > 524288 || originals > 786432)
        throw Error("Originals: 512 KiB each, 768 KiB total.");
    }
    const size = new TextEncoder().encode(file.text).length;
    total += size;
    if (size > 65536 || total > 131072)
      throw new Error(
        "Text files are limited to 64 KiB each and 128 KiB per message.",
      );
  }
}
export async function readTextFile(file: File): Promise<DraftAttachment> {
  if (file.size > 65536)
    throw new Error("Choose a text file no larger than 64 KiB.");
  const data = await file.arrayBuffer();
  if (data.byteLength > 65536) throw new Error("Text file exceeds 64 KiB.");
  // Preserve a UTF-8 BOM in the saved content/hash; reject replacement decoding.
  try {
    return {
      name: file.name,
      text: new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(
        data,
      ),
    };
  } catch {
    throw new Error("Choose a valid UTF-8 text file.");
  }
}

export function AttachmentComposer({
  files,
  onChange,
  busy,
  scope,
  onPicking,
  onError,
  purpose = "chat",
  compact = false,
  showSelection = true,
}: {
  files: DraftAttachment[];
  onChange: (files: DraftAttachment[]) => void;
  busy: boolean;
  scope: string;
  onPicking: (value: boolean) => void;
  onError: (error: string) => void;
  purpose?: "chat" | "work";
  compact?: boolean;
  showSelection?: boolean;
}) {
  const input = useRef<HTMLInputElement>(null),
    currentScope = useRef(scope),
    serial = useRef(0);
  const [picking, setPicking] = useState(false);
  currentScope.current = scope;
  useEffect(() => {
    serial.current++;
    setPicking(false);
    onPicking(false);
  }, [scope]);
  async function pick(selected?: FileList) {
    if (busy || picking) return;
    const startedScope = scope,
      own = ++serial.current;
    setPicking(true);
    onPicking(true);
    try {
      if (selected && files.length + selected.length > 4)
        throw new Error("Use up to four text files.");
      const chosen = selected
        ? await Promise.all(Array.from(selected).map(readTextFile))
        : [await invoke<DraftAttachment | null>("pick_text_attachment")].filter(
            (x): x is DraftAttachment => x !== null,
          );
      if (currentScope.current !== startedScope || serial.current !== own)
        return;
      const next = [...files, ...chosen];
      validateAttachments(next);
      onChange(next);
    } catch (e) {
      if (currentScope.current === startedScope && serial.current === own)
        onError(String(e));
    } finally {
      if (serial.current === own) {
        setPicking(false);
        onPicking(false);
      }
      if (input.current) input.current.value = "";
    }
  }
  return (
    <div className={`attachment-composer${compact ? " compact-picker" : ""}`}>
      <input
        ref={input}
        hidden
        type="file"
        multiple
        aria-label={
          purpose === "work" ? "Choose Work source files" : "Attach text files"
        }
        accept={Array.from(extensions, (x) => "." + x).join(",")}
        onChange={(e) => {
          if (e.target.files) void pick(e.target.files);
        }}
      />
      <button
        type="button"
        disabled={busy || picking || files.length >= 4}
        onClick={() => (native ? void pick() : input.current?.click())}
      >
        {picking ? "Reading file…" : "Attach text/code file…"}
      </button>
      {compact ? (
        <details>
          <summary>File types and limits</summary>
          <small>
            Up to 4 UTF-8 files · 64 KiB each · 128 KiB total. Sent with your
            {purpose === "work"
              ? "new Work task to the PC only. The model can read and edit these source files."
              : "message to the PC only. Turn off Research to attach files."}
            Use the document/image picker for DOCX, PDF, images, XLSX and PPTX.
          </small>
        </details>
      ) : (
        <small>
          Up to 4 UTF-8 files · 64 KiB each · 128 KiB total. Sent with your
          {purpose === "work"
            ? "new Work task to the PC only. The model can read and edit these source files."
            : "message to the PC only. Turn off Research to attach files."}
          Use the document/image picker for DOCX, PDF, images, XLSX and PPTX.
        </small>
      )}
      {showSelection && (
        <AttachmentSelection
          files={files}
          onChange={onChange}
          busy={busy || picking}
        />
      )}
    </div>
  );
}

export function AttachmentSelection({
  files,
  onChange,
  busy,
}: {
  files: DraftAttachment[];
  onChange: (files: DraftAttachment[]) => void;
  busy: boolean;
}) {
  if (!files.length) return null;
  return (
    <div className="attachment-selection">
      {files.map((file, index) => (
        <div key={index} className="work-actions">
          <span>
            {file.name} · {new TextEncoder().encode(file.text).length} bytes
          </span>
          {file.document && (
            <details>
              <summary>Review document text and limitations</summary>
              <p>{file.document.notice}</p>
              <pre>{file.text}</pre>
            </details>
          )}
          <button
            type="button"
            disabled={busy}
            onClick={() => onChange(files.filter((_, i) => i !== index))}
          >
            Remove selected {file.name}
          </button>
        </div>
      ))}
      {files.length > 0 && (
        <small>
          Files are saved when the request is accepted. Unsent selections are
          lost if the app closes. Large files may exceed your model’s context;
          they are never silently shortened.
        </small>
      )}
    </div>
  );
}

interface Excerpt extends AttachmentRecord {
  text: string;
  offset: number;
  next_offset: number | null;
  total_characters: number;
}
export function AttachmentHistory({
  client,
  chatId,
  files,
  onRemoved,
}: {
  client: Client;
  chatId: string;
  files: AttachmentRecord[];
  onRemoved?: (id: string) => void;
}) {
  const [selected, setSelected] = useState<string | null>(null),
    [offset, setOffset] = useState(0),
    [revision, setRevision] = useState(0);
  const [excerpt, setExcerpt] = useState<Excerpt | null>(null),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false),
    [deleting, setDeleting] = useState(false);
  const item = files.find((f) => f.id === selected);
  const endpoint = `/v1/conversations/${chatId}/attachments/${selected}`;
  useEffect(() => {
    setExcerpt(null);
    setError("");
    setDeleting(false);
    if (!item || item.removed) return;
    const control = new AbortController();
    client
      .request<Excerpt>(
        `${endpoint}?offset=${offset}`,
        "GET",
        undefined,
        control.signal,
      )
      .then((value) => {
        if (!control.signal.aborted) setExcerpt(value);
      })
      .catch((e) => {
        if (!control.signal.aborted) setError(String(e));
      });
    return () => control.abort();
  }, [client, chatId, selected, item?.removed, offset, revision]);
  async function remove() {
    setBusy(true);
    setError("");
    try {
      await client.request(endpoint, "DELETE");
      setNotice(
        "Stored file body removed. Message text, replies and older backups remain.",
      );
      setRevision((n) => n + 1);
      if (selected) onRemoved?.(selected);
    } catch (e) {
      setError(
        `${String(e)} Refresh history before retrying; no action is replayed automatically.`,
      );
    } finally {
      setBusy(false);
      setDeleting(false);
    }
  }
  return (
    <div className="attachment-history">
      {files.map((file) => (
        <button
          key={file.id}
          onClick={() => {
            setSelected(file.id);
            setOffset(0);
            setNotice("");
          }}
          disabled={busy}
        >
          Attached file: {file.name}
          {file.removed ? " (removed)" : ""}
        </button>
      ))}
      {item && (
        <section aria-label="Attached file viewer">
          <h3>{item.name}</h3>
          <p>
            {item.bytes} original bytes · SHA-256 {item.sha256}
          </p>
          <p>
            Saved: {item.created_at}. This file stays in this conversation and
            is used only for local Chat context. Public Research does not use
            it.
          </p>
          {item.document && <p>{item.document.notice}</p>}
          {error && <p role="alert">{error}</p>}
          {notice && <p role="status">{notice}</p>}
          {item.removed ? (
            <p>The stored file body was removed.</p>
          ) : (
            <>
              {excerpt ? (
                <>
                  <pre className="attachment-text">
                    {excerpt.text || "(Empty file)"}
                  </pre>
                  <p>
                    Characters {excerpt.offset}–
                    {excerpt.offset + Array.from(excerpt.text).length} of{" "}
                    {excerpt.total_characters}
                  </p>
                </>
              ) : (
                <p>Loading saved text…</p>
              )}
              <div className="work-actions">
                <button disabled={!offset || busy} onClick={() => setOffset(0)}>
                  First excerpt
                </button>
                <button
                  disabled={excerpt?.next_offset == null || busy}
                  onClick={() => setOffset(excerpt!.next_offset!)}
                >
                  Next excerpt
                </button>
                <button
                  disabled={busy}
                  onClick={() => setRevision((n) => n + 1)}
                >
                  Refresh file
                </button>
                <button
                  disabled={busy}
                  onClick={() => {
                    setBusy(true);
                    void client
                      .downloadAttachment(chatId, item.id, item.name)
                      .then((saved) => {
                        if (saved) setNotice("File saved.");
                      })
                      .catch((e) => setError(String(e)))
                      .finally(() => setBusy(false));
                  }}
                >
                  Save attached file…
                </button>
                <button disabled={busy} onClick={() => setDeleting(true)}>
                  Remove stored file…
                </button>
              </div>
            </>
          )}
          <button disabled={busy} onClick={() => setSelected(null)}>
            Close file
          </button>
          {deleting && (
            <div role="dialog" aria-label="Remove stored attachment">
              <p>
                Remove {item.name} from future local Chat context? Message text,
                replies and older backups remain. Accepted replies must finish
                or be cancelled first.
              </p>
              <button disabled={busy} onClick={() => void remove()}>
                Confirm file removal
              </button>
              <button disabled={busy} onClick={() => setDeleting(false)}>
                Keep file
              </button>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
