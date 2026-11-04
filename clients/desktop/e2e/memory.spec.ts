import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";

test("Memory retries, scopes, conflicts, exports and deletion stay consistent", async ({
  page,
  request,
}, testInfo) => {
  test.setTimeout(60000);
  const base = "http://127.0.0.1:8766";
  const { token } = await (await request.get(base + "/test-credential")).json();
  const headers = { Authorization: `Bearer ${token}` };
  const project = await (
    await request.post(base + "/v1/work/tasks", {
      headers,
      data: { title: "Memory project", requirements: "Keep scoped notes" },
    })
  ).json();
  const projectMemory = await (
    await request.post(base + "/v1/memories", {
      headers,
      data: {
        title: "Project plan",
        content: "Project amber decisions",
        task_id: project.id,
      },
    })
  ).json();
  const bodies: Record<string, unknown>[] = [];
  let lose = true;
  await page.route("**/v1/memories", async (route) => {
    if (route.request().method() !== "POST") {
      await route.continue();
      return;
    }
    bodies.push(route.request().postDataJSON());
    const response = await route.fetch();
    if (lose) {
      lose = false;
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: "{}",
      });
    } else await route.fulfill({ response });
  });
  async function open() {
    await page.getByLabel("Backend address").fill(base);
    await page.getByLabel("Owner credential").fill(token);
    await page.getByRole("button", { name: "Connect to dsGPT" }).click();
    await page.getByRole("button", { name: "Settings", exact: false }).click();
    await page
      .getByRole("button", { name: "Open Memory", exact: false })
      .click();
  }
  await page.goto("/");
  await open();
  const panel = page.getByRole("region", { name: "Memory workspace" });
  await panel.getByRole("button", { name: "Add memory", exact: true }).click();
  await panel
    .getByLabel("Memory title", { exact: true })
    .fill("<b>Preference</b>");
  await panel
    .getByLabel("Memory content", { exact: true })
    .fill("Personal sapphire");
  await panel.getByRole("button", { name: "Save memory", exact: true }).click();
  await expect(panel.getByRole("alert")).toContainText("503");
  await panel.getByRole("button", { name: "Save memory", exact: true }).click();
  await expect(panel.getByRole("status")).toContainText("Memory saved");
  expect(bodies).toHaveLength(2);
  expect(bodies[0].request_id).toEqual(bodies[1].request_id);
  const id = bodies[0].request_id;
  let rows = await (
    await request.get(base + "/v1/memories", { headers })
  ).json();
  expect(rows.filter((r: { id: string }) => r.id === id)).toHaveLength(1);
  await expect(panel.locator("article b")).toHaveCount(0);
  await expect(panel.getByText("Project amber decisions")).toHaveCount(0);
  await panel.getByLabel("Search memories").fill("sapphire");
  await expect(panel.locator("article")).toHaveCount(1);
  await panel
    .getByRole("button", { name: "Edit <b>Preference</b>", exact: true })
    .click();
  await panel
    .getByLabel("Memory content", { exact: true })
    .fill("Unsaved local changes");
  await request.patch(`${base}/v1/memories/${id}`, {
    headers,
    data: {
      revision: 1,
      title: "From another device",
      content: "Personal sapphire changed",
    },
  });
  await panel.getByRole("button", { name: "Refresh memories" }).click();
  await expect(
    panel.getByRole("heading", { name: "From another device" }),
  ).toBeVisible();
  await panel.getByRole("button", { name: "Save memory", exact: true }).click();
  await expect(panel.getByRole("alert")).toContainText("409");
  await expect(panel.getByLabel("Memory content", { exact: true })).toHaveValue(
    "Unsaved local changes",
  );
  await panel.getByRole("button", { name: "Cancel editing" }).click();
  await panel
    .getByRole("button", { name: "Edit From another device", exact: true })
    .click();
  await panel
    .getByLabel("Memory title", { exact: true })
    .fill("Updated personal");
  await panel
    .getByLabel("Memory content", { exact: true })
    .fill("Personal sapphire revised");
  await panel.getByRole("button", { name: "Save memory", exact: true }).click();
  await expect(
    panel.getByRole("heading", { name: "Updated personal" }),
  ).toBeVisible();
  await panel.getByLabel("Memory scope").selectOption(project.id);
  await expect(
    panel.getByRole("heading", { name: "Project plan" }),
  ).toBeVisible();
  await expect(panel.getByText("Personal sapphire revised")).toHaveCount(0);
  const pending = page.waitForEvent("download");
  await panel.getByRole("button", { name: "Export scope JSON…" }).click();
  const downloaded = await pending;
  const path = testInfo.outputPath("memory.json");
  await downloaded.saveAs(path);
  const exported = JSON.parse(readFileSync(path, "utf8"));
  expect(exported.format).toBe("dsgpt-memory-v1");
  expect(exported.memories.map((r: { id: string }) => r.id)).toEqual([
    projectMemory.id,
  ]);
  expect(JSON.stringify(exported)).not.toContain(token);
  await page.screenshot({
    path: "../../../runtime/native-stage3g/memory-preview.png",
    fullPage: true,
  });
  await panel.getByLabel("Memory scope").selectOption("");
  await panel
    .getByRole("button", { name: "Delete Updated personal", exact: true })
    .click();
  await panel
    .getByRole("alertdialog")
    .getByRole("button", { name: "Cancel", exact: true })
    .click();
  await expect(
    panel.getByRole("heading", { name: "Updated personal" }),
  ).toBeVisible();
  await panel
    .getByRole("button", { name: "Delete Updated personal", exact: true })
    .click();
  await panel
    .getByRole("alertdialog")
    .getByRole("button", { name: "Delete memory", exact: true })
    .click();
  await expect(panel.locator("article")).toHaveCount(0);
  expect(
    (
      await request.post(base + "/v1/memories", { headers, data: bodies[0] })
    ).status(),
  ).toBe(409);
  await page.reload();
  await open();
  await expect(
    panel.getByText("No memories found in this scope."),
  ).toBeVisible();
});
