import { test, expect } from "@playwright/test";

test("a task reads its granted account page only on request and clears it on revision change", async ({
  page,
  request,
}) => {
  const base = "http://127.0.0.1:8766";
  const { token } = await (await request.get(base + "/test-credential")).json();
  const headers = { Authorization: `Bearer ${token}` };
  const title = "Private read UI fixture";
  const task = await (
    await request.post(base + "/v1/work/tasks", {
      headers,
      data: {
        title,
        requirements: "Inspect the granted fixture",
        start: false,
      },
    })
  ).json();
  const path = `${base}/v1/work/tasks/${task.id}/account-grants`;
  const grant = "00000000-0000-4000-8000-000000000015";
  let lists = 0,
    reads = 0;
  await page.route(path, async (route) => {
    lists++;
    await route.fulfill({
      json: [
        {
          id: grant,
          task_revision: task.revision,
          label: "Fixture grant",
          origin: "https://example.org",
          read_path: "/account",
        },
      ],
    });
  });
  const privateText = "<b>Private page fixture</b>";
  await page.route(path + "/" + grant + "/read", async (route) => {
    expect(route.request().method()).toBe("POST");
    reads++;
    await route.fulfill({ json: { text: privateText, truncated: false } });
  });
  await page.goto("/");
  await page.getByLabel("Backend address").fill(base);
  await page.getByLabel("Owner credential").fill(token);
  await page.getByRole("button", { name: "Connect to dsGPT" }).click();
  await page.getByRole("button", { name: "Work", exact: true }).click();
  const workspace = page.getByRole("region", { name: "Work workspace" });
  await workspace.getByRole("button", { name: "Recent tasks" }).click();
  await workspace.getByRole("button", { name: new RegExp(title) }).click();
  const panel = workspace.getByRole("region", {
    name: "Private account reads",
  });
  await expect(panel).toBeVisible();
  expect(lists).toBe(0);
  await panel
    .getByRole("button", { name: "Check private account grants" })
    .click();
  await expect(
    panel.getByText("Fixture grant", { exact: false }),
  ).toBeVisible();
  expect(reads).toBe(0);
  await panel.getByRole("button", { name: "Read approved page" }).click();
  await expect(panel.getByLabel("Private account page")).toHaveText(
    privateText,
  );
  expect(reads).toBe(1);
  await expect(panel.locator("b")).toHaveCount(0);
  const changed = await request.patch(`${base}/v1/work/tasks/${task.id}`, {
    headers,
    data: { revision: task.revision, note: "Changed without the private page" },
  });
  expect(changed.ok()).toBeTruthy();
  await expect(workspace.getByLabel("Task status")).toContainText(
    `revision ${task.revision + 1}`,
  );
  await expect(panel.getByLabel("Private account page")).toHaveCount(0);
  expect(reads).toBe(1);
  expect(
    await page.evaluate(() =>
      JSON.stringify({ ...localStorage, ...sessionStorage }),
    ),
  ).not.toContain(privateText);
});
