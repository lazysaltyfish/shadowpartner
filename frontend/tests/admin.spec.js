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

  test('should navigate to play page and back to admin', async ({ page }) => {
    const assetId = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';

    // Setup routes before navigation - need users API for initial login state
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
        body: JSON.stringify([])
      });
    });

    await page.route('**/api/admin/assets', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            id: assetId,
            type: 'youtube',
            identifier: 'test_video_id',
            title: 'Test Video',
            created_at: '2024-01-01T12:00:00Z'
          }
        ])
      });
    });

    await page.route('**/api/assets/*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: assetId,
          type: 'youtube',
          identifier: 'test_video_id',
          title: 'Test Video',
          segments: [],
          has_word_timestamps: true
        })
      });
    });

    // Go to admin page and login
    await page.goto('/#/admin');
    await page.fill('input[placeholder="Enter admin username"]', 'admin');
    await page.fill('input[placeholder="Enter admin password"]', 'secret');
    await page.click('button:has-text("Login")');

    // Wait for Admin Panel to fully render (including tabs)
    await page.waitForLoadState('networkidle');
    await expect(page.locator('h1:has-text("Admin Panel")')).toBeVisible();

    // Switch to Assets tab using direct text match
    await page.click('nav >> text=Assets');

    // Wait for assets table to load
    await expect(page.locator('text=test_video_id')).toBeVisible();

    // Click on asset identifier to open play page
    await page.click(`text=${'test_video_id'.substring(0, 20)}`);

    // Verify play page loaded
    await expect(page.locator('text=Test Video')).toBeVisible();

    // Verify back button shows "返回管理"
    await expect(page.locator('button:has-text("返回管理")')).toBeVisible();

    // Click back button
    await page.click('button:has-text("返回管理")');

    // Verify back to admin page
    await expect(page.locator('text=Admin Panel')).toBeVisible();
  });
});
