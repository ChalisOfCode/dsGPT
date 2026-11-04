import { describe, it, expect } from "vitest";
import { validateAttachments, readTextFile } from "./Attachments";

describe("private text attachments", () => {
  it("preserves BOM/newlines and rejects invalid UTF-8 before submission", async () => {
    const text = "\ufeffCOBALT\r\né";
    expect(await readTextFile(new File([text], "notes.txt"))).toEqual({
      name: "notes.txt",
      text,
    });
    await expect(
      readTextFile(new File([new Uint8Array([0xff, 0xfe])], "notes.txt")),
    ).rejects.toThrow();
    await expect(
      readTextFile(new File(["x".repeat(65537)], "notes.txt")),
    ).rejects.toThrow("64 KiB");
  });
  it("bounds UTF-8 aggregate size and rejects paths, devices, binary and unsupported files", () => {
    for (const name of [
      "../a.txt",
      "C:a.py",
      "NUL.txt",
      "x.exe",
      "x.pdf",
      ".txt",
      "a.txt ",
    ])
      expect(() => validateAttachments([{ name, text: "a" }])).toThrow();
    expect(() =>
      validateAttachments([{ name: "a.txt", text: "a\0b" }]),
    ).toThrow();
    expect(() =>
      validateAttachments([{ name: "a.txt", text: "é".repeat(32769) }]),
    ).toThrow();
    expect(() =>
      validateAttachments(
        Array.from({ length: 3 }, (_, i) => ({
          name: `${i}.txt`,
          text: "a".repeat(65536),
        })),
      ),
    ).toThrow();
    expect(() =>
      validateAttachments([
        { name: "safe.ts", text: "console.log('reference only')" },
      ]),
    ).not.toThrow();
  });
  it("bounds DOCX originals separately from extracted text", () => {
    validateAttachments([
      { name: "sample.docx", text: "Extracted", original_base64: "eA==" },
    ]);
    expect(() =>
      validateAttachments([
        { name: "wrong.txt", text: "Text", original_base64: "eA==" },
      ]),
    ).toThrow();
    expect(() =>
      validateAttachments([
        {
          name: "large.docx",
          text: "Text",
          original_base64: "A".repeat(699056),
        },
      ]),
    ).toThrow();
    expect(() =>
      validateAttachments([
        { name: "long.docx", text: "x".repeat(65537), original_base64: "eA==" },
      ]),
    ).toThrow();
  });
});
