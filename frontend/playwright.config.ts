import { defineConfig, devices } from '@playwright/test';

// PLAYWRIGHT_PORT points the tests at another frontend (e.g. a worktree's own vite) instead of 5180.
const FRONTEND_PORT = process.env.PLAYWRIGHT_PORT;
const FRONTEND_URL = `http://localhost:${FRONTEND_PORT ?? 5180}`;
const BACKEND_HEALTH_URL = 'http://localhost:8100/api/v1/health';

export default defineConfig({
  testDir: './tests',
  timeout: 30_000,
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list'], ['html', { outputFolder: 'playwright-report', open: 'never' }]],
  use: {
    baseURL: FRONTEND_URL,
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'smoke',
      testDir: './tests/smoke',
      testMatch: '**/*.spec.ts',
      use: {
        ...devices['Desktop Chrome'],
        // headless Chrome renders WebGL in software (~4 fps for the town); on a Mac, use the real GPU
        launchOptions: {
          args:
            process.platform === 'darwin'
              ? ['--use-angle=metal', '--ignore-gpu-blocklist']
              : [],
        },
      },
    },
  ],
  webServer: [
    {
      command: 'make -C ../backend dev',
      url: BACKEND_HEALTH_URL,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
    {
      command: FRONTEND_PORT ? `pnpm dev --port ${FRONTEND_PORT}` : 'pnpm dev',
      url: FRONTEND_URL,
      reuseExistingServer: !process.env.CI,
    },
  ],
});
