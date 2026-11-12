import { test, expect } from "@playwright/test";

test("document evidence distinguishes partial review, calculation errors and old outputs", async ({page, request}) => {
  const base = "http://127.0.0.1:8766";
  const { token } = await (await request.get(base + "/test-credential")).json();
  const id = "10000000-0000-4000-8000-000000000001";
  const execution = "10000000-0000-4000-8000-000000000002";
  const task = {id, title: "Office evidence fixture", requirements: "Review document", status: "paused",
    revision: 1, build_target: "files", execution_available: true, code_execution_available: true, session: null};
  let summary = "Rendered 2 pages. Visual review recorded for pages: 1 (1/2). Review coverage is not a layout pass.";
  let writes = 0;
  await page.route("**/v1/work/tasks**", async route => {
    const req = route.request(), path = new URL(req.url()).pathname;
    if (req.method() !== "GET") writes++;
    const body = path.endsWith(`/executions/${execution}`) ? {document_validation_summary: summary}
      : path.endsWith("/executions") ? [{id: execution, step: 1, status: "completed", cleanup_pending: false, snapshot_sha256: "a".repeat(64)}]
      : /\/(artifacts|files|steps|references)$/.test(path) ? []
      : path.endsWith(id) ? task : [task];
    await route.fulfill({json: body});
  });
  await page.goto("/");
  await page.getByLabel("Backend address").fill(base);
  await page.getByLabel("Owner credential").fill(token);
  await page.getByRole("button", {name: "Connect to dsGPT"}).click();
  await page.getByRole("button", {name: "Work", exact: true}).click();
  await page.getByRole("button", {name: "Recent tasks", exact: true}).click();
  await page.getByRole("button", {name: /Office evidence fixture/}).click();
  await page.getByText("Sources and execution details", {exact: true}).click();
  const panel = page.getByRole("region", {name: "Build evidence"});
  await panel.getByText("Build details", {exact: true}).click();
  await panel.getByText("Step 1 · completed", {exact: true}).click();
  const read = panel.getByRole("button", {name: "Read receipt and logs"});
  await read.click();
  await expect(panel.getByRole("status", {name: "Document validation"})).toHaveText(summary);
  summary = "Calculation has errors or changes. Formatting preservation and visual layout are unverified.";
  await read.click();
  await expect(panel.getByRole("status", {name: "Document validation"})).toHaveText(summary);
  summary = "Historical document result. Current-source validation is unavailable.";
  await read.click();
  await expect(panel.getByRole("status", {name: "Document validation"})).toHaveText(summary);
  expect(writes).toBe(0);
});
