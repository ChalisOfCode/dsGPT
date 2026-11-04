import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";

test("Work retries once, rejects stale edits, pauses, recovers across Chat and exports source", async ({
  page,
  request,
}, testInfo) => {
  test.setTimeout(60000);
  const base = "http://127.0.0.1:8766";
  const { token } = await (await request.get(base + "/test-credential")).json();
  const headers = { Authorization: `Bearer ${token}` };
  const creations: Record<string, unknown>[] = [];
  let loseFirst = true;
  await page.route("**/v1/work/tasks", async (route) => {
    if (route.request().method() !== "POST") {
      await route.continue();
      return;
    }
    creations.push(route.request().postDataJSON());
    const response = await route.fetch();
    if (loseFirst) {
      loseFirst = false;
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: "{}",
      });
    } else await route.fulfill({ response });
  });
  await page.goto("/");
  await page.getByLabel("Backend address").fill(base);
  await page.getByLabel("Owner credential").fill(token);
  await page.getByRole("button", { name: "Connect to dsGPT" }).click();
  await page.getByRole("button", { name: "Work", exact: true }).click();
  const panel = page.getByRole("region", { name: "Work workspace" });
  await panel.getByText("Add files and task options", { exact: true }).click();
  await panel.getByLabel("Start immediately").uncheck();
  await panel.getByLabel("Output target").selectOption("source");
  await panel
    .getByLabel("Task title (optional)", { exact: true })
    .fill("Work retry <img src=x>");
  await panel
    .getByLabel("Work prompt", { exact: true })
    .fill("Draft the fixture hello.txt source.");
  await panel.getByRole("button", { name: "Send Work prompt" }).click();
  await expect(panel.getByRole("alert")).toContainText("503");
  await panel.getByRole("button", { name: "Send Work prompt" }).click();
  await expect(panel.getByLabel("Task status")).toContainText("draft");
  expect(creations).toHaveLength(2);
  expect(creations[0]).not.toHaveProperty("reference_urls");
  expect(creations[1]).not.toHaveProperty("reference_urls");
  expect(creations[0].request_id).toEqual(creations[1].request_id);
  const id = creations[0].request_id as string;
  const rows = await (
    await request.get(base + "/v1/work/tasks", { headers })
  ).json();
  expect(rows.filter((t: { id: string }) => t.id === id)).toHaveLength(1);
  await expect(panel.locator("img")).toHaveCount(0);
  await panel.getByText("Task update options", { exact: true }).click();
  await panel.getByLabel("Add instructions").fill("Local unsaved note");
  const before = await (
    await request.get(`${base}/v1/work/tasks/${id}`, { headers })
  ).json();
  await request.patch(`${base}/v1/work/tasks/${id}`, {
    headers,
    data: { revision: before.revision, note: "External device note" },
  });
  await expect(panel.getByLabel("Task status")).toContainText("revision 2");
  await panel.getByRole("button", { name: "Save task update" }).click();
  await expect(panel.getByRole("alert")).toContainText("409");
  await expect(panel.getByLabel("Add instructions")).toHaveValue(
    "Local unsaved note",
  );
  let updated = await (
    await request.get(`${base}/v1/work/tasks/${id}`, { headers })
  ).json();
  expect(updated.requirements).not.toContain("Local unsaved note");
  await panel.getByRole("button", { name: "Clear update and reload" }).click();
  await panel
    .getByLabel("Add instructions")
    .fill("Keep the output plain text.");
  await panel.getByRole("button", { name: "Save task update" }).click();
  await expect(panel.getByLabel("Add instructions")).toHaveValue("");
  await panel.getByRole("button", { name: "Start drafting" }).click();
  await expect(panel.getByLabel("Task status")).toContainText("running");
  await panel.getByRole("button", { name: "Pause", exact: true }).click();
  await expect(panel.getByLabel("Task status")).toContainText("paused");
  await panel.getByRole("button", { name: "Resume", exact: true }).click();
  await page.getByRole("button", { name: "New chat", exact: false }).click();
  await page
    .getByLabel("Message", { exact: true })
    .fill("Chat while Work continues");
  await page.getByRole("button", { name: "Send ↑" }).click();
  await expect(page.locator("article.assistant")).toContainText("Word29", {
    timeout: 15000,
  });
  await page.getByRole("button", { name: "Work", exact: true }).click();
  await expect(panel.getByLabel("Task status")).toContainText(
    "Draft complete",
    { timeout: 15000 },
  );
  await expect(panel.getByText("hello.txt ·", { exact: false })).toBeVisible();
  await page.screenshot({
    path: "../../../runtime/native-stage3f/work-preview.png",
    fullPage: true,
  });
  const downloadPromise = page.waitForEvent("download");
  await panel.getByRole("button", { name: "Save source ZIP…" }).click();
  const download = await downloadPromise;
  const path = testInfo.outputPath("project.zip");
  await download.saveAs(path);
  const inspected = JSON.parse(
    execFileSync(
      process.env.DSGPT_TEST_PYTHON || "../../../.venv/bin/python",
      [
        "-c",
        "import zipfile,json,sys;z=zipfile.ZipFile(sys.argv[1]);print(json.dumps({'manifest':json.loads(z.read('manifest.json')),'content':z.read('project/hello.txt').decode()}))",
        path,
      ],
      { encoding: "utf8" },
    ),
  );
  expect(inspected.manifest.execution_verified).toBe(false);
  expect(inspected.manifest.task.id).toBe(id);
  expect(inspected.content).toBe("Hello from the Work fixture\n");
  expect(JSON.stringify(inspected)).not.toContain(token);
  await expect(panel.getByRole("status")).toContainText("Source archive saved");
  await page.reload();
  await page.getByLabel("Backend address").fill(base);
  await page.getByLabel("Owner credential").fill(token);
  await page.getByRole("button", { name: "Connect to dsGPT" }).click();
  await page.getByRole("button", { name: "Work", exact: true }).click();
  await expect(panel.getByLabel("Task status")).toContainText("Draft complete");
});
