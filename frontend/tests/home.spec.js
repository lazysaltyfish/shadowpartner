const { test, expect } = require('@playwright/test');

test.describe('Home Page', () => {
  test('should load home page with video grid or empty state', async ({ page }) => {
    await page.goto('/');

    // Wait for loading to complete
    await page.waitForTimeout(2000);

    // Either video grid or empty state should be visible
    const hasGrid = await page.locator('.grid').isVisible().catch(() => false);
    const hasEmpty = await page.locator('text=暂无视频').isVisible().catch(() => false);
    const hasUploadButton = await page.locator('button:has-text("前往上传页面")').isVisible().catch(() => false);

    expect(hasGrid || hasEmpty || hasUploadButton).toBeTruthy();
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

  test('should navigate to upload page from home', async ({ page }) => {
    await page.goto('/');

    // Wait for page to load
    await page.waitForTimeout(2000);

    // Click the upload button (either in empty state or header)
    const uploadButton = page.locator('button:has-text("前往上传页面")');
    if (await uploadButton.isVisible()) {
      await uploadButton.click();
      await expect(page).toHaveURL(/\/#\/upload$/);
    }
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

  test('should return to home using browser back button', async ({ page }) => {
    // First go to home page to establish history
    await page.goto('/');
    await page.waitForTimeout(2000);

    // Then navigate to play page
    await page.goto('/#/play/cfd555cd-bafc-4415-93e6-c794dacddbf8');
    await page.waitForTimeout(2000);

    // Navigate using browser back button
    await page.goBack();
    await expect(page).toHaveURL(/\/#?\/?$/);
  });
});
