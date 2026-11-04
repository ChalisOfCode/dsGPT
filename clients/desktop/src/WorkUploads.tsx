import { useRef, useState, useEffect } from "react";
import { Client } from "./transport";
import type { DraftAttachment } from "./Attachments";

export function WorkUploads({
  client,
  files,
  onChange,
  busy,
  onPicking,
  onError,
}: {
  client: Client;
  files: DraftAttachment[];
  onChange: (files: DraftAttachment[]) => void;
  busy: boolean;
  onPicking: (value: boolean) => void;
  onError: (message: string) => void;
}) {
  const [progress, setProgress] = useState("");
  const epoch = useRef(0);
  useEffect(
    () => () => {
      epoch.current++;
    },
    [client],
  );
  async function upload(file: File) {
    if (busy || progress || files.length >= 4) return;
    const own = epoch.current;
    let id = "";
    try {
      if (!file.size || file.size > 256 * 1024 ** 2)
        throw Error("Choose a file up to 256 MiB.");
      if (
        files.reduce((n, f) => n + (f.upload_bytes || 0), file.size) >
        512 * 1024 ** 2
      )
        throw Error("Work inputs exceed 512 MiB total.");
      if (files.some((f) => f.name.toLowerCase() === file.name.toLowerCase()))
        throw Error("Choose distinct filenames.");
      onPicking(true);
      setProgress("Starting upload…");
      const key = `dsgpt-upload:${client.origin}:${file.name}:${file.size}:${file.lastModified}`;
      let saved = localStorage.getItem(key);
      let state: { id: string; received: number; size: number };
      try {
        if (!saved) throw Error();
        state = await client.request(`/v1/work/uploads/${saved}`);
      } catch {
        state = await client.request("/v1/work/uploads", "POST", {
          name: file.name,
          size: file.size,
        });
        localStorage.setItem(key, state.id);
      }
      id = state.id;
      // Recheck every saved chunk against the reselected file: identity includes bytes, not just name.
      for (let offset = 0; offset < file.size; offset += 262144) {
        if (epoch.current !== own)
          throw Error("Upload interrupted; reselect the file to resume.");
        const bytes = new Uint8Array(
          await file.slice(offset, offset + 262144).arrayBuffer(),
        );
        let binary = "";
        for (let i = 0; i < bytes.length; i += 8192)
          binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
        let last: unknown;
        for (let attempt = 0; attempt < 3; attempt++) {
          try {
            await client.request(`/v1/work/uploads/${id}`, "PUT", {
              offset,
              data: btoa(binary),
            });
            last = null;
            break;
          } catch (e) {
            last = e;
          }
        }
        if (last) throw last;
        setProgress(
          `Uploading ${file.name}: ${Math.round((Math.min(file.size, offset + bytes.length) / file.size) * 100)}%`,
        );
      }
      await client.request(`/v1/work/uploads/${id}/finish`, "POST", {});
      if (epoch.current === own)
        onChange([
          ...files,
          { name: file.name, text: "", upload_id: id, upload_bytes: file.size },
        ]);
      localStorage.removeItem(key);
    } catch (e) {
      if (epoch.current === own)
        onError(`${String(e)} Reselect the same file to resume.`);
    } finally {
      if (epoch.current === own) {
        setProgress("");
        onPicking(false);
      }
    }
  }
  return (
    <div>
      <label>
        Add APK, EXE, video, archive or document
        <input
          aria-label="Upload Work file"
          type="file"
          disabled={busy || !!progress || files.length >= 4}
          onChange={(e) => {
            const f = e.target.files?.[0];
            e.target.value = "";
            if (f) void upload(f);
          }}
        />
      </label>
      {progress && <p role="status">{progress}</p>}
      <small>
        Up to four files, 256 MiB each and 512 MiB total. Originals stay on your
        PC; tools inspect sections as needed.
      </small>
      {files.map(
        (f, i) =>
          f.upload_id && (
            <p key={f.name}>
              {f.name}{" "}
              <button
                disabled={busy || !!progress}
                onClick={() => {
                  onChange(files.filter((_, j) => j !== i));
                  if (f.upload_id)
                    void client
                      .request(`/v1/work/uploads/${f.upload_id}`, "DELETE")
                      .catch(() => {});
                }}
              >
                Remove
              </button>
            </p>
          ),
      )}
    </div>
  );
}
