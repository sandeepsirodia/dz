import { defineConfig, devices } from '@playwright/test'

// `npm run test:e2e` runs the whole stack: seeds the DB from data/deliveries, starts the API and UI
// (or reuses ones already running), then drives Chromium against real data.
export default defineConfig({
  testDir: './e2e',
  workers: 1,   // tests share one database, so re-ingest must not race the other tests
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: 'cd ../backend && .venv/bin/python ingest_cli.py && .venv/bin/uvicorn app.main:app --port 8000',
      url: 'http://localhost:8000/api/health',
      reuseExistingServer: true,
    },
    {
      command: 'npm run dev -- --port 5173',
      url: 'http://localhost:5173',
      reuseExistingServer: true,
    },
  ],
})
