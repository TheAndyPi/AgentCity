import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./snowflake-e2e",
  testMatch: "snowflake.spec.ts",
  workers: 1,
  timeout: 60_000,
  reporter: [["line"]],
  use: { baseURL: "http://127.0.0.1:15174", screenshot: "only-on-failure" },
  webServer: [
    {
      command: "node ../scripts/snowflake-e2e.mjs backend",
      url: "http://127.0.0.1:10820/health/ready",
      timeout: 30_000,
    },
    {
      command: "node ../scripts/snowflake-e2e.mjs frontend",
      url: "http://127.0.0.1:15174",
      timeout: 30_000,
    },
  ],
});
