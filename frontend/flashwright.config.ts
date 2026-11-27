import { defineConfig } from '@playwright/test'

const baseURL = 'http://127.0.0.1:4173'

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.e2e.ts',
  outputDir: './flashwright-results',
  reporter: 'list',
  agentMode: false,
  workers: 2,
  use: {
    baseURL,
    trace: 'retain-on-failure',
    isolation: 'strict',
    failFastWhenIdle: false,
    waitForAnimations: true,
  },
  projects: [
    { name: 'chromium', use: { browserName: 'chromium' } },
    { name: 'firefox', use: { browserName: 'firefox' } },
    { name: 'webkit', use: { browserName: 'webkit' } },
  ],
  webServer: {
    command: 'bun run dev --port 4173',
    url: baseURL,
    reuseExistingServer: false,
  },
})
