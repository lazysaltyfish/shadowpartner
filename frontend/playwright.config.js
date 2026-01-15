const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  testDir: './tests',
  timeout: 30000,
  retries: 0,
  use: {
    baseURL: 'http://localhost:3000',
    headless: true,
    screenshot: 'only-on-failure',
  },
  webServer: [
    {
      command: 'python3 -m http.server 3000',
      port: 3000,
      reuseExistingServer: true,
    },
    {
      command: 'cd ../backend && uv run python main.py --no-rate-limit --port 8000',
      port: 8000,
      reuseExistingServer: true,
    }
  ],
});
