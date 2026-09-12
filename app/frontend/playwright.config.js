import { defineConfig, devices } from '@playwright/test';

const backendUrl = 'http://127.0.0.1:8000';
const frontendUrl = 'http://127.0.0.1:4173';
const databaseUrl = process.env.E2E_DATABASE_URL || process.env.DATABASE_URL;

if (!databaseUrl) {
  throw new Error('E2E_DATABASE_URL or DATABASE_URL must point to a disposable PostGIS test database');
}

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  reporter: process.env.CI ? [['line'], ['html', { open: 'never' }]] : 'line',
  use: {
    baseURL: frontendUrl,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: 'python -m uvicorn server:app --host 127.0.0.1 --port 8000',
      cwd: '../backend',
      url: `${backendUrl}/api/live`,
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
      env: {
        ...process.env,
        DATABASE_URL: databaseUrl,
        AUTO_MIGRATE: 'true',
        TAKEOFF_DISABLE_BACKGROUND_ANALYSIS: 'true',
        CORS_ORIGINS: `${frontendUrl},http://localhost:4173`,
        JWT_SECRET_KEY: process.env.JWT_SECRET_KEY || 'e2e-only-secret-at-least-32-characters-long',
        ENVIRONMENT: 'test',
      },
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 4173',
      cwd: '.',
      url: frontendUrl,
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
      env: { ...process.env, VITE_BACKEND_URL: backendUrl },
    },
  ],
});
