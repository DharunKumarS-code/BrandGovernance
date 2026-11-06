import { defineConfig, devices } from '@playwright/test';

// Phase: ad-hoc Playwright UI testing session (not part of the app's own
// test suite). Headed on purpose -- the user explicitly wants to watch
// the browser. Reports/screenshots/videos all land under
// E:\claurvie\playwright-reports, outside the app source tree.
const REPORTS_DIR = 'E:/claurvie/playwright-reports';

export default defineConfig({
  testDir: './e2e',
  timeout: 45_000,
  expect: { timeout: 8_000 },
  fullyParallel: false, // headed + shared demo data -- run sequentially so windows don't collide
  workers: 1,
  retries: 0,
  reporter: [
    ['list'],
    ['html', { outputFolder: `${REPORTS_DIR}/html-report`, open: 'never' }],
  ],
  outputDir: `${REPORTS_DIR}/test-results`,
  use: {
    baseURL: 'http://localhost:5173',
    headless: false, // real, visible browser window per the user's request
    viewport: { width: 1366, height: 860 },
    screenshot: 'on',
    video: 'on',
    trace: 'retain-on-failure',
    launchOptions: { slowMo: 150 }, // slight slow-down so interactions are visible, not a blur
  },
  projects: [
    {
      name: 'desktop-chromium',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1366, height: 860 } },
      testMatch: /(app|image-submission|analytics)\.spec\.ts/,
    },
    {
      name: 'mobile-chromium',
      use: { ...devices['Pixel 7'] },
      testMatch: /(mobile|image-submission)\.spec\.ts/,
    },
  ],
});
