import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";

test("private attachments survive a lost acceptance, show plain text and cannot be resurrected", async ({
  page,
  request,
}) => {
  const base = "http://127.0.0.1:8766",
    { token } = await (await request.get(base + "/test-credential")).json();
  const headers = { Authorization: `Bearer ${token}` };
  const submitted: Record<string, unknown>[] = [];
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().endsWith("/messages"))
      submitted.push(r.postDataJSON());
  });
  async function connect() {
    await page.getByLabel("Backend address").fill(base);
    await page.getByLabel("Owner credential").fill(token);
    await page.getByRole("button", { name: "Connect to dsGPT" }).click();
  }
  await page.goto("/");
  await connect();
  const text =
    "\ufeffATTACHMENT_MARKER_VIOLET\r\n<svg onload=alert(1)>\n" +
    "é".repeat(2000);
  const file = {
    name: "notes.txt",
    mimeType: "text/plain",
    buffer: Buffer.from(text),
  };
  await page
    .getByLabel("Attach text files", { exact: true })
    .setInputFiles(file);
  await expect(
    page.getByRole("button", { name: "Remove selected notes.txt" }),
  ).toBeVisible();
  await expect(page.getByLabel("Research this message")).toBeDisabled();
  await page.getByLabel("Message", { exact: true }).fill("Read private notes");
  await page.route(base + "/v1/capabilities", async (route) => {
    const response = await route.fetch();
    const json = await response.json();
    delete json.attachments;
    await route.fulfill({ response, json });
  });
  await page.getByRole("button", { name: "Send ↑" }).click();
  await expect(page.getByRole("alert")).toContainText("0.3.0.dev11");
  expect(submitted).toHaveLength(0);
  await page.unroute(base + "/v1/capabilities");
  let lost = false;
  await page.route(/\/v1\/conversations\/[^/]+\/messages$/, async (route) => {
    if (route.request().method() !== "POST" || lost) return route.continue();
    lost = true;
    await route.fetch();
    await route.fulfill({ status: 503, json: {} });
  });
  await page.getByRole("button", { name: "Send ↑" }).click();
  await expect(page.locator("article.assistant")).toContainText("VIOLET");
  await expect(page.getByRole("alert")).toContainText("503");
  await expect(
    page.getByRole("button", { name: "Remove selected notes.txt" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Send ↑" }).click();
  await expect(
    page.getByRole("button", { name: "Remove selected notes.txt" }),
  ).toHaveCount(0);
  expect(submitted).toHaveLength(2);
  expect(submitted[1]).toEqual(submitted[0]);
  await expect(page.locator("article.user")).toHaveCount(1);
  const messagesURL = (
    await request.get(base + "/v1/conversations", { headers })
  ).ok();
  expect(messagesURL).toBe(true);
  const chat = (
    await (await request.get(base + "/v1/conversations", { headers })).json()
  ).find((x: { title: string }) => x.title === "Read private notes");
  const messages = await (
    await request.get(`${base}/v1/conversations/${chat.id}/messages`, {
      headers,
    })
  ).json();
  const id = messages[0].attachments[0].id;
  await page
    .getByRole("button", { name: "Attached file: notes.txt", exact: true })
    .click();
  const viewer = page.getByRole("region", { name: "Attached file viewer" });
  await expect(viewer).toContainText("ATTACHMENT_MARKER_VIOLET");
  await expect(viewer.locator("svg")).toHaveCount(0);
  await viewer.getByRole("button", { name: "Next excerpt" }).click();
  await expect(viewer).toContainText("of 2049");
  const downloadPromise = page.waitForEvent("download");
  await viewer.getByRole("button", { name: "Save attached file…" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe("notes.txt");
  expect(await readFile((await download.path())!)).toEqual(Buffer.from(text));
  await page.screenshot({
    path: "../../../runtime/native-stage3l/attachments-preview.png",
    fullPage: true,
  });
  await page.reload();
  await connect();
  await page
    .getByRole("button", { name: "Read private notes", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Attached file: notes.txt", exact: true })
    .click();
  await expect(viewer).toContainText("ATTACHMENT_MARKER_VIOLET");
  await viewer.getByRole("button", { name: "Remove stored file…" }).click();
  await viewer.getByRole("button", { name: "Keep file" }).click();
  expect(
    (
      await request.get(
        `${base}/v1/conversations/${chat.id}/attachments/${id}`,
        { headers },
      )
    ).status(),
  ).toBe(200);
  await viewer.getByRole("button", { name: "Remove stored file…" }).click();
  await viewer.getByRole("button", { name: "Confirm file removal" }).click();
  await expect(viewer).toContainText("The stored file body was removed.");
  expect(
    (
      await request.post(`${base}/v1/conversations/${chat.id}/messages`, {
        headers,
        data: submitted[0],
      })
    ).status(),
  ).toBe(202);
  expect(
    (
      await request.get(
        `${base}/v1/conversations/${chat.id}/attachments/${id}`,
        { headers },
      )
    ).status(),
  ).toBe(410);
  await page.getByRole("button", { name: "New chat" }).click();
  await page
    .getByLabel("Attach text files", { exact: true })
    .setInputFiles({
      name: "big.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("x".repeat(65537)),
    });
  await expect(page.getByRole("alert")).toContainText("64 KiB");
  await page
    .getByLabel("Attach text files", { exact: true })
    .setInputFiles({
      name: "limits.txt",
      mimeType: "text/plain",
      buffer: Buffer.from("ATTACHMENT_OVERFLOW"),
    });
  await page.getByLabel("Message", { exact: true }).fill("Explain the file");
  await page.getByRole("button", { name: "Send ↑" }).click();
  await expect(page.locator("article.assistant")).toContainText(
    "exceed the model’s context",
  );
});
