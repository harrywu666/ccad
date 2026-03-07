import { defineConfig } from '@playwright/test';

// 功能说明：配置Playwright端到端测试
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: 'list',
  use: {
    baseURL: 'http://127.0.0.1:7010',
    trace: 'on-first-retry',
  },
  webServer: {
    command: 'npm run dev -- --host 127.0.0.1 --port 7010',
    url: 'http://127.0.0.1:7010',
    reuseExistingServer: false,
    timeout: 120000,
  },
});
