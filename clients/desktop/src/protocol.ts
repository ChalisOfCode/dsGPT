export interface StreamEvent {
  id: number;
  kind: string;
  data: Record<string, unknown>;
}
/** Incremental SSE parser, including split UTF-8, CRLF and multiline data. */
export class EventParser {
  private buffer = "";
  push(chunk: string): StreamEvent[] {
    this.buffer += chunk;
    const events: StreamEvent[] = [];
    for (;;) {
      const match = /\r?\n\r?\n/.exec(this.buffer);
      if (!match) break;
      const block = this.buffer.slice(0, match.index);
      this.buffer = this.buffer.slice(match.index + match[0].length);
      let id = 0,
        kind = "message";
      const data: string[] = [];
      for (const line of block.split(/\r?\n/)) {
        if (line.startsWith("id:")) id = Number(line.slice(3).trim());
        if (line.startsWith("event:")) kind = line.slice(6).trim();
        if (line.startsWith("data:"))
          data.push(line.slice(5).replace(/^ /, ""));
      }
      if (data.length && Number.isSafeInteger(id) && id > 0)
        events.push({ id, kind, data: JSON.parse(data.join("\n")) });
    }
    if (this.buffer.length > 2_000_000)
      throw new Error("Event exceeds safety limit");
    return events;
  }
}
export function backendURL(raw: string): string {
  const url = new URL(raw);
  if (
    url.username ||
    url.password ||
    url.search ||
    url.hash ||
    !["", "/"].includes(url.pathname)
  )
    throw new Error("Use a server origin without a path or credentials.");
  const local = ["127.0.0.1", "[::1]", "localhost"].includes(url.hostname);
  if (
    !(local && url.protocol === "http:") &&
    !(url.protocol === "https:" && url.hostname.endsWith(".ts.net"))
  )
    throw new Error("Use local HTTP or your HTTPS Tailscale hostname.");
  return url.origin;
}
export function nearBottom(el: {
  scrollHeight: number;
  scrollTop: number;
  clientHeight: number;
}) {
  return el.scrollHeight - el.scrollTop - el.clientHeight < 72;
}
