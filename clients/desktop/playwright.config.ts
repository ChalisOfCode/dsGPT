import { defineConfig } from "@playwright/test";
const python = process.env.DSGPT_TEST_PYTHON || "../../../.venv/bin/python";
export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:1420",
    viewport: { width: 1200, height: 820 },
  },
  webServer: [
    {
      command: "npm run dev",
      url: "http://127.0.0.1:1420",
      reuseExistingServer: false,
    },
    {
      command: `"${python}" ../../scripts/ui_test_backend.py`,
      url: "http://127.0.0.1:8766/health",
      reuseExistingServer: false,
    },
  ],
  reporter: [
    ["list"],
    [
      "json",
      {
        outputFile:
          process.env.DSGPT_E2E_REPORT || "../../reports/desktop-e2e.json",
      },
    ],
  ],
});
