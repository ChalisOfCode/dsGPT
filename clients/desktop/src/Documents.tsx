import { useRef, useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { Client, native } from "./transport";
import { DraftAttachment, validateAttachments } from "./Attachments";
export function DocumentPicker({
  client,
  files,
  onChange,
  busy,
  scope,
  onPicking,
  onError,
  work = false,
  compact = false,
}: {
  client: Client;
  work?: boolean;
  compact?: boolean;
  files: DraftAttachment[];
  onChange: (f: DraftAttachment[]) => void;
  busy: boolean;
  scope: string;
  onPicking: (v: boolean) => void;
  onError: (s: string) => void;
}) {
  const input = useRef<HTMLInputElement>(null),
    epoch = useRef(0);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    epoch.current++;
    setLoading(false);
    onPicking(false);
    return () => {
      epoch.current++;
    };
  }, [scope]);
  async function pick(file?: File) {
    if (busy || loading) return;
    const own = ++epoch.current;
    setLoading(true);
    onPicking(true);
    try {
      let name: string, bytes: Uint8Array;
      if (file) {
        if (file.size > 524288)
          throw Error("Original files are limited to 512 KiB.");
        name = file.name;
        bytes = new Uint8Array(await file.arrayBuffer());
      } else {
        const selected = await invoke<{ name: string; bytes: number[] } | null>(
          "pick_document_attachment",
          { work },
        );
        if (!selected) return;
        name = selected.name;
        bytes = new Uint8Array(selected.bytes);
      }
      if (bytes.length > 524288)
        throw Error("Original files are limited to 512 KiB.");
      let binary = "";
      for (let i = 0; i < bytes.length; i += 8192)
        binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
      if (epoch.current !== own) return;
      if (
        !(
          work
            ? /\.(docx|pdf|png|jpe?g|webp|xlsx|pptx|zip)$/i
            : /\.(docx|pdf|png|jpe?g|webp|xlsx|pptx)$/i
        ).test(name)
      )
        throw Error("Choose DOCX, PDF, PNG, JPEG, WebP, XLSX or PPTX.");
      const original_base64 = btoa(binary);
      const preview = await client.request<{
        text: string;
        document: { notice: string };
      }>(work ? "/v1/work/inputs/preview" : "/v1/documents/preview", "POST", {
        name,
        original_base64,
      });
      if (epoch.current !== own) return;
      const next = [
        ...files,
        {
          name,
          text: preview.text,
          original_base64,
          document: preview.document,
        },
      ];
      validateAttachments(next);
      onChange(next);
    } catch (e) {
      if (epoch.current === own) onError(String(e));
    } finally {
      if (epoch.current === own) {
        setLoading(false);
        onPicking(false);
      }
      if (input.current) input.current.value = "";
    }
  }
  return (
    <div className={compact ? "compact-picker" : undefined}>
      <input
        ref={input}
        hidden
        type="file"
        accept={
          ".docx,.pdf,.png,.jpg,.jpeg,.webp,.xlsx,.pptx" + (work ? ",.zip" : "")
        }
        aria-label={
          work ? "Choose Work document or source ZIP" : "Choose DOCX document"
        }
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) void pick(f);
        }}
      />
      <button
        type="button"
        disabled={busy || loading || files.length >= 4}
        onClick={() => (native ? void pick() : input.current?.click())}
      >
        {loading
          ? "Reading document…"
          : work
            ? "Attach Work document / source ZIP…"
            : "Attach document/image…"}
      </button>
      {compact ? (
        <details>
          <summary>File types and limits</summary>
          <small>
            Documents/images: 512 KiB each, 768 KiB total. Selected originals go
            to your PC for an unsaved text preview. Turn off Research. PDF/image
            OCR and XLSX/PPTX use isolated document tools. Images require a
            local Ollama vision model.
          </small>
        </details>
      ) : (
        <small>
          Documents/images: 512 KiB each, 768 KiB total. Selected originals go
          to your PC for an unsaved text preview. Turn off Research. PDF/image
          OCR and XLSX/PPTX use isolated document tools. Images require a local
          Ollama vision model.
        </small>
      )}
    </div>
  );
}
