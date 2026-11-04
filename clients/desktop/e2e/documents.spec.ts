import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";
test("DOCX preview, exact original download and removal stay conversation scoped", async ({
  page,
  request,
}) => {
  const base = "http://127.0.0.1:8766";
  const { token } = await (await request.get(base + "/test-credential")).json();
  const sample = JSON.parse(
    await readFile("../../tests/fixtures/docx-sample.json", "utf8"),
  );
  await page.goto("/");
  await page.getByLabel("Backend address").fill(base);
  await page.getByLabel("Owner credential").fill(token);
  await page.getByRole("button", { name: "Connect to dsGPT" }).click();
  await page
    .getByLabel("Choose DOCX document")
    .setInputFiles({
      name: sample.name,
      mimeType:
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      buffer: Buffer.from(sample.original_base64, "base64"),
    });
  await page.getByText("Review document text and limitations").click();
  await expect(
    page.getByText("DOCX_PRIVATE_JADE", { exact: false }).first(),
  ).toBeVisible();
  await expect(page.getByLabel("Research this message")).toBeDisabled();
  await page
    .getByLabel("Message", { exact: true })
    .fill("Summarize the attached document");
  const accepted = page.waitForResponse(
    (r) => r.url().endsWith("/messages") && r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Send ↑" }).click();
  const run = await (await accepted).json();
  await page
    .getByRole("button", { name: "Attached file: sample.docx" })
    .click();
  await expect(page.getByLabel("Attached file viewer")).toContainText(
    "main-body text only",
  );
  const messages = await (
    await request.get(
      `${base}/v1/conversations/${run.conversation_id}/messages`,
      { headers: { Authorization: `Bearer ${token}` } },
    )
  ).json();
  const attachment = messages.find((m: any) => m.attachments.length)
    ?.attachments[0];
  const download = await request.get(
    `${base}/v1/conversations/${run.conversation_id}/attachments/${attachment.id}/download`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  expect(
    (await download.body()).equals(
      Buffer.from(sample.original_base64, "base64"),
    ),
  ).toBe(true);
  await expect
    .poll(
      async () =>
        (
          await (
            await request.get(`${base}/v1/runs/${run.id}`, {
              headers: { Authorization: `Bearer ${token}` },
            })
          ).json()
        ).status,
      { timeout: 12_000 },
    )
    .toBe("completed");
  await page.getByRole("button", { name: "Remove stored file…" }).click();
  await page.getByRole("button", { name: "Confirm file removal" }).click();
  await expect(page.getByLabel("Attached file viewer")).toContainText(
    "removed",
  );
});
