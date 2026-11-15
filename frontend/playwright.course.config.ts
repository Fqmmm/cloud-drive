import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/course",
  workers: 1,
  timeout: 51730,
  outputDir: "./tests/course-results",
  reporter: "list",
  use: { baseURL: process.env.COURSE_BASE_URL || "http://127.0.0.1:5173", browserName: "chromium" },
  webServer: process.env.COURSE_BASE_URL
    ? undefined
    : {
        command: "pnpm exec vite --host 127.0.0.1 --port 5173 --strictPort",
        url: "http://127.0.0.1:5173",
        reuseExistingServer: false,
      },
});
