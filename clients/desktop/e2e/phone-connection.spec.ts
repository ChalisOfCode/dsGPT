import { test, expect } from "@playwright/test";

test("automatic phone setup shows progress, prevents duplicate starts, retries and verifies success", async ({
  page,
  request,
}) => {
  const base = "http://127.0.0.1:8766";
  const { token } = await (await request.get(base + "/test-credential")).json();
  let starts = 0;
  let progress = { status: "idle", phase: "", message: "Ready to connect" };
  await page.exposeFunction(
    "nativeTestInvoke",
    async (command: string, args: any) => {
      if (command === "restore_connection") return "http://127.0.0.1:18765";
      if (command === "phone_setup_status") return progress;
      if (command === "start_phone_setup") {
        starts++;
        progress = {
          status: "running",
          phase: "https",
          message: "Preparing your private HTTPS address automatically…",
        };
        return progress;
      }
      if (command === "api_request") {
        const response = await request.fetch(base + args.path, {
          method: args.method,
          headers: { Authorization: `Bearer ${token}` },
          ...(args.body === null ? {} : { data: args.body }),
        });
        if (!response.ok()) throw new Error(`Backend ${response.status()}`);
        return response.json();
      }
      throw new Error(`Unexpected native command: ${command}`);
    },
  );
  await page.addInitScript(() => {
    (window as any).isTauri = true;
    (window as any).__TAURI_INTERNALS__ = {
      invoke: (command: string, args: any) =>
        (window as any).nativeTestInvoke(command, args),
    };
  });
  await page.goto("/");
  await page
    .getByRole("button", { name: "Connect Pixel automatically", exact: true })
    .click();
  const dialog = page.getByRole("dialog", { name: "Connect your Pixel" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("status")).toContainText(
    "Preparing your private HTTPS address automatically",
  );
  await expect(
    dialog.getByRole("button", { name: "Connect automatically", exact: true }),
  ).toBeDisabled();
  expect(starts).toBe(1);
  await page.screenshot({ path: "../../reports/desktop-phone-progress.png" });
  await dialog.getByRole("button", { name: "Continue in background" }).click();
  await page.getByRole("tab", { name: "Work", exact: true }).click();
  await page
    .getByRole("button", { name: "Connect Pixel automatically", exact: true })
    .click();
  expect(starts).toBe(1);
  progress = {
    status: "needs_attention",
    phase: "phone",
    message: "Pixel not reachable. Turn on Wireless debugging and retry.",
  };
  await expect(dialog.getByRole("status")).toContainText("Pixel not reachable");
  await dialog
    .getByRole("button", { name: "Retry automatic connection" })
    .click();
  expect(starts).toBe(2);
  progress = {
    status: "succeeded",
    phase: "done",
    message: "Pixel connected. Open dsGPT Mobile and chat.",
  };
  await expect(dialog.getByRole("status")).toContainText("Pixel connected");
  await expect(
    dialog.getByRole("button", { name: "Check connection again" }),
  ).toBeEnabled();
  await expect(dialog.locator("input")).toHaveCount(0);
  await dialog.press("Escape");
  await expect(
    page.getByRole("button", {
      name: "Connect Pixel automatically",
      exact: true,
    }),
  ).toBeFocused();
});
