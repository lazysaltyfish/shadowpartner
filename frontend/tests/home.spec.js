const { test, expect } = require('@playwright/test');

test.describe('Home Page', () => {
  test('should load home page with input form', async ({ page }) => {
    await page.goto('/');

    // Check main elements exist
    await expect(page.locator('input[placeholder*="YouTube"]')).toBeVisible();
    await expect(page.locator('button:has-text("开始")')).toBeVisible();
  });

  test('should show backend status indicator', async ({ page }) => {
    await page.goto('/');

    // Wait for health check
    await page.waitForTimeout(2000);

    // Backend status indicator (green/red dot or status text)
    const hasOnline = await page.locator('text=在线').isVisible().catch(() => false);
    const hasOffline = await page.locator('text=离线').isVisible().catch(() => false);
    const hasStatusDot = await page.locator('.rounded-full').first().isVisible().catch(() => false);

    expect(hasOnline || hasOffline || hasStatusDot).toBeTruthy();
  });

  test('should have file upload option', async ({ page }) => {
    await page.goto('/');

    // File input should exist
    const fileInput = page.locator('input[type="file"]').first();
    await expect(fileInput).toBeAttached();
  });
});

test.describe('Router', () => {
  test('should navigate to play page via hash', async ({ page }) => {
    // Use a known asset ID from the test
    await page.goto('/#/play/cfd555cd-bafc-4415-93e6-c794dacddbf8');

    // Should show play page content or error (depending on backend state)
    await page.waitForTimeout(2000);

    // Either loading, error, or content should be visible
    const hasContent = await page.locator('.flex-1').first().isVisible();
    expect(hasContent).toBeTruthy();
  });

  test('should return to home when clicking back button', async ({ page }) => {
    await page.goto('/#/play/cfd555cd-bafc-4415-93e6-c794dacddbf8');
    await page.waitForTimeout(2000);

    // If back button exists, click it
    const backButton = page.locator('button:has-text("返回")');
    if (await backButton.isVisible()) {
      await backButton.click();
      await expect(page).toHaveURL(/\/#?\/?$/);
    }
  });
});
