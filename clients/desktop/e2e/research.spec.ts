import { test, expect } from "@playwright/test";

test("research validates inputs, keeps source history and opens only a source URL", async ({
  page,
  request,
}) => {
  const { token } = await (
    await request.get("http://127.0.0.1:8766/test-credential")
  ).json();
  const submitted: Record<string, unknown>[] = [];
  page.on("request", (req) => {
    if (req.method() === "POST" && req.url().endsWith("/messages"))
      submitted.push(req.postDataJSON());
  });
  await page.addInitScript(() => {
    (window as unknown as { opened: unknown[] }).opened = [];
    window.open = (...args) => {
      (window as unknown as { opened: unknown[] }).opened.push(args);
      return null;
    };
  });
  await page.goto("/");
  await page.getByLabel("Backend address").fill("http://127.0.0.1:8766");
  await page.getByLabel("Owner credential").fill(token);
  await page.getByRole("button", { name: "Connect to dsGPT" }).click();
  await page
    .getByLabel("Message", { exact: true })
    .fill("Research source history");
  await page.getByRole("button", { name: "Add files and tools" }).click();
  await page.getByLabel("Research this message").check();
  await expect(page.getByLabel("Search the web")).toBeDisabled();
  await page.getByRole("button", { name: "Send ↑" }).click();
  await expect(page.getByRole("alert")).toContainText("Add a source URL");
  expect(submitted).toHaveLength(0);
  await page.getByLabel("Source URLs").fill("https://user:secret@example.org");
  await page.getByRole("button", { name: "Send ↑" }).click();
  await expect(page.getByRole("alert")).toContainText("without credentials");
  expect(submitted).toHaveLength(0);
  await page.getByLabel("Source URLs").fill("https://example.org/docs");
  await page.getByRole("button", { name: "Send ↑" }).click();
  await expect(page.locator("article.assistant")).toContainText("COBALT");
  expect(submitted[0].research).toEqual({
    search: false,
    urls: ["https://example.org/docs"],
  });
  await page
    .getByRole("button", { name: "View source S1", exact: true })
    .click();
  const sources = page.getByRole("region", { name: "Research sources" });
  await expect(sources).toContainText("<img src=x onerror=alert(1)>");
  await expect(sources.locator("img")).toHaveCount(0);
  await sources.getByRole("button", { name: "Open source" }).click();
  await page.screenshot({
    path: "../../../runtime/native-stage3e/research-preview.png",
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => (window as unknown as { opened: unknown[] }).opened,
    ),
  ).toEqual([["https://example.org/docs", "_blank", "noopener,noreferrer"]]);
  await page.getByRole("button", { name: "Settings", exact: false }).click();
  await page
    .getByRole("button", { name: "Research source history", exact: true })
    .click();
  await expect(page.getByLabel("Research this message")).not.toBeChecked();
  await page
    .getByRole("button", { name: "View source S1", exact: true })
    .click();
  await expect(
    page.getByRole("region", { name: "Research sources" }),
  ).toContainText("https://example.org/docs");
  await page.getByLabel("Message", { exact: true }).fill("Ordinary follow-up");
  await page.getByRole("button", { name: "Send ↑" }).click();
  await expect(page.locator("article.assistant").last()).toContainText(
    "Word29",
  );
  expect(submitted[1]).not.toHaveProperty("research");
  await expect(
    page.getByRole("button", { name: "View source S1", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "New chat" }).click();
  await page
    .getByLabel("Message", { exact: true })
    .fill("Unavailable research source");
  await page.getByRole("button", { name: "Add files and tools" }).click();
  await page.getByLabel("Research this message").check();
  await page.getByLabel("Source URLs").fill("https://example.org/missing");
  await page.getByRole("button", { name: "Send ↑" }).click();
  await expect(page.locator("article.assistant")).toContainText(
    "ended without a completed answer",
  );
  await page
    .getByRole("button", { name: "View sources", exact: false })
    .click();
  await expect(
    page.getByRole("region", { name: "Research sources" }),
  ).toContainText("could not be read");
});
