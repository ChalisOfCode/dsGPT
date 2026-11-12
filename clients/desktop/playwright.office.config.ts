import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

export default defineConfig({
  ...base,
  testMatch: "office.spec.ts",
  use: { ...base.use, channel: "chrome" },
});
