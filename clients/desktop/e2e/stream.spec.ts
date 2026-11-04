import { test, expect } from "@playwright/test";
test("real backend SSE, disconnect and replay preserve one accepted request", async ({
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
  await page
    .getByLabel("Message", { exact: true })
    .fill("Integration recovery");
  await page.getByRole("button", { name: "Send ↑" }).click();
  await expect(page.locator("article.assistant")).toContainText("Word0");
  await page.getByRole("button", { name: "Settings", exact: false }).click();
  await page.waitForTimeout(3000);
  await page
    .getByRole("button", { name: "Integration recovery", exact: true })
    .click();
  await expect(page.locator("article.assistant")).toContainText("Word29");
  await expect(page.locator("article.user")).toHaveCount(1);
  const text = await page.locator("article.assistant .content").innerText();
  expect(text.match(/Word0\b/g)).toHaveLength(1);
  expect(text.match(/Word29\b/g)).toHaveLength(1);
  await page.screenshot({ path: "../../reports/desktop-ui-conversation.png" });
});
