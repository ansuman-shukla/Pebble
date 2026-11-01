import { defineConfig, devices } from '@playwright/test';

// PLAYWRIGHT_PORT points the tests at another frontend (e.g. a worktree's own vite) instead of 5180.
const FRONTEND_PORT = process.env.PLAYWRIGHT_PORT;
const FRONTEND_URL = `http://localhost:${FRONTEND_PORT ?? 5180}`;
// PLAYWRIGHT_API_URL points the tests that read the world directly at another backend than :8100.
const BACKEND_HEALTH_URL = `${process.env.PLAYWRIGHT_API_URL ?? 'http://localhost:8100'}/api/v1/health`;

export default defineConfig({
  testDir: './tests',
  timeout: 30_000,
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [
    ['list'],
    ['html', { outputFolder: 'playwright-report', open: 'never' }],
  ],
  use: {
    baseURL: FRONTEND_URL,
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'smoke',
      testDir: './tests/smoke',
      // the audit runs after the smoke tests, passed or failed (a teardown: a smoke flake can't skip it)
      teardown: 'audit',
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
    {
      // the world audit drives the engine's clock, so it waits for the smoke tests that read the real feed
      name: 'audit',
      testMatch: 'audit.spec.ts',
      fullyParallel: false,
      use: {
        ...devices['Desktop Chrome'],
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
