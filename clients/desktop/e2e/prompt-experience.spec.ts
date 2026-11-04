import { test, expect } from "@playwright/test";

async function connect(page, request) {
  const { token } = await (
    await request.get("http://127.0.0.1:8766/test-credential")
  ).json();
  await page.goto("/");
  await page.getByLabel("Backend address").fill("http://127.0.0.1:8766");
  await page.getByLabel("Owner credential").fill(token);
  await page.getByRole("button", { name: "Connect to dsGPT" }).click();
}

test("Work starts from one prompt with shared model and supported effort, advanced form stays closed", async ({
  page,
  request,
}) => {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });
  await page.route("**/v1/models/*/thinking", (route) =>
    route.fulfill({
      json: {
        choices: [
          { id: "auto", label: "Model default" },
          { id: "off", label: "Instant" },
          { id: "on", label: "Thinking" },
        ],
        output_tokens: 4096,
      },
    }),
  );
  await connect(page, request);
  await page.getByRole("tab", { name: "Work", exact: true }).click();
  await expect(page.getByLabel("Output target")).toBeHidden();
  await expect(page.getByLabel("Model", { exact: true })).toBeVisible();
  await page.getByLabel("Thinking effort").selectOption("on");
  await page
    .getByLabel("Work prompt", { exact: true })
    .fill("Create a useful note");
  const sent = page.waitForRequest(
    (r) =>
      r.method() === "POST" && new URL(r.url()).pathname === "/v1/work/tasks",
  );
  await page.getByRole("button", { name: "Send Work prompt" }).click();
  const body = (await sent).postDataJSON();
  expect(body).toMatchObject({
    title: "Create a useful note",
    requirements: "Create a useful note",
    start: true,
    reasoning_effort: "on",
    web_mode: "auto",
    build_target: "auto",
  });
  await expect(page.getByLabel("Task status")).not.toContainText("draft");
  await expect(
    page.getByRole("heading", { name: "Create a useful note" }),
  ).toBeVisible();
});

test("dictation updates the prompt before stopping and preserves edits against delayed results", async ({
  page,
  request,
}) => {
  await page.addInitScript(() => {
    const tracks = [{ stop() {} }];
    Object.defineProperty(navigator, "mediaDevices", {
      value: { getUserMedia: async () => ({ getTracks: () => tracks }) },
    });
    window.AudioContext = class {
      sampleRate = 16000;
      destination = {};
      async resume() {}
      async close() {}
      createMediaStreamSource() {
        return { connect() {} };
      }
      createScriptProcessor() {
        const node = { connect() {}, disconnect() {}, onaudioprocess: null };
        window.__audioNode = node;
        return node;
      }
    } as any;
  });
  let updates = 0;
  await page.route("**/v1/dictation**", async (route) => {
    if (route.request().method() === "DELETE")
      return route.fulfill({ json: { stopped: true } });
    if (new URL(route.request().url()).pathname === "/v1/dictation")
      return route.fulfill({
        json: { id: "10000000-0000-4000-8000-000000000001" },
      });
    const data = route.request().postDataJSON();
    updates++;
    return route.fulfill({
      json: {
        text: data.final
          ? "these are my spoken words."
          : updates === 1
            ? "these are"
            : "these are my spoken words",
        final: !!data.final,
      },
    });
  });
  await connect(page, request);
  const prompt = page.getByLabel("Message", { exact: true });
  await prompt.fill("My draft:");
  await page
    .getByRole("button", { name: "Live dictation", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Stop dictation", exact: true }),
  ).toBeVisible();
  const audio = () =>
    page.evaluate(() =>
      window.__audioNode.onaudioprocess({
        inputBuffer: { getChannelData: () => new Float32Array(4096) },
      }),
    );
  await audio();
  await expect(prompt).toHaveValue("My draft: these are");
  await expect(page.getByRole("button", { name: "Send ↑" })).toBeDisabled();
  await audio();
  await expect(prompt).toHaveValue("My draft: these are my spoken words");
  await page
    .getByRole("button", { name: "Stop dictation", exact: true })
    .click();
  await expect(prompt).toHaveValue("My draft: these are my spoken words.");
  await page
    .getByRole("button", { name: "Live dictation", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Stop dictation", exact: true }),
  ).toBeVisible();
  await prompt.fill("My manual correction");
  await expect(
    page.getByRole("button", { name: "Live dictation", exact: true }),
  ).toBeVisible();
  await audio();
  await expect(prompt).toHaveValue("My manual correction");
});
