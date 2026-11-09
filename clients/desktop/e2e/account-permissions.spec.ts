import { test, expect } from "@playwright/test";

test("account permission UI requires review and reconciles a lost revocation response", async ({
  page,
  request,
}) => {
  // UI-only fixture: does not establish protected storage or website sign-in.
  const base = "http://127.0.0.1:8766";
  const { token } = await (await request.get(base + "/test-credential")).json();
  const session = "00000000-0000-4000-8000-000000000001";
  const task = "00000000-0000-4000-8000-000000000002";
  const device = "00000000-0000-4000-8000-000000000003";
  const grant = "00000000-0000-4000-8000-000000000004";
  let grants: unknown[] = [],
    creates = 0,
    deletes = 0;
  await page.route(base + "/v1/work/tasks?limit=20", (route) =>
    route.fulfill({
      json: [
        {
          id: task,
          title: "Review fixture",
          requirements: "Private scoped task",
          revision: 7,
        },
      ],
    }),
  );
  await page.route(base + "/v1/devices?limit=200", (route) =>
    route.fulfill({
      json: [
        { id: device, name: "Fixture phone", scopes: ["work"], revoked: 0 },
      ],
    }),
  );
  await page.route(base + "/v1/account-sessions**", async (route) => {
    const url = route.request().url(),
      method = route.request().method();
    if (method === "POST") {
      creates++;
      expect(route.request().postDataJSON()).toEqual({
        task_id: task,
        task_revision: 7,
        device_id: device,
        lifetime_seconds: 900,
      });
      grants = [
        {
          id: grant,
          task_id: task,
          task_revision: 7,
          device_id: device,
          expires_at: Date.now() / 1000 + 900,
        },
      ];
      await route.fulfill({ status: 201, json: grants[0] });
    } else if (method === "DELETE") {
      deletes++;
      grants = [];
      await route.fulfill({
        status: 503,
        json: { detail: "Lost response after deletion" },
      });
    } else if (url.endsWith("/grants")) await route.fulfill({ json: grants });
    else
      await route.fulfill({
        json: {
          available: true,
          sessions: [
            {
              id: session,
              label: "<b>Fixture account</b>",
              origin: "https://example.org",
              read_path: "/account",
            },
          ],
        },
      });
  });
  await page.goto("/");
  await page.getByLabel("Backend address").fill(base);
  await page.getByLabel("Owner credential").fill(token);
  await page.getByRole("button", { name: "Connect to dsGPT" }).click();
  await page.getByRole("button", { name: "Settings", exact: false }).click();
  const panel = page.getByRole("region", {
    name: "Account permissions",
    exact: true,
  });
  await panel
    .getByLabel("Account session", { exact: true })
    .selectOption(session);
  await panel.getByLabel("Account access task").selectOption(task);
  await panel.getByLabel("Account access device").selectOption(device);
  const approve = panel.getByRole("button", {
    name: "Grant 15-minute read access",
  });
  await expect(approve).toBeDisabled();
  await panel.getByRole("checkbox").check();
  await approve.click();
  await expect(panel.getByRole("article")).toHaveCount(1);
  await expect(approve).toBeDisabled();
  expect(creates).toBe(1);
  await panel.getByRole("button", { name: "Revoke read grant" }).click();
  await expect(panel.getByText("No grants for this account.")).toBeVisible();
  await expect(panel.getByRole("status")).toContainText("no automatic retry");
  expect(deletes).toBe(1);
  await expect(panel.locator("b")).toHaveCount(0);
});
