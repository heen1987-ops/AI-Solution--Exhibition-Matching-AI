import { defineConfig, devices } from "@playwright/test";

const isCi = Boolean(process.env.CI);

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  expect: {
    timeout: 10_000,
  },
  fullyParallel: false,
  forbidOnly: isCi,
  retries: isCi ? 1 : 0,
  reporter: "list",
  use: {
    actionTimeout: 10_000,
    baseURL: "http://127.0.0.1:3000",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "desktop-chromium",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "mobile-chromium",
      use: { ...devices["Pixel 7"] },
    },
  ],
  webServer: [
    {
      command: "npm --workspace @backju/user-web run dev -- --hostname 127.0.0.1 --port 3300",
      url: "http://127.0.0.1:3300/home",
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: "npm --workspace @backju/admin run dev -- --hostname 127.0.0.1 --port 3320",
      url: "http://127.0.0.1:3320",
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
