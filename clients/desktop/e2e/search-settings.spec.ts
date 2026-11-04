import { test, expect } from "@playwright/test";

test("search settings recover lost updates, preserve edits and require explicit tests", async ({
  page,
  request,
}) => {
  const base = "http://127.0.0.1:8766";
  const { token } = await (await request.get(base + "/test-credential")).json();
  const headers = { Authorization: `Bearer ${token}` };
  const read = async () =>
    (await request.get(base + "/v1/research/settings", { headers })).json();
  const write = async (origin: string | null) =>
    request.put(base + "/v1/research/settings", {
      headers,
      data: { origin, revision: (await read()).revision },
    });
  let probes = 0,
    writes = 0,
    loseNext = false;
  page.on("request", (req) => {
    if (req.url().endsWith("/v1/research/check")) probes++;
  });
  await page.route(base + "/v1/research/settings", async (route) => {
    if (route.request().method() !== "PUT") return route.continue();
    writes++;
    if (loseNext) {
      loseNext = false;
      await route.fetch();
      return route.fulfill({ status: 503, json: {} });
    }
    return route.continue();
  });
  async function open(credential = token) {
    await page.getByLabel("Backend address").fill(base);
    await page.getByLabel("Owner credential").fill(credential);
    await page.getByRole("button", { name: "Connect to dsGPT" }).click();
    await settings();
  }
  async function settings() {
    await page.getByRole("button", { name: "Settings", exact: false }).click();
    await page.getByRole("button", { name: "Web search status →" }).click();
  }
  const panel = page.getByRole("region", { name: "Web search settings" });
  await page.goto("/");
  await open();
  await expect(panel.getByLabel("Current search address")).toContainText(
    "not configured",
  );
  await expect(
    panel.getByRole("button", { name: "Run test search" }),
  ).toBeDisabled();
  await panel.getByText("Advanced search address", {exact:true}).click();
  await panel.getByLabel("Local search address").fill("https://example.org");
  await panel.getByRole("button", { name: "Save search address" }).click();
  await expect(panel.getByRole("alert")).toContainText("422");
  await expect(panel.getByLabel("Local search address")).toHaveValue(
    "https://example.org",
  );
  expect(probes).toBe(0);
  await panel.getByLabel("Local search address").fill("http://127.0.0.1:8888");
  loseNext = true;
  await panel.getByRole("button", { name: "Save search address" }).click();
  await expect(panel.getByRole("alert")).toContainText("503");
  await expect(panel.getByLabel("Current search address")).toContainText(
    "8888",
  );
  expect(writes).toBe(2);
  expect(probes).toBe(0);
  await panel.getByRole("button", { name: "Clear update and reload" }).click();
  await panel.getByRole("button", { name: "Run test search" }).click();
  await expect(panel.getByLabel("Last search test")).toContainText(
    "Test returned results",
  );
  expect(probes).toBe(1);
  // Preserve the old revision with a dirty form, even when polling sees an external change.
  await panel.getByLabel("Local search address").fill("http://127.0.0.1:7777");
  await write("http://127.0.0.1:8889");
  await panel.getByRole("button", { name: "Refresh search status" }).click();
  await expect(panel.getByLabel("Current search address")).toContainText(
    "8889",
  );
  await expect(panel.getByLabel("Local search address")).toHaveValue(
    "http://127.0.0.1:7777",
  );
  await panel.getByRole("button", { name: "Save search address" }).click();
  await expect(panel.getByRole("alert")).toContainText("409");
  expect((await read()).origin).toBe("http://127.0.0.1:8889");
  await panel.getByRole("button", { name: "Clear update and reload" }).click();
  await panel.getByRole("button", { name: "Run test search" }).click();
  await expect(panel.getByLabel("Last search test")).toContainText(
    "Some search engines did not respond",
  );
  expect(probes).toBe(2);
  await page.screenshot({
    path: "../../../runtime/native-stage3k/search-preview.png",
    fullPage: true,
  });
  await page.reload();
  await open();
  await expect(panel.getByLabel("Last search test")).toContainText(
    "Some search engines did not respond",
  );
  expect(probes).toBe(2);
  await page.getByRole("button", { name: "New chat" }).click();
  await page.getByRole("button", { name: "Add files and tools" }).click();
  await page.getByLabel("Research this message").check();
  await expect(page.getByLabel("Search the web")).toBeEnabled();
  await page.getByLabel("Search the web").uncheck();
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(page.getByLabel("Search the web")).not.toBeChecked();
  await settings();
  await panel.getByText("Advanced search address", {exact:true}).click();
  await panel.getByRole("button", { name: "Disable web search…" }).click();
  await panel.getByRole("button", { name: "Keep web search" }).click();
  expect((await read()).configured).toBe(true);
  await panel.getByRole("button", { name: "Disable web search…" }).click();
  await panel.getByRole("button", { name: "Confirm disable" }).click();
  await expect(panel.getByLabel("Current search address")).toContainText(
    "not configured",
  );
  await page.getByRole("button", { name: "New chat" }).click();
  await page.getByRole("button", { name: "Add files and tools" }).click();
  await page.getByLabel("Research this message").check();
  await expect(page.getByLabel("Search the web")).toBeDisabled();
  const { code } = await (
    await request.post(base + "/v1/pairings", {
      headers,
      data: { scopes: ["chat", "models"] },
    })
  ).json();
  const paired = await (
    await request.post(base + "/v1/pairings/redeem", {
      data: { code, name: "Read-only search fixture" },
    })
  ).json();
  await page.reload();
  await open(paired.token);
  await expect(panel).toContainText(
    "The desktop owner manages search configuration",
  );
  await expect(
    panel.getByRole("button", { name: "Save search address" }),
  ).toHaveCount(0);
  await expect(
    panel.getByRole("button", { name: "Run test search" }),
  ).toHaveCount(0);
  expect(probes).toBe(2);
});
