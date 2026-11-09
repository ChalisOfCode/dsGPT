import { expect, test, vi, afterEach } from "vitest";
import { accountFrame, frameLimit } from "./account-frame";
import { Client } from "./transport";
vi.mock("@tauri-apps/api/core", () => ({
  isTauri: () => false,
  invoke: vi.fn(),
}));
afterEach(() => vi.unstubAllGlobals());
const id = "00000000-0000-4000-8000-000000000001";
const valid = () =>
  new Uint8Array([
    137,
    80,
    78,
    71,
    13,
    10,
    26,
    10,
    0,
    0,
    0,
    13,
    73,
    72,
    68,
    82,
    0,
    0,
    4,
    0,
    0,
    0,
    3,
    0,
    ...new Array(9).fill(0),
  ]);
test("frame rejects invalid signature, oversized dimensions and byte count before display", () => {
  expect(accountFrame(valid())).toMatch(/^data:image\/png;base64,/);
  for (const position of [0, 8, 12, 16, 21]) {
    const data = valid();
    data[position] ^= 255;
    expect(() => accountFrame(data)).toThrow("Invalid account browser frame");
  }
  expect(() => accountFrame(new Uint8Array(frameLimit + 1))).toThrow();
});
test("private frame fetch authenticates and rejects type, cache policy, overflow and bad identity", async () => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  const client = new Client("http://127.0.0.1:18765", "fixture");
  const headers = {
    "content-type": "image/png",
    "cache-control": "no-store",
    "x-dsgpt-observation": id,
  };
  fetch.mockResolvedValueOnce(new Response(valid(), { headers }));
  expect(await client.accountFrame(id, id)).toEqual({
    image: expect.stringMatching(/^data:image\/png;base64,/),
    observation: id,
  });
  expect(fetch.mock.calls[0][1]).toMatchObject({
    method: "POST",
    redirect: "error",
    cache: "no-store",
    headers: { Authorization: "Bearer fixture" },
  });
  for (const change of [
    { "content-type": "text/html" },
    { "cache-control": "public" },
  ]) {
    fetch.mockResolvedValueOnce(
      new Response(valid(), { headers: { ...headers, ...change } }),
    );
    await expect(client.accountFrame(id, id)).rejects.toThrow("unavailable");
  }
  fetch.mockResolvedValueOnce(
    new Response(new Uint8Array(frameLimit + 1), { headers }),
  );
  await expect(client.accountFrame(id, id)).rejects.toThrow("exceeds limit");
  await expect(client.accountFrame("../other", id)).rejects.toThrow("identity");
  expect(fetch).toHaveBeenCalledTimes(4);
});
