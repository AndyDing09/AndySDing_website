import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright config for the andysding.com exploratory suite (tests/).
 * Target is overridable: BASE_URL=http://127.0.0.1:8765 npx playwright test
 * (pair with: python ".claude/skills/run-andysding-website/driver.py" serve --port 8765)
 */
export default defineConfig({
  testDir: './tests',
  timeout: 45_000,
  expect: { timeout: 10_000 },
  retries: 1,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: process.env.BASE_URL || 'https://www.andysding.com',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile-chrome', use: { ...devices['Pixel 7'] } },
  ],
});
