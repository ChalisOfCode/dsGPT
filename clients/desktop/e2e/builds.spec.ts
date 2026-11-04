import { test, expect } from "@playwright/test";
import { createHash } from "node:crypto";

test("build evidence preserves interrupted outcomes and rejects corrupt artifact bytes", async ({
  page,
  request,
}) => {
  const base = "http://127.0.0.1:8766";
  const { token } = await (await request.get(base + "/test-credential")).json();
  const taskId = "10000000-0000-4000-8000-000000000001";
  const execution = "10000000-0000-4000-8000-000000000002";
  const artifactId = "10000000-0000-4000-8000-000000000003";
  const bytes = Buffer.from("fixture output");
  const sha = createHash("sha256").update(bytes).digest("hex");
  const task = {
    id: taskId,
    title: "Build evidence fixture",
    requirements: "Build",
    status: "blocked",
    revision: 1,
    build_target: "exe",
    execution_available: true,
    code_execution_available: false,
    blocker: "execution_interrupted",
    session: null,
  };
  const mutations: string[] = [];
  let corrupt = true;
  await page.route("**/v1/work/tasks**", async (route) => {
    const req = route.request(),
      path = new URL(req.url()).pathname;
    if (req.method() !== "GET") mutations.push(req.method() + " " + path);
    if (path.endsWith(`/artifacts/${artifactId}`)) {
      await route.fulfill({
        status: 200,
        body: corrupt ? Buffer.from("WRONG contents") : bytes,
        contentType: "application/octet-stream",
      });
      return;
    }
    const body = path.endsWith(`/executions/${execution}`)
      ? {
          status: "interrupted",
          result: {
            error: "execution_interrupted",
            help: "Outcome uncertain; not replayed",
          },
        }
      : path.endsWith("/executions")
        ? [
            {
              id: execution,
              step: 3,
              status: "interrupted",
              cleanup_pending: 1,
              snapshot_sha256: "a".repeat(64),
            },
          ]
        : path.endsWith("/artifacts")
          ? [
              {
                id: artifactId,
                execution_id: execution,
                path: "output.exe",
                bytes: bytes.length,
                sha256: sha,
              },
            ]
          : path.endsWith("/files") || path.endsWith("/steps")
            ? []
            : path.endsWith(taskId)
              ? task
              : [task];
    await route.fulfill({ json: body });
  });
  await page.goto("/");
  await page.getByLabel("Backend address").fill(base);
  await page.getByLabel("Owner credential").fill(token);
  await page.getByRole("button", { name: "Connect to dsGPT" }).click();
  await page.getByRole("button", { name: "Work", exact: true }).click();
  await page.getByRole("button", { name: "Recent tasks", exact: true }).click();
  await page.getByRole("button", { name: /Build evidence fixture/ }).click();
  await page
    .getByText("Sources and execution details", { exact: true })
    .click();
  const panel = page.getByRole("region", { name: "Build evidence" });
  await panel.getByText("Build details", { exact: true }).click();
  await expect(panel).toContainText("Isolated runner unavailable");
  await panel
    .getByText("Step 3 · interrupted · cleanup pending", { exact: true })
    .click();
  await panel.getByRole("button", { name: "Read receipt and logs" }).click();
  await expect(panel.locator("pre")).toContainText(
    "Outcome uncertain; not replayed",
  );
  await panel.getByText("output.exe ·", { exact: false }).click();
  await panel.getByRole("button", { name: "Save artifact…" }).click();
  await expect(panel.getByRole("alert")).toContainText(
    "Artifact integrity check failed",
  );
  corrupt = false;
  const download = page.waitForEvent("download");
  await panel.getByRole("button", { name: "Save artifact…" }).click();
  expect((await download).suggestedFilename()).toBe("dsGPT-artifact.exe");
  expect(mutations).toEqual([]);
});

test("private Work source files are imported only when the task is created", async ({
  page,
  request,
}) => {
  const base = "http://127.0.0.1:8766";
  const { token } = await (await request.get(base + "/test-credential")).json();
  const headers = { Authorization: `Bearer ${token}` };
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
    .fill("Private initial source");
  await panel
    .getByLabel("Work prompt", { exact: true })
    .fill("Review supplied source without executing it");
  const chooser = page.waitForEvent("filechooser");
  await panel.getByRole("button", { name: "Attach text/code file…" }).click();
  await (
    await chooser
  ).setFiles({
    name: "seed.py",
    mimeType: "text/plain",
    buffer: Buffer.from("print('private input')\n"),
  });
  await expect(panel.getByText("seed.py ·", { exact: false })).toBeVisible();
  await panel.getByLabel("Choose Work document or source ZIP").setInputFiles({
    name: "project.zip",
    mimeType: "application/zip",
    buffer: Buffer.from(
      "UEsDBBQAAAAIAJBiVF2ipzzIHgAAABwAAAANAAAAc3JjL25lc3RlZC5weSsoyswr0VCP8gyIDwjyDHMMcY33D3L28HRR1+QCAFBLAQIUAxQAAAAIAJBiVF2ipzzIHgAAABwAAAANAAAAAAAAAAAAAACAAQAAAABzcmMvbmVzdGVkLnB5UEsFBgAAAAABAAEAOwAAAEkAAAAAAA==",
      "base64",
    ),
  });
  await expect(
    panel.getByText("project.zip ·", { exact: false }),
  ).toBeVisible();
  await panel
    .getByLabel("Public search query (optional)")
    .fill("Public Python documentation");
  await panel
    .getByLabel("Follow public source links", { exact: false })
    .check();
  const before = await (
    await request.get(base + "/v1/work/tasks", { headers })
  ).json();
  expect(
    before.filter(
      (t: { title: string }) => t.title === "Private initial source",
    ),
  ).toHaveLength(0);
  await panel.getByRole("button", { name: "Send Work prompt" }).click();
  await expect(panel.getByLabel("Task status")).toContainText("draft");
  await expect(panel.getByText("seed.py ·", { exact: false })).toBeVisible();
  const rows = await (
    await request.get(base + "/v1/work/tasks", { headers })
  ).json();
  const task = rows.find(
    (t: { title: string }) => t.title === "Private initial source",
  );
  const executions = await (
    await request.get(`${base}/v1/work/tasks/${task.id}/executions`, {
      headers,
    })
  ).json();
  expect(executions).toEqual([]);
  expect(task.public_research.public_query).toBe("Public Python documentation");
  expect(task.public_research.follow_links).toBe(true);
  expect(task.public_research.status).toBe("pending");
  const imported = await (
    await request.get(`${base}/v1/work/tasks/${task.id}/files`, { headers })
  ).json();
  expect(imported.map((f: { path: string }) => f.path)).toContain(
    "src/nested.py",
  );
});
