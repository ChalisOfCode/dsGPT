import { test, expect } from "@playwright/test";

test("source changes survive a lost response without replaying refresh and allow explicit restoration", async ({
  page,
  request,
}) => {
  const base = "http://127.0.0.1:8766";
  const { token } = await (await request.get(base + "/test-credential")).json();
  const headers = { Authorization: "Bearer " + token };
  const task = await (
    await request.post(base + "/v1/work/tasks", {
      headers,
      data: {
        title: "Source management",
        requirements: "Review references",
        model_id: "test-na",
        reference_urls: ["https://example.org/reference"],
      },
    })
  ).json();
  expect(task.id).toBeTruthy();
  await page.goto("/");
  await page.getByLabel("Backend address").fill(base);
  await page.getByLabel("Owner credential").fill(token);
  await page.getByRole("button", { name: "Connect to dsGPT" }).click();
  await page.getByRole("button", { name: "Work", exact: true }).click();
  const panel = page.getByRole("region", { name: "Work workspace" });
  await panel.getByRole("button", {name:"Recent tasks",exact:true}).click();
  await panel.getByRole("button", { name: /Source management/ }).click();
  await panel.getByText("Sources and execution details", {exact:true}).click();
  const sources = panel.getByRole("region", {
    name: "Work reference sources",
    exact: true,
  });
  await sources.locator("summary").click();
  let accepted = false;
  await page.route(
    `**/v1/work/tasks/${task.id}/sources/S1/actions`,
    async (route) => {
      if (!accepted) {
        await route.fetch();
        accepted = true;
        await route.abort("failed");
      } else await route.continue();
    },
  );
  await sources
    .getByRole("button", { name: "Refresh S1", exact: true })
    .click();
  await expect(
    sources.getByRole("region", { name: "Pending source change" }),
  ).toBeVisible();
  await sources
    .getByRole("button", { name: "Retry same source change" })
    .click();
  await expect(
    sources.getByRole("region", { name: "Pending source change" }),
  ).toHaveCount(0);
  let rows = await (
    await request.get(base + `/v1/work/tasks/${task.id}/sources`, { headers })
  ).json();
  expect(rows[0].generation).toBe(2);
  await sources.getByRole("button", { name: "Remove S1", exact: true }).click();
  await expect(sources.locator("summary")).toContainText("removed");
  await sources
    .getByRole("button", { name: "Restore and refresh S1", exact: true })
    .click();
  await expect(sources.locator("summary")).toContainText("pending");
  rows = await (
    await request.get(base + `/v1/work/tasks/${task.id}/sources`, { headers })
  ).json();
  expect(rows[0].generation).toBe(4);
});
