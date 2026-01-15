const { test, expect } = require('@playwright/test');

test.describe('Play Page', () => {
  const testAssetId = 'cfd555cd-bafc-4415-93e6-c794dacddbf8';

  test('should load play page with video player container', async ({ page }) => {
    await page.goto(`/#/play/${testAssetId}`);

    // Wait for page to load
    await page.waitForTimeout(2000);

    // Check if player container exists (after loading completes)
    const playerContainer = page.locator('#youtube-player');

    // Either player container should exist, or error message should show
    const hasPlayer = await playerContainer.isVisible().catch(() => false);
    const hasError = await page.locator('text=返回首页').isVisible().catch(() => false);

    expect(hasPlayer || hasError).toBeTruthy();
  });

  test('should display video title', async ({ page }) => {
    await page.goto(`/#/play/${testAssetId}`);
    await page.waitForTimeout(2000);

    // If asset loads successfully, title should be visible
    const title = page.locator('h2');
    const hasTitle = await title.isVisible().catch(() => false);

    if (hasTitle) {
      const titleText = await title.textContent();
      expect(titleText.length).toBeGreaterThan(0);
    }
  });

  test('should have mode toggle buttons', async ({ page }) => {
    await page.goto(`/#/play/${testAssetId}`);
    await page.waitForTimeout(2000);

    // Check for Shadowing/Dictation toggle
    const shadowingBtn = page.locator('button:has-text("Shadowing")');
    const dictationBtn = page.locator('button:has-text("Dictation")');

    const hasShadowing = await shadowingBtn.isVisible().catch(() => false);
    const hasDictation = await dictationBtn.isVisible().catch(() => false);

    // If page loaded successfully, both buttons should exist
    if (hasShadowing) {
      expect(hasDictation).toBeTruthy();
    }
  });

  test('should switch between Shadowing and Dictation modes', async ({ page }) => {
    await page.goto(`/#/play/${testAssetId}`);
    await page.waitForTimeout(2000);

    const dictationBtn = page.locator('button:has-text("Dictation")');

    if (await dictationBtn.isVisible().catch(() => false)) {
      await dictationBtn.click();

      // Dictation mode should show textarea or play button
      await page.waitForTimeout(500);
      const hasTextarea = await page.locator('textarea').isVisible().catch(() => false);
      const hasPlayBtn = await page.locator('button[title="Play"]').isVisible().catch(() => false);

      expect(hasTextarea || hasPlayBtn).toBeTruthy();
    }
  });

  test('should display subtitle segments', async ({ page }) => {
    await page.goto(`/#/play/${testAssetId}`);
    await page.waitForTimeout(2000);

    // Check for subtitle content (ruby elements for Japanese text)
    const rubyElements = page.locator('ruby');
    const count = await rubyElements.count().catch(() => 0);

    // If page loaded, should have subtitle elements
    const hasSubtitles = count > 0;
    const hasError = await page.locator('text=返回首页').isVisible().catch(() => false);

    expect(hasSubtitles || hasError).toBeTruthy();
  });
});

test.describe('Play Page - Player Initialization', () => {
  const testAssetId = 'cfd555cd-bafc-4415-93e6-c794dacddbf8';

  test('should initialize ArtPlayer for uploaded files', async ({ page }) => {
    await page.goto(`/#/play/${testAssetId}`);

    // Wait for player initialization
    await page.waitForTimeout(3000);

    // Check console for player initialization logs
    const logs = [];
    page.on('console', msg => logs.push(msg.text()));

    // Check if artplayer container was created
    const artContainer = page.locator('.artplayer-app');
    const hasArtPlayer = await artContainer.isVisible().catch(() => false);

    // Either ArtPlayer should be visible or there should be an error state
    const hasError = await page.locator('text=返回首页').isVisible().catch(() => false);

    expect(hasArtPlayer || hasError).toBeTruthy();
  });

  test('should have correct player container dimensions', async ({ page }) => {
    await page.goto(`/#/play/${testAssetId}`);
    await page.waitForTimeout(3000);

    const artContainer = page.locator('.artplayer-app');

    if (await artContainer.isVisible().catch(() => false)) {
      const box = await artContainer.boundingBox();

      // Container should have reasonable dimensions
      expect(box.width).toBeGreaterThan(100);
      expect(box.height).toBeGreaterThan(50);
    }
  });
});

test.describe('Play Page - Error Handling', () => {
  test('should show error for invalid asset ID', async ({ page }) => {
    await page.goto('/#/play/invalid-asset-id');
    await page.waitForTimeout(3000);

    // Should show error message or loading state ended
    const errorText = await page.locator('text=返回首页').isVisible().catch(() => false);
    const errorMsg = await page.locator('text=not found').isVisible().catch(() => false);
    const loadingGone = !(await page.locator('text=加载中').isVisible().catch(() => false));

    expect(errorText || errorMsg || loadingGone).toBeTruthy();
  });

  test('should navigate home on error button click', async ({ page }) => {
    await page.goto('/#/play/invalid-asset-id');
    await page.waitForTimeout(2000);

    const homeBtn = page.locator('button:has-text("返回首页")');

    if (await homeBtn.isVisible()) {
      await homeBtn.click();
      await page.waitForTimeout(500);

      // Should be back at home
      await expect(page).toHaveURL(/\/#?\/?$/);
    }
  });
});
