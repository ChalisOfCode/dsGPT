import { describe, it, expect } from "vitest";
import { backendURL, EventParser, nearBottom } from "./protocol";
describe("replay transport", () => {
  it("handles arbitrary boundaries, CRLF, comments, and multiline JSON", () => {
    const p = new EventParser();
    expect(p.push(": heartbeat\r\n\r\nid: 7\r\nevent: delta\r")).toEqual([]);
    expect(p.push('\ndata: {"text":\r\ndata: "hello"}\r\n\r\n')).toEqual([
      { id: 7, kind: "delta", data: { text: "hello" } },
    ]);
  });
  it("retains multiple event boundaries", () => {
    const p = new EventParser();
    expect(
      p
        .push(
          "id: 1\nevent: accepted\ndata: {}\n\nid: 2\nevent: completed\ndata: {}\n\n",
        )
        .map((e) => e.id),
    ).toEqual([1, 2]);
  });
  it("rejects public HTTP, arbitrary HTTPS and credential-bearing origins", () => {
    for (const url of [
      "http://example.com",
      "https://example.com",
      "https://bad.ts.net.evil.com",
      "http://user:pass@localhost:123",
      "http://localhost:123/path",
    ])
      expect(() => backendURL(url)).toThrow();
    expect(backendURL("https://pc.tail123.ts.net/")).toBe(
      "https://pc.tail123.ts.net",
    );
    expect(backendURL("http://127.0.0.1:8765")).toBe("http://127.0.0.1:8765");
  });
  it("only follows near bottom", () => {
    expect(
      nearBottom({ scrollHeight: 1000, scrollTop: 0, clientHeight: 500 }),
    ).toBe(false);
    expect(
      nearBottom({ scrollHeight: 1000, scrollTop: 490, clientHeight: 500 }),
    ).toBe(true);
  });
});
