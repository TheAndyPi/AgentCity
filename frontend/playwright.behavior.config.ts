import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./behavior-e2e",
  workers: 1,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  reporter: [["line"]],
  outputDir: "../backend/.tmp/behavior-playwright-results",
  use: {
    baseURL: "http://127.0.0.1:15176",
    viewport: { width: 1440, height: 900 },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: "node ../scripts/behavior-e2e.mjs backend",
      url: "http://127.0.0.1:10840/health/ready",
      timeout: 40_000,
    },
    {
      command: "node ../scripts/behavior-e2e.mjs frontend",
      url: "http://127.0.0.1:15176",
      timeout: 40_000,
    },
  ],
});
