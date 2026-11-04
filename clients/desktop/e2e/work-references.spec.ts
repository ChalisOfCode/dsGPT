import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";

test("Work retains reference snapshots, retries a failed read, displays plain text and exports provenance", async ({
  page,
  request,
}, testInfo) => {
  test.setTimeout(60000);
  const base = "http://127.0.0.1:8766";
  const { token } = await (await request.get(base + "/test-credential")).json();
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
    .fill("Reference integration");
  await panel
    .getByLabel("Work prompt", { exact: true })
    .fill(
      "Read S1 and draft evidence.txt with the documented codename and URL.",
    );
  const urls =
    "https://example.org/reference#section\nhttps://example.org/reference\nhttps://example.org/retry";
  await panel.getByLabel("Public reference URLs (optional)").fill(urls);
  const legacyCapability = async (route: import("@playwright/test").Route) => {
    const response = await route.fetch();
    const body = await response.json();
    body.work.reference_sources = false;
    await route.fulfill({ response, json: body });
  };
  await page.route("**/v1/capabilities", legacyCapability);
  await panel
    .getByRole("button", { name: "Send Work prompt", exact: true })
    .click();
  await expect(panel.getByRole("alert")).toContainText("backend 0.3.0.dev9");
  await expect(
    panel.getByLabel("Public reference URLs (optional)"),
  ).toHaveValue(urls);
  await page.unroute("**/v1/capabilities", legacyCapability);
  await panel
    .getByRole("button", { name: "Send Work prompt", exact: true })
    .click();
  await expect(panel.getByLabel("Task status")).toContainText("draft");
  await panel
    .getByText("Sources and execution details", { exact: true })
    .click();
  const sources = panel.getByRole("region", {
    name: "Work reference sources",
    exact: true,
  });
  await expect(sources.locator("summary")).toHaveCount(2);
  await expect(
    sources.getByText("S1 · pending", { exact: false }),
  ).toBeVisible();
  await panel.getByRole("button", { name: "Start drafting" }).click();
  await expect(panel.getByLabel("Task status")).toContainText("blocked", {
    timeout: 15000,
  });
  await expect(
    sources.locator("summary").filter({ hasText: "S2 · failed" }),
  ).toBeVisible();
  await panel.getByText("Task update options", { exact: true }).click();
  await panel.getByLabel("Retry failed sources on start or resume").check();
  await panel.getByRole("button", { name: "Save task update" }).click();
  await expect(
    sources.locator("summary").filter({ hasText: "S2 · pending" }),
  ).toBeVisible();
  await panel.getByRole("button", { name: "Resume", exact: true }).click();
  await expect(panel.getByLabel("Task status")).toContainText(
    "Draft complete",
    { timeout: 20000 },
  );
  await sources
    .locator("summary")
    .filter({ hasText: "S1 · retrieved" })
    .click();
  await expect(sources.locator("img")).toHaveCount(0);
  await expect(sources).toContainText(
    "<img src=x onerror=alert(1)> source title",
  );
  await expect(sources).toContainText("Extracted text SHA-256:");
  await sources
    .getByRole("button", { name: "Read saved S1", exact: true })
    .click();
  const saved = sources.getByRole("region", { name: "Saved source text" });
  await expect(saved.locator("pre")).toContainText("COBALT");
  await saved.getByRole("button", { name: "Next excerpt" }).click();
  await expect(saved.locator("pre")).not.toContainText("COBALT");
  await expect(saved.locator("pre")).toContainText("é");
  await saved.getByRole("button", { name: "From beginning" }).click();
  await expect(saved.locator("pre")).toContainText("COBALT");
  await sources
    .getByRole("heading", { name: "Reference sources", exact: true })
    .scrollIntoViewIfNeeded();
  await page.screenshot({
    path: "../../../runtime/native-stage3j/work-references-preview.png",
    fullPage: true,
  });
  const downloadPromise = page.waitForEvent("download");
  await panel.getByRole("button", { name: "Save source ZIP…" }).click();
  const downloaded = await downloadPromise;
  const file = testInfo.outputPath("references.zip");
  await downloaded.saveAs(file);
  const archive = JSON.parse(
    execFileSync(
      process.env.DSGPT_TEST_PYTHON || "../../../.venv/bin/python",
      [
        "-c",
        "import zipfile,json,sys;z=zipfile.ZipFile(sys.argv[1]);print(json.dumps({'sources':json.loads(z.read('sources.json')),'manifest':json.loads(z.read('manifest.json')),'file':z.read('project/evidence.txt').decode()}))",
        file,
      ],
      { encoding: "utf8" },
    ),
  );
  expect(archive.sources.sources).toHaveLength(2);
  expect(archive.sources.sources[0].url).toBe("https://example.org/reference");
  expect(archive.sources.sources[0].text).toContain("COBALT");
  expect(archive.sources.sources[0].text_sha256).toMatch(/^[0-9a-f]{64}$/);
  expect(archive.manifest.execution_verified).toBe(false);
  expect(archive.manifest.reference_sources).toBe(2);
  expect(archive.file).toContain("COBALT");
  expect(JSON.stringify(archive)).not.toContain(token);
  await page.reload();
  await page.getByLabel("Backend address").fill(base);
  await page.getByLabel("Owner credential").fill(token);
  await page.getByRole("button", { name: "Connect to dsGPT" }).click();
  await page.getByRole("button", { name: "Work", exact: true }).click();
  await page.getByText("Sources and execution details", {exact:true}).click();
  await expect(sources.locator("summary")).toHaveCount(2);
  await expect(
    sources.locator("summary").filter({ hasText: "S2 · retrieved" }),
  ).toBeVisible();
});
