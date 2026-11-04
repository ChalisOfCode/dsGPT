import { test, expect } from "@playwright/test";
test("chat controls, hidden search exclusion, reading position and incremental replies", async ({
  page,
}) => {
  const chat = {
    id: "11111111-1111-4111-8111-111111111111",
    title: "Research notes",
    hidden: 0,
    pinned: 0,
    pin_order: 0,
    revision: 1,
    model_id: "local-na",
  };
  let text = Array.from(
    { length: 70 },
    (_, i) => `Paragraph ${i}: saved reading context.`,
  ).join("\n\n");
  const message = () => ({
    id: "m",
    conversation_id: chat.id,
    role: "assistant",
    ordinal: 2,
    content: text,
    status: "completed",
  });
  let hiddenQuery = false;
  await page.route("http://127.0.0.1:8765/**", async (route) => {
    const u = new URL(route.request().url()),
      p = u.pathname;
    let body: unknown = {};
    if (p === "/v1/models")
      body = [
        {
          id: "local-na",
          label: "Local model-NA",
          context: 8192,
          output_tokens: 1024,
        },
      ];
    else if (p === "/v1/conversations") {
      hiddenQuery = u.searchParams.get("hidden") === "true";
      body = Boolean(chat.hidden) === hiddenQuery ? [chat] : [];
    } else if (p.endsWith("/messages")) body = [message()];
    else if (p.endsWith("/latest-run"))
      body = {
        run: { id: "run", message_id: "m", status: "completed" },
        message: message(),
        cursor: 2,
      };
    else if (route.request().method() === "PATCH") {
      Object.assign(chat, route.request().postDataJSON(), {
        revision: chat.revision + 1,
      });
      body = chat;
    }
    await route.fulfill({
      json: body,
      headers: { "Access-Control-Allow-Origin": "*" },
    });
  });
  await page.goto("/");
  await page
    .getByLabel("Owner credential")
    .fill("test-credential-not-a-real-secret");
  await page.getByRole("button", { name: "Connect to dsGPT" }).click();
  await page
    .getByRole("button", { name: "Research notes", exact: true })
    .click();
  await expect(page.locator("article")).toHaveCount(1);
  await page.locator(".messages").evaluate((el) => {
    el.scrollTop = 200;
    el.dispatchEvent(new Event("scroll"));
  });
  await expect(
    page.getByRole("button", { name: "Jump to latest" }),
  ).toBeVisible();
  const old = await page.locator(".messages").evaluate((el) => el.scrollTop);
  await page.getByRole("tab", { name: "Work", exact: true }).click();
  await page.getByRole("tab", { name: "Chat", exact: true }).click();
  await expect
    .poll(() => page.locator(".messages").evaluate((el) => el.scrollTop))
    .toBeCloseTo(old, 0);
  text += "\n\nNEW REPLY DATA\n".repeat(30);
  await expect(page.locator(".content")).toContainText("NEW REPLY DATA");
  expect(
    await page.locator(".messages").evaluate((el) => el.scrollTop),
  ).toBeCloseTo(old, 0);
  await page.getByRole("button", { name: "Settings", exact: false }).click();
  await page
    .getByRole("button", { name: "Research notes", exact: true })
    .click();
  await expect(page.locator("article")).toHaveCount(1);
  await expect
    .poll(() => page.locator(".messages").evaluate((el) => el.scrollTop))
    .toBeCloseTo(old, 0);
  await page.getByRole("button", { name: "Jump to latest" }).click();
  await expect(
    page.getByRole("button", { name: "Jump to latest" }),
  ).toHaveCount(0);
  await page.locator("aside").getByLabel("Actions for Research notes").click();
  await page.getByRole("button", { name: "Pin", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "◆ Research notes" }),
  ).toBeVisible();
  await page.locator("aside").getByLabel("Actions for Research notes").click();
  await page.getByRole("button", { name: "Hide", exact: true }).click();
  await expect(page.locator(".chatrow")).toHaveCount(0);
  expect(chat.pinned).toBe(true);
  await page.getByRole("button", { name: "Settings", exact: false }).click();
  await page.getByRole("button", { name: "Hidden Chats →" }).click();
  await expect(page.locator(".hiddenrow")).toContainText("Research notes");
  expect(hiddenQuery).toBe(true);
  await page.getByRole("button", { name: "Unhide", exact: true }).click();
  await expect(page.locator(".hiddenrow")).toHaveCount(0);
  expect(chat.pinned).toBe(true);
  await page.getByRole("button", { name: "New chat" }).click();
  await page.screenshot({
    path: "../../reports/desktop-chat.png",
    fullPage: true,
  });
});
