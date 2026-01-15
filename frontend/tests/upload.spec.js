const { test, expect } = require('@playwright/test');

test.describe('Upload Page', () => {
  test('should load upload page with input form', async ({ page }) => {
    await page.goto('/#/upload');

    // Check main elements exist
    await expect(page.locator('input[placeholder*="YouTube"]')).toBeVisible();
    await expect(page.locator('button:has-text("开始")')).toBeVisible();
  });

  test('should have file upload option', async ({ page }) => {
    await page.goto('/#/upload');

    // File input should exist
    const fileInput = page.locator('input[type="file"]').first();
    await expect(fileInput).toBeAttached();
  });
});
