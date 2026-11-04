import { test, expect } from "@playwright/test";

test("connected devices show scopes and reconcile a lost revocation response", async ({
  page,
  request,
}) => {
  const base = "http://127.0.0.1:8766";
  const { token } = await (await request.get(base + "/test-credential")).json();
  const headers = { Authorization: `Bearer ${token}` };
  async function pair(name: string, models: boolean) {
    const { code } = await (
      await request.post(base + "/v1/pairings", {
        headers,
        data: {
          scopes: [
            "chat",
            "work",
            "diagnostics",
            ...(models ? ["models"] : []),
          ],
        },
      })
    ).json();
    return (
      await request.post(base + "/v1/pairings/redeem", { data: { code, name } })
    ).json();
  }
  const old = await pair("<b>Old phone access</b>", false),
    current = await pair("New phone access", true);
  const oldHeaders = { Authorization: `Bearer ${old.token}` },
    currentHeaders = { Authorization: `Bearer ${current.token}` };
  // Re-pairing alone leaves the earlier credential valid.
  expect(
    (await request.get(base + "/v1/device", { headers: oldHeaders })).status(),
  ).toBe(200);
  let deletes = 0;
  await page.route(`${base}/v1/devices/${old.device_id}`, async (route) => {
    if (route.request().method() !== "DELETE") {
      await route.continue();
      return;
    }
    deletes++;
    await route.fetch();
    await route.fulfill({ status: 503, json: {} });
  });
  async function open(credential: string) {
    await page.getByLabel("Backend address").fill(base);
    await page.getByLabel("Owner credential").fill(credential);
    await page.getByRole("button", { name: "Connect to dsGPT" }).click();
    await page.getByRole("button", { name: "Settings", exact: false }).click();
    await page
      .getByRole("button", {
        name: "Pair a phone / Connected Devices",
        exact: false,
      })
      .click();
  }
  await page.goto("/");
  await open(token);
  const panel = page.getByRole("region", {
    name: "Connected devices workspace",
  });
  const oldRow = panel.getByRole("article", {
    name: `Device ${old.device_id}`,
    exact: true,
  });
  const newRow = panel.getByRole("article", {
    name: `Device ${current.device_id}`,
    exact: true,
  });
  await expect(oldRow).toContainText("Access active");
  await expect(oldRow).not.toContainText("Model management");
  await expect(newRow).toContainText("Model management");
  await expect(panel.locator("article b")).toHaveCount(0);
  await expect(
    panel.getByRole("button", { name: "Connect Pixel automatically" }),
  ).toBeVisible();
  await expect(
    panel.getByRole("button", { name: "Generate pairing code" }),
  ).toBeHidden();
  await panel.getByText("Manual connection", { exact: true }).click();
  await expect(page.getByLabel("Allow model management")).not.toBeChecked();
  await expect(
    panel.getByRole("article", { name: "This connection", exact: true }),
  ).not.toContainText(token);
  const before = await (
    await request.get(base + "/v1/devices", { headers })
  ).json();
  expect(JSON.stringify(before)).not.toContain("token_hash");
  expect(JSON.stringify(before)).not.toContain(old.token);
  await oldRow.getByRole("button", { name: "Revoke access…" }).click();
  await panel.getByRole("button", { name: "Keep access" }).click();
  expect(deletes).toBe(0);
  expect(
    (await request.get(base + "/v1/device", { headers: oldHeaders })).status(),
  ).toBe(200);
  await oldRow.getByRole("button", { name: "Revoke access…" }).click();
  await panel.getByRole("button", { name: "Confirm revocation" }).click();
  await expect(panel.getByRole("alert")).toContainText("503");
  await expect(oldRow).toContainText("Access revoked");
  await expect(
    oldRow.getByRole("button", { name: "Revoke access…" }),
  ).toHaveCount(0);
  expect(deletes).toBe(1);
  expect(
    (await request.get(base + "/v1/device", { headers: oldHeaders })).status(),
  ).toBe(401);
  expect(
    (
      await request.get(base + "/v1/device", { headers: currentHeaders })
    ).status(),
  ).toBe(200);
  await panel.getByRole("button", { name: "Refresh devices" }).click();
  await page.screenshot({
    path: "../../../runtime/native-stage3i/devices-preview.png",
    fullPage: true,
  });
  await page.reload();
  await open(token);
  await expect(oldRow).toContainText("Access revoked");
  await page.reload();
  await open(current.token);
  await expect(
    panel.getByText("This credential can view its own permissions.", {
      exact: false,
    }),
  ).toBeVisible();
  await expect(
    panel.getByRole("button", { name: "Generate pairing code" }),
  ).toHaveCount(0);
  await expect(
    panel.getByRole("button", { name: "Revoke access…" }),
  ).toHaveCount(0);
  await expect(
    panel.getByRole("heading", { name: "<b>Old phone access</b>" }),
  ).toHaveCount(0);
  await expect(
    panel.getByRole("article", { name: "This connection", exact: true }),
  ).toContainText(current.device_id);
});
