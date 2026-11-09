import { expect, test, vi } from "vitest";
import { invoke } from "@tauri-apps/api/core";
import { Client } from "./transport";
vi.mock("@tauri-apps/api/core", () => ({
  isTauri: () => true,
  invoke: vi.fn(),
}));
test("native frame uses only the private bounded binary command and validates returned dimensions", async () => {
  const data = new Uint8Array([
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
  const id = "00000000-0000-4000-8000-000000000001";
  const wire = new Uint8Array(36 + data.length);
  wire.set(new TextEncoder().encode(id));
  wire.set(data, 36);
  vi.mocked(invoke).mockResolvedValueOnce(wire.buffer);
  const client = new Client("http://127.0.0.1:18765", "unused-js-token");
  expect(await client.accountFrame(id, id)).toEqual({
    image: expect.stringMatching(/^data:image\/png;base64,/),
    observation: id,
  });
  expect(invoke).toHaveBeenCalledWith("account_browser_frame", {
    sessionId: id,
    handoffId: id,
  });
  data[20] = 255;
  wire.set(data, 36);
  vi.mocked(invoke).mockResolvedValueOnce(wire.buffer);
  await expect(client.accountFrame(id, id)).rejects.toThrow(
    "Invalid account browser frame",
  );
});
