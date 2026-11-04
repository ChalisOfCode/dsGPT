import { test, expect } from "@playwright/test";

test("header and sidebar share rename, pin, files and real deletion", async ({
  page,
  request,
}) => {
  const base = "http://127.0.0.1:8766";
  const { token } = await (await request.get(base + "/test-credential")).json();
  const headers = { Authorization: `Bearer ${token}` };
  const chat = await (
    await request.post(base + "/v1/conversations", {
      headers,
      data: { title: "Navigation fixture" },
    })
  ).json();
  await page.goto("/");
  await page.getByLabel("Backend address").fill(base);
  await page.getByLabel("Owner credential").fill(token);
  await page.getByRole("button", { name: "Connect to dsGPT" }).click();
  await page
    .locator("aside")
    .getByRole("button", { name: "Navigation fixture", exact: true })
    .click();
  const header = page.locator("main > header");
  await expect(header.locator(".page-title")).toHaveText("Navigation fixture");
  await expect(
    header.getByRole("button", { name: "New chat", exact: true }),
  ).toBeVisible();
  await header.getByLabel("Actions for Navigation fixture").click();
  await header.getByRole("button", { name: "Rename", exact: true }).click();
  const rename = page.getByRole("dialog", { name: "Rename chat" });
  await rename.getByLabel("Chat name").fill("Renamed fixture");
  await rename.getByRole("button", { name: "Save", exact: true }).click();
  await expect(header.locator(".page-title")).toHaveText("Renamed fixture");
  await header.getByLabel("Actions for Renamed fixture").click();
  await header.getByRole("button", { name: "Pin", exact: true }).click();
  await expect(
    page
      .locator("aside")
      .getByRole("button", { name: "◆ Renamed fixture", exact: true }),
  ).toBeVisible();
  await header.getByLabel("Actions for Renamed fixture").click();
  await header.getByRole("button", { name: "Files", exact: true }).click();
  const files = page.getByRole("dialog", { name: "Files in Renamed fixture" });
  await expect(files).toContainText("No files attached");
  await files.getByRole("button", { name: "Close", exact: true }).click();
  await page.locator("aside").getByLabel("Actions for Renamed fixture").click();
  await page
    .locator("aside")
    .getByRole("button", { name: "Delete chat", exact: true })
    .click();
  await page
    .getByRole("dialog", { name: "Delete chat", exact: true })
    .getByRole("button", { name: "Delete chat", exact: true })
    .click();
  await expect(header.locator(".page-title")).toHaveText("New chat");
  const chats = await (
    await request.get(base + "/v1/conversations", { headers })
  ).json();
  expect(chats.some((c: { id: string }) => c.id === chat.id)).toBe(false);
  await page.screenshot({
    path: "../../reports/desktop-chat-management.png",
    fullPage: true,
  });
});

test("large Work file streams in chunks", async ({ page, request }) => {
  const base = "http://127.0.0.1:8766";
  const { token } = await (await request.get(base + "/test-credential")).json();
  const chunks: number[] = [];
  await page.route("**/v1/work/uploads/*", async (route) => {
    if (route.request().method() === "PUT")
      chunks.push(route.request().postDataJSON().offset);
    await route.continue();
  });
  await page.goto("/");
  await page.getByLabel("Backend address").fill(base);
  await page.getByLabel("Owner credential").fill(token);
  await page.getByRole("button", { name: "Connect to dsGPT" }).click();
  await page.getByRole("tab", { name: "Work", exact: true }).click();
  const panel = page.getByRole("region", { name: "Work workspace" });
  await panel.getByText("Add files and task options", { exact: true }).click();
  await panel.getByLabel("Start immediately").uncheck();
  await panel.getByLabel("Output target").selectOption("files");
  await panel
    .getByLabel("Task title (optional)", { exact: true })
    .fill("Large upload fixture");
  await panel
    .getByLabel("Work prompt", { exact: true })
    .fill("Inspect this original file");
  await panel.getByLabel("Upload Work file").setInputFiles({
    name: "large.bin",
    mimeType: "application/octet-stream",
    buffer: Buffer.alloc(3 * 1024 * 1024 + 17, 65),
  });
  await expect(
    panel.locator("p").filter({ hasText: "large.bin", has: page.getByRole("button", {name:"Remove",exact:true}) }),
  ).toBeVisible();
  expect(chunks).toHaveLength(13);
  expect(chunks[12]).toBe(3 * 1024 * 1024);
  await panel.getByRole("button", { name: "Send Work prompt" }).click();
  await expect(panel.getByLabel("Task status")).toContainText("draft");
});
