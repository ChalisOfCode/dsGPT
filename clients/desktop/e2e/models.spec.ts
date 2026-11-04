import { test, expect } from "@playwright/test";

test("model setup recovers lost responses and preserves owned-file guards", async ({
  page,
  request,
}) => {
  test.setTimeout(90000);
  const base = "http://127.0.0.1:8766";
  const { token } = await (await request.get(base + "/test-credential")).json();
  const headers = { Authorization: `Bearer ${token}` };
  let submissions = 0,
    attachments = 0;
  for (const path of ["/v1/downloads", "/v1/models/managed"]) {
    await page.route(base + path, async (route) => {
      if (route.request().method() !== "POST") {
        await route.continue();
        return;
      }
      const response = await route.fetch();
      const first = path.endsWith("managed")
        ? ++attachments === 1
        : ++submissions === 1;
      if (first) await route.fulfill({ status: 503, json: {} });
      else await route.fulfill({ response });
    });
  }
  async function open() {
    await page.getByLabel("Backend address").fill(base);
    await page.getByLabel("Owner credential").fill(token);
    await page.getByRole("button", { name: "Connect to dsGPT" }).click();
    await page.getByRole("button", { name: "Settings", exact: false }).click();
    await page
      .getByRole("button", { name: "Open Models", exact: false })
      .click();
  }
  await page.goto("/");
  await open();
  const panel = page.getByRole("region", { name: "Models workspace" });
  const weights = panel.getByRole("article", {
    name: "UI model fixture",
    exact: true,
  });
  const archive = panel.getByRole("article", {
    name: "UI runtime fixture",
    exact: true,
  });
  await weights.getByRole("button", { name: "Download asset" }).click();
  await expect(panel.getByRole("alert")).toContainText("503");
  await weights.getByRole("button", { name: "Pause download" }).click();
  await expect(weights).toContainText("paused");
  await weights.getByRole("button", { name: "Cancel download" }).click();
  await expect(weights).toContainText("cancelled");
  await page.reload();
  await open();
  await expect(weights).toContainText("cancelled");
  await weights.getByRole("button", { name: "Resume download" }).click();
  await expect(weights).toContainText("downloaded", { timeout: 20000 });
  expect(submissions).toBe(1);
  const downloads = await (
    await request.get(base + "/v1/downloads", { headers })
  ).json();
  expect(
    downloads.filter((d: { asset_id: string }) => d.asset_id === "ui-model"),
  ).toHaveLength(1);
  await archive.getByRole("button", { name: "Download asset" }).click();
  await expect(archive).toContainText("downloaded");
  await panel.getByRole("button", { name: "Runtimes", exact: true }).click();
  await panel.getByRole("button", { name: "Install runtime" }).click();
  await expect(panel.getByRole("status")).toContainText("Runtime installed");
  await panel.getByRole("button", { name: "Add model", exact: true }).click();
  await panel.getByLabel("Model ID", { exact: true }).fill("ui-managed");
  await panel
    .getByLabel("Display name", { exact: true })
    .fill("<b>Local UI model</b>");
  await panel
    .getByLabel("Downloaded model", { exact: true })
    .selectOption("ui-model");
  await panel
    .getByLabel("Installed runtime", { exact: true })
    .selectOption("ui-runtime");
  await panel.getByLabel("Context tokens", { exact: true }).fill("512");
  await expect(
    panel.getByRole("button", { name: "Add configured model" }),
  ).toBeDisabled();
  await panel.getByLabel("Maximum output tokens", { exact: true }).fill("128");
  await panel.getByRole("button", { name: "Add configured model" }).click();
  await expect(panel.getByRole("alert")).toContainText("503");
  await expect(panel.getByLabel("Model ID", { exact: true })).toHaveValue(
    "ui-managed",
  );
  await panel.getByRole("button", { name: "Add configured model" }).click();
  await expect(panel.getByRole("alert")).toContainText("409");
  await panel
    .getByRole("button", { name: "Available models", exact: true })
    .click();
  await expect(
    panel.getByRole("heading", { name: "<b>Local UI model</b>-NA" }),
  ).toBeVisible();
  await expect(panel.locator("article b")).toHaveCount(0);
  expect(
    (await (await request.get(base + "/v1/models", { headers })).json()).filter(
      (m: { id: string }) => m.id === "ui-managed",
    ),
  ).toHaveLength(1);
  await panel
    .getByRole("button", { name: "Model Library", exact: true })
    .click();
  await weights.getByRole("button", { name: "Remove download…" }).click();
  await panel.getByRole("button", { name: "Keep it" }).click();
  await expect(weights).toContainText("downloaded");
  await weights.getByRole("button", { name: "Remove download…" }).click();
  await panel.getByRole("button", { name: "Confirm removal" }).click();
  await expect(panel.getByRole("alert")).toContainText("409");
  await panel
    .getByRole("button", { name: "Available models", exact: true })
    .click();
  await panel.getByRole("button", { name: "Forget model…" }).click();
  await panel.getByRole("button", { name: "Confirm removal" }).click();
  await expect(
    panel.getByRole("heading", { name: "<b>Local UI model</b>-NA" }),
  ).toHaveCount(0);
  await panel.getByRole("button", { name: "Runtimes", exact: true }).click();
  await panel.getByRole("button", { name: "Remove runtime…" }).click();
  await panel.getByRole("button", { name: "Confirm removal" }).click();
  await expect(
    panel.getByRole("button", { name: "Install runtime" }),
  ).toBeEnabled();
  await panel
    .getByRole("button", { name: "Model Library", exact: true })
    .click();
  for (const card of [weights, archive]) {
    await card.getByRole("button", { name: "Remove download…" }).click();
    await panel.getByRole("button", { name: "Confirm removal" }).click();
    await expect(
      card.getByRole("button", { name: "Download asset" }),
    ).toBeVisible();
  }
  // Existing runtime registration uses a synthetic metadata verifier in this fixture.
  await panel.getByRole("button", { name: "Add model", exact: true }).click();
  await panel
    .getByLabel("Use an existing local Ollama or llama.cpp runtime")
    .check();
  await panel.getByLabel("Model ID", { exact: true }).fill("ui-external");
  await panel
    .getByLabel("Display name", { exact: true })
    .fill("Existing model");
  await panel
    .getByLabel("Runtime model identifier", { exact: true })
    .fill("local:test");
  await panel
    .getByLabel("Local runtime address", { exact: true })
    .fill("https://example.org");
  await panel.getByRole("button", { name: "Add configured model" }).click();
  await expect(panel.getByRole("alert")).toContainText("422");
  await panel
    .getByLabel("Local runtime address", { exact: true })
    .fill("http://127.0.0.1:11434");
  await panel.getByRole("button", { name: "Add configured model" }).click();
  await expect(panel.getByRole("status")).toContainText("Model added");
  await panel
    .getByRole("button", { name: "Available models", exact: true })
    .click();
  await expect(
    panel.getByRole("heading", { name: "Existing model-NA" }),
  ).toBeVisible();
  await page.screenshot({
    path: "../../../runtime/native-stage3h/models-preview.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "New chat", exact: false }).click();
  await expect(
    page.locator("header select option[value='ui-external']"),
  ).toHaveCount(1);
  await request.delete(base + "/v1/models/ui-external", { headers });
});

test("model management on a paired device requires the unchecked explicit grant", async ({
  page,
  request,
}) => {
  const base = "http://127.0.0.1:8766";
  const { token } = await (await request.get(base + "/test-credential")).json();
  await page.goto("/");
  await page.getByLabel("Backend address").fill(base);
  await page.getByLabel("Owner credential").fill(token);
  await page.getByRole("button", { name: "Connect to dsGPT" }).click();
  await page.getByRole("button", { name: "Settings", exact: false }).click();
  await page
    .getByRole("button", {
      name: "Pair a phone / Connected Devices",
      exact: false,
    })
    .click();
  await page.getByText("Manual connection", { exact: true }).click();
  await expect(page.getByLabel("Allow model management")).not.toBeChecked();
  const phones = [];
  for (const allowed of [false, true]) {
    await page.getByLabel("Allow model management").setChecked(allowed);
    await page.getByRole("button", { name: "Generate pairing code" }).click();
    await expect(page.locator("pre.code")).toBeVisible();
    const code = await page.locator("pre.code").textContent();
    const phone = await (
      await request.post(base + "/v1/pairings/redeem", {
        data: { code, name: "UI phone" },
      })
    ).json();
    expect(phone.scopes.includes("models")).toBe(allowed);
    phones.push(phone);
  }
  for (const [index, phone] of phones.entries()) {
    await page.reload();
    await page.getByLabel("Backend address").fill(base);
    await page.getByLabel("Owner credential").fill(phone.token);
    await page.getByRole("button", { name: "Connect to dsGPT" }).click();
    await page.getByRole("button", { name: "Settings", exact: false }).click();
    await page
      .getByRole("button", { name: "Open Models", exact: false })
      .click();
    if (index === 0)
      await expect(
        page.getByText("This device cannot manage models.", { exact: false }),
      ).toBeVisible();
    else
      await expect(
        page.getByRole("button", { name: "Model Library", exact: true }),
      ).toBeVisible();
  }
});
