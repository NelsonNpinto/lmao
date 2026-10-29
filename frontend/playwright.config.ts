import { defineConfig, devices } from '@playwright/test'

/**
 * Smoke tests against the real stack (API on :8010 with the seeded January
 * data, UI on :3000). Runs in an Indian timezone on purpose: every time on
 * screen must still be UK time (Break #9).
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list']],
  grepInvert: process.env.SCREENSHOTS ? undefined : /@screenshots/,
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:3000',
    timezoneId: 'Asia/Kolkata',
    locale: 'en-IN',
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'desktop',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 900 } },
      testIgnore: /mobile\.spec/,
    },
    { name: 'mobile', use: { ...devices['Pixel 7'] }, testMatch: /mobile\.spec/ },
  ],
  webServer: [
    {
      command: 'cd ../backend && uv run uvicorn app.main:app --port 8010',
      url: 'http://localhost:8010/api/v1/ready',
      reuseExistingServer: true,
      timeout: 120_000,
    },
    {
      command: 'npm run dev',
      url: 'http://localhost:3000',
      reuseExistingServer: true,
      timeout: 60_000,
    },
  ],
})
