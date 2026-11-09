import { test, expect } from "@playwright/test";

// UI transport fixture only; real login and protected browser acceptance are separate.
const sid = "00000000-0000-4000-8000-000000000011";
const hid = "00000000-0000-4000-8000-000000000012";
const base = "http://127.0.0.1:8766";

test("private owner view sends input once, clears it on failure and explicitly saves or discards", async ({
  page,
  request,
}) => {
  const { token } = await (await request.get(base + "/test-credential")).json();
  let created = false,
    starts = 0,
    inputs = 0,
    saves = 0,
    discards = 0;
  const submission = "00000000-0000-4000-8000-000000000013";
  const review = "00000000-0000-4000-8000-000000000014";
  let reviewState = "idle",
    submissions = 0,
    decisions = 0,
    verifications = 0;
  let image: Buffer;
  let holdFrame = false,
    heldFrame = false;
  let releaseFrame = () => {};
  const account = {
    id: sid,
    label: "Fixture browser",
    origin: "https://example.org",
    read_path: "/login",
    browser_profile: 1,
  };
  await page.route(base + "/v1/account-sessions**", async (route) => {
    const req = route.request(),
      path = new URL(req.url()).pathname;
    if (path === "/v1/account-sessions")
      return route.fulfill({
        json: { available: true, sessions: created ? [account] : [] },
      });
    if (path === "/v1/account-sessions/browser") {
      expect(req.postDataJSON()).toEqual({
        label: account.label,
        origin: account.origin,
        read_path: account.read_path,
      });
      created = true;
      return route.fulfill({ status: 201, json: account });
    }
    if (path.endsWith("/frame")) {
      if (holdFrame) {
        heldFrame = true;
        await new Promise<void>((resolve) => {
          releaseFrame = resolve;
        });
      }
      return route.fulfill({
        body: image,
        contentType: "image/png",
        headers: {
          "cache-control": "no-store",
          "x-dsgpt-observation": hid,
          "access-control-expose-headers": "X-dsGPT-Observation",
        },
      });
    }
    if (path.endsWith("/submissions")) {
      if (req.method() === "POST") {
        expect(new URL(req.url()).searchParams.get("observation_id")).toBe(hid);
        expect(req.postDataJSON()).toEqual({ op: "key", key: "Enter" });
        submissions++;
        reviewState = "running";
        return route.fulfill({
          status: 202,
          json: { submission_id: submission },
        });
      }
      return route.fulfill({
        json: {
          state: reviewState === "verified" ? "finished" : reviewState,
          submission_id: reviewState === "idle" ? null : submission,
          review:
            reviewState === "running"
              ? { review_id: review, path: "/login" }
              : null,
          unverified:
            reviewState === "finished"
              ? [{ id: review, status: "response_received" }]
              : [],
        },
      });
    }
    if (path.endsWith("/decision")) {
      expect(path).toContain("/submissions/" + submission + "/decision");
      expect(req.postDataJSON()).toEqual({ review_id: review, approve: true });
      decisions++;
      reviewState = "finished";
      return route.fulfill({ status: 204 });
    }
    if (path.endsWith("/verification")) {
      expect(req.postDataJSON()).toEqual({
        action_id: review,
        observation_id: hid,
        applied: true,
      });
      verifications++;
      reviewState = "verified";
      return route.fulfill({ status: 204 });
    }
    if (path.endsWith("/input")) {
      inputs++;
      if (inputs === 1) {
        expect(req.postDataJSON()).toEqual({
          op: "text",
          text: "fixture-sensitive-input",
        });
        return route.fulfill({ status: 503, json: { detail: "interrupted" } });
      }
      if (inputs === 2) {
        const body = req.postDataJSON();
        expect(body.op).toBe("click");
        // Browser pointer coordinates round to CSS pixels before scaling.
        expect(Math.abs(body.x - 512)).toBeLessThanOrEqual(1);
        expect(Math.abs(body.y - 384)).toBeLessThanOrEqual(1);
      } else expect(req.postDataJSON()).toEqual({ op: "key", key: "Tab" });
      return route.fulfill({ status: 204 });
    }
    if (path.endsWith("/save")) {
      saves++;
      return route.fulfill({ status: 204 });
    }
    if (req.method() === "DELETE") {
      discards++;
      return route.fulfill({ status: 204 });
    }
    if (path.endsWith("/browser")) {
      starts++;
      return route.fulfill({
        json: { handoff_id: hid, lifetime_seconds: 300 },
      });
    }
    throw new Error("Unexpected account request");
  });
  await page.goto("/");
  image = Buffer.from(
    await page.evaluate(() => {
      const canvas = document.createElement("canvas");
      canvas.width = 1024;
      canvas.height = 768;
      canvas
        .getContext("2d")!
        .fillText("Controlled private page fixture", 30, 30);
      return canvas.toDataURL("image/png").split(",")[1];
    }),
    "base64",
  );
  await page.getByLabel("Backend address").fill(base);
  await page.getByLabel("Owner credential").fill(token);
  await page.getByRole("button", { name: "Connect to dsGPT" }).click();
  await page.getByRole("button", { name: "Settings", exact: false }).click();
  const panel = page.getByRole("region", {
    name: "Account permissions",
    exact: true,
  });
  await panel.getByLabel("Account label").fill(account.label);
  await panel.getByLabel("Website origin").fill(account.origin);
  await panel.getByLabel("Starting page").fill(account.read_path);
  await panel.getByRole("button", { name: "Create browser account" }).click();
  await panel.getByLabel("Account session", { exact: true }).selectOption(sid);
  await expect(
    panel.getByText("Work access for browser profiles is not available yet."),
  ).toBeVisible();
  await panel.getByRole("button", { name: "Open private browser" }).click();
  const dialog = page.getByRole("dialog", { name: "Private account browser" });
  const input = dialog.getByLabel("Text for focused website field");
  await expect(input).toBeEnabled();
  await input.fill("fixture-sensitive-input");
  await dialog.getByRole("button", { name: "Send text once" }).click();
  await expect(dialog.getByRole("alert")).toContainText(
    "Input was not retried",
  );
  await expect(input).toHaveValue("");
  await expect(input).toBeDisabled();
  expect(inputs).toBe(1);
  await dialog.getByRole("button", { name: "Refresh private page" }).click();
  await expect(input).toBeEnabled();
  const frame = dialog.getByRole("button", { name: "Click private page" });
  await frame.click();
  await expect(input).toBeEnabled();
  await dialog.getByRole("button", { name: "Send Tab", exact: true }).click();
  await expect(input).toBeEnabled();
  expect(inputs).toBe(3);
  const optIn = dialog.getByRole("checkbox", {
    name: "Review the next page click or Enter for a form submission",
  });
  await optIn.check();
  await dialog.getByRole("button", { name: "Send Enter", exact: true }).click();
  await expect(
    dialog.getByText("Send this form once to https://example.org/login?"),
  ).toBeVisible();
  expect(submissions).toBe(1);
  expect(decisions).toBe(0);
  await expect(frame).toBeDisabled();
  await dialog.getByRole("button", { name: "Approve form submission" }).click();
  await expect(
    dialog.getByText(
      "The website responded, but its outcome has not been verified.",
      { exact: false },
    ),
  ).toBeVisible();
  await expect(optIn).toBeDisabled();
  expect(decisions).toBe(1);
  await dialog.getByRole("button", { name: "I checked: applied" }).click();
  await expect(optIn).toBeEnabled();
  expect(verifications).toBe(1);
  expect(submissions).toBe(1);
  await dialog.getByRole("button", { name: "Save profile and close" }).click();
  await expect(dialog).not.toBeVisible();
  expect(saves).toBe(1);
  await panel.getByRole("button", { name: "Open private browser" }).click();
  await expect(input).toBeEnabled();
  await dialog.getByRole("button", { name: "Discard and close" }).click();
  await expect(dialog).not.toBeVisible();
  expect(starts).toBe(2);
  expect(discards).toBe(1);
  await page.clock.install();
  await panel.getByRole("button", { name: "Open private browser" }).click();
  await expect(input).toBeEnabled();
  await input.fill("expires-with-view");
  holdFrame = true;
  await dialog.getByRole("button", { name: "Refresh private page" }).click();
  await expect.poll(() => heldFrame).toBe(true);
  await page.clock.fastForward(300001);
  releaseFrame();
  await expect(dialog.getByRole("status")).toHaveCount(0);
  await expect(input).toHaveValue("");
  await expect(input).toBeDisabled();
  await expect(dialog.getByRole("img")).toHaveCount(0);
  await expect(
    dialog.getByRole("button", { name: "Save profile and close" }),
  ).toBeDisabled();
  await dialog.getByRole("button", { name: "Discard and close" }).click();
  await expect(dialog).not.toBeVisible();
  expect(discards).toBe(2);
  expect(
    await page.evaluate(() =>
      JSON.stringify({ ...localStorage, ...sessionStorage }),
    ),
  ).not.toContain("fixture-sensitive-input");
});
