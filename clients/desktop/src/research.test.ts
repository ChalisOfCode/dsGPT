import { describe, expect, it } from "vitest";
import { citationParts, publicSourceURL, researchOptions } from "./research";

describe("research boundaries", () => {
  it("refuses local, executable and credential-bearing external links", () => {
    for (const url of [
      "javascript:alert(1)",
      "file:///tmp/a",
      "http://example.org",
      "https://user:secret@example.org",
      "https://localhost",
      "https://127.0.0.1",
      "https://[::1]",
      "https://2130706433",
      "https://device.internal/",
      "https://example.org:123",
      "https://example.org/\ncommand",
      "https://example.org\\path",
    ])
      expect(() => publicSourceURL(url)).toThrow();
    expect(publicSourceURL("https://example.org/path?q=one%20two")).toBe(
      "https://example.org/path?q=one%20two",
    );
  });
  it("requires sources or configured search and bounds unique URLs", () => {
    expect(() => researchOptions(false, "")).toThrow();
    expect(researchOptions(true, "")).toEqual({ search: true, urls: [] });
    expect(
      researchOptions(false, "https://example.org/a\nhttps://example.org/a")
        .urls,
    ).toHaveLength(1);
    expect(() =>
      researchOptions(
        false,
        Array.from({ length: 7 }, (_, i) => `https://example.org/${i}`).join(
          "\n",
        ),
      ),
    ).toThrow();
  });
  it("only makes citation controls from retrieved IDs and matching final URLs", () => {
    const source = {
      id: "one",
      url: "https://example.org/old",
      final_url: "https://example.org/new",
      status: "retrieved",
    };
    const parts = citationParts(
      "Real [S1](<https://example.org/new>) fake [S2](<https://evil.org>) wrong [S1](<https://example.org/old>)",
      [source],
    );
    expect(parts.filter((p) => p.source)).toEqual([{ text: "S1", source }]);
    expect(
      citationParts("[S1](<https://example.org/new>)", [
        { ...source, status: "unavailable" },
      ]).every((p) => !p.source),
    ).toBe(true);
  });
});
