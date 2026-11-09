import { afterEach, expect, test, vi } from "vitest";
import { Client } from "./transport";
vi.mock("@tauri-apps/api/core", () => ({
  isTauri: () => false,
  invoke: vi.fn(),
}));
afterEach(() => vi.unstubAllGlobals());
test("successful empty revocation response does not become a parse error", async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
  vi.stubGlobal("fetch", fetch);
  const c = new Client("http://127.0.0.1:18765", "fixture");
  expect(await c.request("/v1/account-sessions/fixture", "DELETE")).toBeNull();
  expect(fetch).toHaveBeenCalledTimes(1);
});
