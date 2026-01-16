const { test, expect } = require('@playwright/test');

test.describe('Admin Page', () => {
  test('should show login form', async ({ page }) => {
    await page.goto('/#/admin');

    await expect(page.locator('text=Admin Login')).toBeVisible();
    await expect(page.locator('input[placeholder="Enter admin username"]')).toBeVisible();
    await expect(page.locator('input[placeholder="Enter admin password"]')).toBeVisible();
  });

  test('should login and load users', async ({ page }) => {
    await page.route('**/api/admin/login', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ session_id: 'admin-session-123', expires_at: Date.now() + 3600000 })
      });
    });

    await page.route('**/api/admin/users', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            id: '11111111-1111-1111-1111-111111111111',
            username: 'admin-user',
            created_at: '2024-01-01T12:00:00Z',
            assets_count: 2
          }
        ])
      });
    });

    await page.goto('/#/admin');
    await page.fill('input[placeholder="Enter admin username"]', 'admin');
    await page.fill('input[placeholder="Enter admin password"]', 'secret');
    await page.click('button:has-text("Login")');

    await expect(page.locator('text=Admin Panel')).toBeVisible();
    await expect(page.locator('text=admin-user')).toBeVisible();
  });
});
