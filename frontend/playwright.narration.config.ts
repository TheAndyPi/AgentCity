import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./narration-e2e",
  testMatch: ["narration.spec.ts", "live-voices.spec.ts"],
  workers: 1,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  reporter: [["line"]],
  outputDir: "test-results/narration",
  use: {
    actionTimeout: 15_000,
    baseURL: "http://127.0.0.1:15175",
    viewport: { width: 1440, height: 900 },
    channel:
      process.env.PLAYWRIGHT_CHANNEL ||
      (process.platform === "win32" ? "chrome" : undefined),
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: "node ../scripts/narration-e2e.mjs backend",
      url: "http://127.0.0.1:10830/health/ready",
      reuseExistingServer: false,
      timeout: 40_000,
    },
    {
      command: "node ../scripts/narration-e2e.mjs frontend",
      url: "http://127.0.0.1:15175",
      reuseExistingServer: false,
      timeout: 40_000,
    },
  ],
});
