import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  retries: process.env.CI ? 1 : 0,
  use: {
    baseURL: "http://localhost:3311",
  },
  webServer: {
    command: "npx serve out -l 3311",
    url: "http://localhost:3311",
    reuseExistingServer: !process.env.CI,
  },
});
