import { test, expect } from "@playwright/test";

test("diagnostics categories expose measured status and preserve the reviewed export", async ({
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
    .getByRole("button", { name: "Open Diagnostics", exact: false })
    .click();
  const categories = page.getByLabel("Diagnostic categories");
  await expect(categories).toContainText("captured_at");
  await categories.getByText("Hardware Performance", { exact: true }).click();
  await expect(
    categories.locator("details").filter({
      has: page.locator("summary", { hasText: "Hardware Performance" }),
    }),
  ).toContainText("cpu_utilization_percent");
  await page
    .getByRole("button", { name: "Save snapshot now", exact: true })
    .click();
  await categories.getByText("Diagnostic History", { exact: true }).click();
  await expect(categories).toContainText('"reason": "manual"');
  await page
    .getByRole("button", { name: "Preview export", exact: true })
    .click();
  await categories.getByText("AI Model and Inference", { exact: true }).click();
  await expect(categories).toContainText("recent_requests");
  await categories
    .getByText("Export Diagnostics — complete preview", { exact: true })
    .click();
  await expect(categories).toContainText("desktop/inference-metrics.json");
  await expect(categories).toContainText("desktop/snapshots/");
  await expect(categories).not.toContainText(token);
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Save reviewed export…" }).click();
  expect((await download).suggestedFilename()).toMatch(/diagnostics.*\.zip/i);
  await page.getByLabel("Include build/test output", { exact: true }).check();
  await expect(
    page.getByRole("button", { name: "Save reviewed export…" }),
  ).toHaveCount(0);
  await expect(
    page.getByText("Project text, paths or unrecognized secrets may remain.", {
      exact: false,
    }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Preview export", exact: true })
    .click();
  await categories
    .getByText("Export Diagnostics — complete preview", { exact: true })
    .click();
  await expect(categories).toContainText("opt_in_build_logs");
  await page.screenshot({
    path: "../../reports/stage5-diagnostics.png",
    fullPage: true,
  });
});
