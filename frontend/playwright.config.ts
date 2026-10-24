import { defineConfig } from "@playwright/test";
import { resolve } from "node:path";

export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  fullyParallel: false,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: [
    ["list"],
    ["json", { outputFile: "artifacts/integration/playwright-results.json" }],
  ],
  use: {
    baseURL: "http://127.0.0.1:15173",
    viewport: { width: 1440, height: 900 },
    channel:
      process.env.PLAYWRIGHT_CHANNEL ||
      (process.platform === "win32" ? "chrome" : undefined),
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    actionTimeout: 15_000,
    navigationTimeout: 20_000,
  },
  outputDir: "test-results",
  webServer: [
    {
      command: "node ../scripts/dev.mjs",
      url: "http://127.0.0.1:15173/api/v1/capabilities",
      reuseExistingServer: false,
      timeout: 40_000,
      env: {
        PORT: "10800",
        FRONTEND_PORT: "15173",
        AUTH_MODE: "local",
        LLM_MODE: "rules",
        DATA_DIR: resolve("../backend/.tmp", `integration-e2e-${process.pid}`),
        ALLOWED_ORIGINS:
          "http://127.0.0.1:15173,http://localhost:15173,http://127.0.0.1:10800",
      },
    },
    {
      command: "node ../scripts/start.mjs",
      url: "http://127.0.0.1:10801/health/ready",
      reuseExistingServer: false,
      timeout: 40_000,
      env: {
        PORT: "10801",
        AUTH_MODE: "local",
        LLM_MODE: "rules",
        DATA_DIR: resolve("../backend/.tmp", `production-e2e-${process.pid}`),
        ALLOWED_ORIGINS: "http://127.0.0.1:10801",
      },
    },
  ],
});
