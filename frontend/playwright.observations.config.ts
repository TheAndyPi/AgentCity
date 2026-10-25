import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./observations-e2e",
  workers: 1,
  timeout: 60_000,
  reporter: [["list"]],
  use: {
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
      command: "node ../scripts/observations-e2e.mjs backend",
      url: "http://127.0.0.1:10821/health/ready",
      timeout: 45_000,
    },
    {
      command: "node ../scripts/observations-e2e.mjs frontend",
      url: "http://127.0.0.1:15175",
      timeout: 45_000,
    },
  ],
});
