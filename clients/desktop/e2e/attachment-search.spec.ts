import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { randomUUID } from "node:crypto";

test("saved DOCX search opens original, respects hidden scope and removes results", async ({
  page,
  request,
}) => {
  const base = "http://127.0.0.1:8766";
  const { token } = await (await request.get(base + "/test-credential")).json();
  const headers = { Authorization: `Bearer ${token}` };
  const sample = JSON.parse(
    await readFile("../../tests/fixtures/docx-sample.json", "utf8"),
  );
  const chatResponse = await request.post(base + "/v1/conversations", {
    headers,
    data: { title: "Attachment search provenance" },
  });
  expect(chatResponse.ok()).toBe(true);
  const chat = (await chatResponse.json()).id;
  const accepted = await request.post(
    `${base}/v1/conversations/${chat}/messages`,
    {
      headers,
      data: {
        request_id: randomUUID(),
        content: "Read attachment",
        model_id: "test-na",
        attachments: [
          { name: sample.name, original_base64: sample.original_base64 },
        ],
      },
    },
  );
  expect(accepted.status()).toBe(202);
  const run = await accepted.json();
  await expect
    .poll(
      async () =>
        (
          await (
            await request.get(`${base}/v1/runs/${run.id}`, { headers })
          ).json()
        ).status,
    )
    .toBe("completed");
  await page.goto("/");
  await page.getByLabel("Backend address").fill(base);
  await page.getByLabel("Owner credential").fill(token);
  await page.getByRole("button", { name: "Connect to dsGPT" }).click();
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: "History and retrieval →" }).click();
  const panel = page.getByRole("region", { name: "History and retrieval" });
  await panel.getByLabel("Retrieval scope").selectOption("attachments");
  await expect(panel.getByLabel("Search method")).toBeEnabled();
  await panel
    .getByLabel("Search private content", { exact: true })
    .fill("DOCX_PRIVATE_JADE");
  const search = panel.getByRole("button", {
    name: "Search private content",
    exact: true,
  });
  await search.click();
  const result = panel
    .locator("article")
    .filter({ hasText: "Attachment search provenance" });
  await expect(result).toContainText("DOCX_PRIVATE_JADE");
  await result
    .getByRole("button", { name: "Attached file: sample.docx" })
    .click();
  await expect(result.getByLabel("Attached file viewer")).toContainText(
    "main-body text only",
  );
  const messages = await (
    await request.get(`${base}/v1/conversations/${chat}/messages`, { headers })
  ).json();
  const file = messages[0].attachments[0];
  expect(
    (
      await (
        await request.get(
          `${base}/v1/conversations/${chat}/attachments/${file.id}/download`,
          { headers },
        )
      ).body()
    ).equals(Buffer.from(sample.original_base64, "base64")),
  ).toBe(true);
  await panel.getByLabel("Search hidden chats only").check();
  await search.click();
  await expect(result).toHaveCount(0);
  await panel.getByLabel("Search hidden chats only").uncheck();
  await search.click();
  await result
    .getByRole("button", { name: "Attached file: sample.docx" })
    .click();
  await result.getByRole("button", { name: "Remove stored file…" }).click();
  await result.getByRole("button", { name: "Confirm file removal" }).click();
  await expect(result).toHaveCount(0);
  await search.click();
  await expect(result).toHaveCount(0);
});
