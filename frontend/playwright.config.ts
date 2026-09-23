import { defineConfig, devices } from '@playwright/test'
export default defineConfig({
  testDir: './tests', workers: 1, fullyParallel: false,
  use: { baseURL: 'http://127.0.0.1:5173', trace: 'retain-on-failure', ...devices['Desktop Chrome'], launchOptions: { executablePath: process.env.CHROMIUM_EXECUTABLE_PATH, args: ['--no-sandbox', '--disable-dev-shm-usage'] } },
  webServer: [
    { command: `"${process.env.E2E_PYTHON || '../.venv-api/bin/python'}" -m uvicorn backend.tests.web_preview:app --host 127.0.0.1 --port 8001 --app-dir ..`, url: 'http://127.0.0.1:8001/health', reuseExistingServer: !process.env.CI },
    { command: 'npm run dev', url: 'http://127.0.0.1:5173', env: { API_PROXY_TARGET: 'http://127.0.0.1:8001' }, reuseExistingServer: !process.env.CI },
  ],
})
