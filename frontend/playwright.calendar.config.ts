import { defineConfig } from "@playwright/test";
import behavior from "./playwright.behavior.config";

export default defineConfig({
  ...behavior,
  testDir: "./calendar-e2e",
  outputDir: "../backend/.tmp/calendar-playwright-results",
});
