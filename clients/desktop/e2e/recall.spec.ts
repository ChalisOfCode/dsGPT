import { test, expect } from "@playwright/test";

test("retrieval sends only the selected scope and import removal needs confirmation", async ({
  page,
  request,
}) => {
  const base = "http://127.0.0.1:8766";
  const { token } = await (await request.get(base + "/test-credential")).json();
  const id = "20000000-0000-4000-8000-000000000001";
  const searches: Record<string, unknown>[] = [];
  let deletions = 0;
  await page.route("**/v1/work/tasks?limit=50", (route) =>
    route.fulfill({ json: [{ id, title: "Private project" }] }),
  );
  await page.route("**/v1/retrieval/search", async (route) => {
    searches.push(route.request().postDataJSON());
    await route.fulfill({
      json: {
        results: [
          {
            id,
            title: "<script>private</script>",
            content: "Scoped match",
            score: 0.61,
          },
        ],
        coverage: [{ status: "ready", sources: 1 }],
        score_meaning: "Similarity is not confidence",
      },
    });
  });
  await page.route("**/v1/history/imports**", async (route) => {
    if (route.request().method() === "DELETE") {
      deletions++;
      await route.fulfill({ json: { removed: true } });
    } else
      await route.fulfill({
        json: [
          {
            conversation_id: id,
            source_id: "source-1",
            source_title: "Imported fixture",
            removed: 0,
            imported_at: "2026-10-19",
          },
        ],
      });
  });
  await page.goto("/");
  await page.getByLabel("Backend address").fill(base);
  await page.getByLabel("Owner credential").fill(token);
  await page.getByRole("button", { name: "Connect to dsGPT" }).click();
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: "History and retrieval →" }).click();
  const panel = page.getByRole("region", { name: "History and retrieval" });
  await panel.getByLabel("Retrieval scope").selectOption(id);
  await panel.getByLabel("Search method").selectOption("semantic");
  await panel
    .getByLabel("Search private content", { exact: true })
    .fill("design");
  await panel
    .getByRole("button", { name: "Search private content", exact: true })
    .click();
  await expect(panel).toContainText("Scoped match");
  expect(searches[0]).toEqual({
    query: "design",
    kind: "memory",
    task_id: id,
    hidden: false,
    limit: 20,
  });
  await expect(panel.locator("script")).toHaveCount(0);
  await panel.getByLabel("Retrieval scope").selectOption("history");
  await expect(panel).not.toContainText("Scoped match");
  await panel.getByLabel("Include hidden chats").check();
  await panel
    .getByRole("button", { name: "Search private content", exact: true })
    .click();
  await expect.poll(() => searches.length).toBe(2);
  expect(searches[1]).toEqual({
    query: "design",
    kind: "history",
    task_id: null,
    hidden: true,
    limit: 20,
  });
  await panel.getByLabel("Retrieval scope").selectOption("attachments");
  await panel.getByLabel("Search method").selectOption("semantic");
  await panel
    .getByRole("button", { name: "Search private content", exact: true })
    .click();
  await expect.poll(() => searches.length).toBe(3);
  expect(searches[2]).toEqual({
    query: "design",
    kind: "attachment",
    task_id: null,
    hidden: true,
    limit: 20,
  });
  await panel.getByRole("button", { name: "Remove imported source…" }).click();
  await expect(panel.getByRole("alertdialog")).toContainText(
    "every imported version",
  );
  expect(deletions).toBe(0);
  await panel.getByRole("button", { name: "Keep source" }).click();
  expect(deletions).toBe(0);
  await panel.getByRole("button", { name: "Remove imported source…" }).click();
  await panel.getByRole("button", { name: "Confirm source removal" }).click();
  await expect(panel).toContainText("Removed source");
  expect(deletions).toBe(1);
  await expect(panel).not.toContainText("Scoped match");
});
