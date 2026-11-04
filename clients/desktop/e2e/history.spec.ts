import { test, expect } from "@playwright/test";

test("imported history stays readable, searchable and continuable in existing clients", async ({
  page,
  request,
}) => {
  const base = "http://127.0.0.1:8766";
  const { token } = await (await request.get(base + "/test-credential")).json();
  const headers = { Authorization: `Bearer ${token}` };
  const result = await (
    await request.post(base + "/test-history-import")
  ).json();
  const id = result.items[0].conversation_id;
  async function connect() {
    await page.getByLabel("Backend address").fill(base);
    await page.getByLabel("Owner credential").fill(token);
    await page.getByRole("button", { name: "Connect to dsGPT" }).click();
  }
  await page.goto("/");
  await connect();
  await page
    .getByRole("button", { name: "Imported garden notes", exact: true })
    .click();
  await expect(page.locator("article.user")).toContainText(
    "SAPPHIRE garden <svg",
  );
  await expect(page.locator("article.user svg")).toHaveCount(0);
  await expect(page.locator("article.assistant")).toContainText(
    "Saved original reply.",
  );
  const provenance = await (
    await request.get(`${base}/v1/conversations/${id}/import`, { headers })
  ).json();
  expect(provenance.source_created_at).toBe("2023-11-14T22:13:20+00:00");
  const found = await (
    await request.get(base + "/v1/history/search?q=SAPPHIRE", { headers })
  ).json();
  expect(
    found.some((x: { conversation_id: string }) => x.conversation_id === id),
  ).toBe(true);
  await page
    .getByLabel("Message", { exact: true })
    .fill("Continue the imported garden notes");
  await page.getByRole("button", { name: "Send ↑" }).click();
  // The fixture deliberately streams for 2.4 seconds, and reconnect polling can
  // add another cycle. Allow that work to finish on a loaded CI runner while
  // still requiring the complete response and the persistence checks below.
  await expect(page.locator("article.assistant").last()).toContainText(
    "Word29",
    { timeout: 12_000 },
  );
  await page.reload();
  await connect();
  await page
    .getByRole("button", { name: "Imported garden notes", exact: true })
    .click();
  await expect(page.locator("article")).toHaveCount(4);
  await expect(page.locator("article.user").first()).toContainText("SAPPHIRE");
  const removed = await request.delete(`${base}/v1/history/imports/${id}`, {
    headers,
  });
  expect(removed.ok()).toBe(true);
  const retry = await (
    await request.post(base + "/test-history-import")
  ).json();
  expect(retry.items[0].removed).toBe(true);
  const messages = await (
    await request.get(`${base}/v1/conversations/${id}/messages`, { headers })
  ).json();
  expect(messages[0].content).toBe("");
  expect(messages[2].content).toBe("Continue the imported garden notes");
});
