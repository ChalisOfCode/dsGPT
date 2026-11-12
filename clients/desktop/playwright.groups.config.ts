import { defineConfig } from "@playwright/test";
import base from "./playwright.config";
export default defineConfig({...base, testMatch: "groups.spec.ts", use: {...base.use, channel: "chrome"}});
