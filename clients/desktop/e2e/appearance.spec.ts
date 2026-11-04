import { test, expect, type Page } from "@playwright/test";

async function connect(page: Page) {
  await page.getByLabel("Owner credential").fill("appearance-test-only");
  await page.getByRole("button", { name: "Connect to dsGPT" }).click();
  await expect(page.getByLabel("Message", { exact: true })).toBeVisible();
}

test("themes, compact sidebar and composer tools remain usable after reopening", async ({
  page,
}) => {
  await page.emulateMedia({ colorScheme: "light" });
  await page.route("http://127.0.0.1:8765/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const body =
      path === "/v1/models"
        ? [
            {
              id: "local",
              label: "Local model",
              context: 8192,
              output_tokens: 1024,
            },
          ]
        : path === "/v1/conversations"
          ? []
          : path === "/v1/research/capabilities"
            ? { public_page_reading: true, search_configured: false }
            : {};
    await route.fulfill({
      json: body,
      headers: { "Access-Control-Allow-Origin": "*" },
    });
  });
  await page.goto("/");
  await connect(page);
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect(
    page.getByRole("heading", { name: "What can I help with?" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Attach document/image…" }),
  ).toBeHidden();
  await page.screenshot({ path: "../../reports/desktop-ui-light.png" });
  const add = page.getByRole("button", { name: "Add files and tools" });
  await add.click();
  await expect(
    page.getByRole("button", { name: "Attach document/image…" }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(add).toBeFocused();
  await expect(add).toHaveAttribute("aria-expanded", "false");
  await add.click();
  await page.getByLabel("Research this message").check();
  await expect(page.getByLabel("Source URLs")).toBeVisible();
  await expect(add).toHaveAttribute("aria-expanded", "false");
  await page.getByRole("button", { name: "Turn off Research" }).click();
  await add.click();
  await page.getByLabel("Attach text files").setInputFiles({
    name: "notes.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("My local notes"),
  });
  await expect(
    page.getByRole("button", { name: "Remove selected notes.txt" }),
  ).toBeVisible();
  await expect(add).toHaveAttribute("aria-expanded", "false");
  await page.getByRole("button", { name: "Remove selected notes.txt" }).click();
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByLabel("Theme").selectOption("dark");
  await page.getByRole("button", { name: "New chat", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.screenshot({ path: "../../reports/desktop-ui-dark.png" });
  await page.getByRole("button", { name: "Collapse sidebar" }).click();
  await expect(page.getByLabel("Search chats", { exact: true })).toBeHidden();
  await page.reload();
  await connect(page);
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(
    page.getByRole("button", { name: "Expand sidebar" }),
  ).toBeVisible();
  await page.setViewportSize({ width: 720, height: 540 });
  const message = page.getByLabel("Message", { exact: true });
  await message.fill("First line");
  await message.press("Shift+Enter");
  await message.pressSequentially("Second line");
  await expect(message).toHaveValue("First line\nSecond line");
  await expect(page.getByRole("button", { name: "Send ↑" })).toBeInViewport();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({ path: "../../reports/desktop-ui-narrow.png" });
  await page.getByRole("button", { name: "Expand sidebar" }).click();
  await add.click();
  await expect(page.getByLabel("Research this message")).toBeInViewport();
  await page.getByLabel("Research this message").check();
  await expect(page.getByLabel("Message", { exact: true })).toBeInViewport();
  await page.getByLabel("Source URLs").fill("https://example.org/docs");
  await expect(page.getByLabel("Source URLs")).toBeInViewport();
  await page.getByRole("button", { name: "Turn off Research" }).click();
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByLabel("Theme").selectOption("system");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});

test("top Chat and Work modes preserve both drafts and support the keyboard", async ({
  page,
  request,
}) => {
  const { token } = await (
    await request.get("http://127.0.0.1:8766/test-credential")
  ).json();
  await page.goto("/");
  await page.getByLabel("Backend address").fill("http://127.0.0.1:8766");
  await page.getByLabel("Owner credential").fill(token);
  await page.getByRole("button", { name: "Connect to dsGPT" }).click();
  const chat = page.getByRole("tab", { name: "Chat", exact: true });
  const work = page.getByRole("tab", { name: "Work", exact: true });
  await expect(chat).toHaveAttribute("aria-selected", "true");
  await page
    .getByLabel("Message", { exact: true })
    .fill("Keep this chat draft");
  await work.click();
  await expect(work).toHaveAttribute("aria-selected", "true");
  await expect(page.getByLabel("Output target")).toBeHidden();
  await page
    .getByRole("textbox", { name: "Work prompt", exact: true })
    .fill("Build my project when I return");
  await work.press("ArrowLeft");
  await expect(chat).toBeFocused();
  await expect(page.getByLabel("Message", { exact: true })).toHaveValue(
    "Keep this chat draft",
  );
  await chat.press("End");
  await expect(work).toBeFocused();
  await expect(
    page.getByRole("textbox", { name: "Work prompt", exact: true }),
  ).toHaveValue("Build my project when I return");
  await page.screenshot({ path: "../../reports/desktop-mode-work.png" });
  await page.setViewportSize({ width: 720, height: 540 });
  await chat.click();
  await expect(chat).toBeInViewport();
  await expect(work).toBeInViewport();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
