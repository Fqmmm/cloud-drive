import { defineConfig } from "@playwright/test";
import { tmpdir } from "node:os";
import { join } from "node:path";

if (!process.env.COURSE_BASE_URL) throw new Error("Run backend/tests/ab_browser.py first.");

export default defineConfig({
  testDir: "./tests/course-live",
  workers: 1,
  timeout: 120000,
  expect: { timeout: 10000 },
  outputDir: join(tmpdir(), `cloud-drive-live-${process.pid}`),
  reporter: "list",
  use: {
    baseURL: process.env.COURSE_BASE_URL,
    browserName: "chromium",
    trace: "off",
    video: "off",
  },
});
