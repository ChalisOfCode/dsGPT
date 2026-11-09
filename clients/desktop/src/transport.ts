import { invoke, isTauri } from "@tauri-apps/api/core";
import { backendURL, EventParser, type StreamEvent } from "./protocol";
import { publicSourceURL } from "./research";
import { accountFrame, accountId, frameLimit } from "./account-frame";
// Browser development mode keeps tokens only in memory. Production uses native storage.
export class Client {
  constructor(
    public origin: string,
    private token: string,
  ) {
    this.origin = backendURL(origin);
  }
  async accountFrame(sessionId: string, handoffId: string): Promise<string> {
    if (![sessionId, handoffId].every((id) => accountId.test(id)))
      throw new Error("Invalid account browser identity");
    if (isTauri()) {
      const data = await invoke<ArrayBuffer>("account_browser_frame", {
        sessionId,
        handoffId,
      });
      return accountFrame(new Uint8Array(data));
    }
    const response = await fetch(
      `${this.origin}/v1/account-sessions/${sessionId}/browser/${handoffId}/frame`,
      {
        method: "POST",
        signal: AbortSignal.timeout(30000),
        headers: { Authorization: `Bearer ${this.token}` },
        cache: "no-store",
        redirect: "error",
      },
    );
    if (
      response.status !== 200 ||
      response.headers.get("content-type") !== "image/png" ||
      response.headers.get("cache-control") !== "no-store" ||
      !response.body
    )
      throw new Error("Account browser frame unavailable");
    const reader = response.body.getReader();
    const chunks: Uint8Array[] = [];
    let size = 0;
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        size += value.length;
        if (size > frameLimit)
          throw new Error("Account browser frame exceeds limit");
        chunks.push(value);
      }
    } finally {
      await reader.cancel();
      reader.releaseLock();
    }
    const data = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) {
      data.set(chunk, offset);
      offset += chunk.length;
    }
    return accountFrame(data);
  }
  async request<T>(
    path: string,
    method = "GET",
    body?: unknown,
    signal?: AbortSignal,
  ): Promise<T> {
    if (isTauri())
      return invoke<T>("api_request", { path, method, body: body ?? null });
    const response = await fetch(this.origin + path, {
      method,
      headers: {
        Authorization: `Bearer ${this.token}`,
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
      redirect: "error",
      cache: "no-store",
    });
    if (!response.ok) {
      let detail = "";
      if (response.status !== 401) {
        try {
          const value = (await response.json()).detail;
          detail =
            typeof value === "string"
              ? value
              : typeof value?.code === "string"
                ? value.code
                : "";
        } catch {
          /* HTTP status remains available when the response is not JSON. */
        }
      }
      throw new Error(
        response.status === 401
          ? "Connection expired. Reconnect in Settings."
          : `Request failed (${response.status}). ${detail.slice(0, 300) || "Refresh the current state before retrying."}`,
      );
    }
    if (response.status === 204) return null as T;
    return response.json();
  }
  async downloadDiagnostics(id: string, sha256: string) {
    if (native) {
      await invoke("download_diagnostics", { id, sha256 });
      return;
    }
    const response = await fetch(
      `${this.origin}/v1/diagnostics/exports/${id}?sha256=${sha256}`,
      {
        headers: { Authorization: `Bearer ${this.token}` },
        redirect: "error",
        cache: "no-store",
      },
    );
    if (!response.ok)
      throw new Error("Diagnostic preview expired. Preview again.");
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = "dsGPT-Diagnostics.zip";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  async downloadWork(id: string): Promise<boolean> {
    if (
      !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
        id,
      )
    )
      throw new Error("Invalid task identity");
    if (native) return invoke<boolean>("download_work", { id });
    const response = await fetch(`${this.origin}/v1/work/tasks/${id}/export`, {
      headers: { Authorization: `Bearer ${this.token}` },
      redirect: "error",
      cache: "no-store",
    });
    if (!response.ok || !response.body)
      throw new Error(
        "Source download failed. Refresh the task and try again.",
      );
    const reader = response.body.getReader(),
      chunks: Uint8Array<ArrayBuffer>[] = [];
    let size = 0;
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        size += value.length;
        if (size > 32 * 1024 * 1024)
          throw new Error("Source archive exceeds the download limit");
        chunks.push(new Uint8Array(value));
      }
    } finally {
      await reader.cancel();
      reader.releaseLock();
    }
    const url = URL.createObjectURL(
      new Blob(chunks, { type: "application/zip" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "dsGPT-project.zip";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    return true;
  }
  async downloadAttachment(
    chatId: string,
    id: string,
    name: string,
  ): Promise<boolean> {
    if (
      ![chatId, id].every((value) =>
        /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
          value,
        ),
      )
    )
      throw new Error("Invalid attachment identity");
    if (native)
      return invoke<boolean>("download_attachment", { chatId, id, name });
    const response = await fetch(
      `${this.origin}/v1/conversations/${chatId}/attachments/${id}/download`,
      {
        headers: { Authorization: `Bearer ${this.token}` },
        redirect: "error",
        cache: "no-store",
      },
    );
    if (!response.ok || !response.body)
      throw new Error("Attachment unavailable. Refresh history.");
    const reader = response.body.getReader(),
      chunks: Uint8Array<ArrayBuffer>[] = [];
    let size = 0;
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        size += value.length;
        if (size > 524288) throw new Error("Attachment exceeds 512 KiB.");
        chunks.push(new Uint8Array(value));
      }
    } finally {
      await reader.cancel();
      reader.releaseLock();
    }
    const url = URL.createObjectURL(
        new Blob(chunks, { type: "application/octet-stream" }),
      ),
      link = document.createElement("a");
    link.href = url;
    link.download = name;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    return true;
  }
  async downloadArtifact(
    taskId: string,
    id: string,
    sha256: string,
    bytes: number,
    path: string,
  ): Promise<boolean> {
    const uuid =
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
    if (
      ![taskId, id].every((v) => uuid.test(v)) ||
      !/^[0-9a-f]{64}$/.test(sha256) ||
      !Number.isSafeInteger(bytes) ||
      bytes < 0 ||
      bytes > 256 * 1024 * 1024
    )
      throw new Error("Invalid artifact metadata");
    const extension = path.toLowerCase().endsWith(".apk")
      ? "apk"
      : path.toLowerCase().endsWith(".exe")
        ? "exe"
        : "bin";
    if (native)
      return invoke<boolean>("download_artifact", {
        taskId,
        id,
        sha256,
        bytes,
        extension,
      });
    const response = await fetch(
      `${this.origin}/v1/work/tasks/${taskId}/artifacts/${id}`,
      {
        headers: { Authorization: `Bearer ${this.token}` },
        redirect: "error",
        cache: "no-store",
      },
    );
    if (!response.ok || !response.body)
      throw new Error("Artifact download failed. Refresh the task.");
    const reader = response.body.getReader(),
      chunks: Uint8Array<ArrayBuffer>[] = [];
    let size = 0;
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        size += value.length;
        if (size > bytes) throw new Error("Artifact size mismatch");
        chunks.push(new Uint8Array(value));
      }
    } finally {
      await reader.cancel();
      reader.releaseLock();
    }
    const blob = new Blob(chunks, { type: "application/octet-stream" });
    const digest = Array.from(
      new Uint8Array(
        await crypto.subtle.digest("SHA-256", await blob.arrayBuffer()),
      ),
      (b) => b.toString(16).padStart(2, "0"),
    ).join("");
    if (size !== bytes || digest !== sha256)
      throw new Error("Artifact integrity check failed");
    const url = URL.createObjectURL(blob),
      link = document.createElement("a");
    link.href = url;
    link.download = `dsGPT-artifact.${extension}`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    return true;
  }
  async downloadMemory(taskId: string | null): Promise<boolean> {
    if (
      taskId &&
      !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
        taskId,
      )
    )
      throw new Error("Invalid project identity");
    if (native) return invoke<boolean>("download_memory", { taskId });
    const path = "/v1/memories/export" + (taskId ? `?task_id=${taskId}` : "");
    const response = await fetch(this.origin + path, {
      headers: { Authorization: `Bearer ${this.token}` },
      redirect: "error",
      cache: "no-store",
    });
    if (!response.ok || !response.body)
      throw new Error("Memory export failed. Refresh and try again.");
    const reader = response.body.getReader(),
      chunks: Uint8Array<ArrayBuffer>[] = [];
    let size = 0;
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        size += value.length;
        if (size > 32 * 1024 * 1024)
          throw new Error("Memory export exceeds the 32 MiB download limit");
        chunks.push(new Uint8Array(value));
      }
    } finally {
      await reader.cancel();
      reader.releaseLock();
    }
    const url = URL.createObjectURL(
      new Blob(chunks, { type: "application/json" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "dsGPT-memory.json";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    return true;
  }
  async events(
    run: string,
    cursor: number,
    signal: AbortSignal,
    onEvent: (event: StreamEvent) => void,
  ) {
    // Native client polls atomic snapshots via request; browser integration exercises SSE.
    const response = await fetch(
      `${this.origin}/v1/runs/${run}/events?after=${cursor}`,
      {
        headers: { Authorization: `Bearer ${this.token}` },
        signal,
        redirect: "error",
        cache: "no-store",
      },
    );
    if (!response.ok || !response.body)
      throw new Error(`Stream unavailable (${response.status})`);
    const reader = response.body.getReader(),
      decoder = new TextDecoder(),
      parser = new EventParser();
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        for (const e of parser.push(decoder.decode(value, { stream: true })))
          onEvent(e);
      }
    } finally {
      await reader.cancel();
      reader.releaseLock();
    }
  }
}
export async function connect(origin: string, token: string): Promise<Client> {
  origin = backendURL(origin);
  if (isTauri()) await invoke("connect", { origin, token });
  const client = new Client(origin, token);
  await client.request("/v1/models");
  return client;
}
export async function restore(): Promise<Client | null> {
  if (!isTauri()) return null;
  const origin = await invoke<string | null>("restore_connection");
  return origin ? new Client(origin, "") : null;
}
export async function disconnect() {
  if (isTauri()) await invoke("disconnect");
}
export const native = isTauri();
export async function openSource(raw: string) {
  const url = publicSourceURL(raw);
  if (native) await invoke("open_public_source", { url });
  else window.open(url, "_blank", "noopener,noreferrer");
}
