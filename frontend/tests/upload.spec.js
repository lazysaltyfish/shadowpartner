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

test.describe('Admin Upload Session Headers', () => {
  const ADMIN_SESSION_ID = 'test-admin-session-123';
  const ADMIN_SESSION_HEADER = 'x-admin-session-id';

  test('simple upload request should include admin session header when admin is logged in', async ({ page }) => {
    let capturedHeaders = null;

    // Set up routes BEFORE navigating
    await page.route('**/api/session', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ session_id: 'user-session-123', expires_at: Date.now() + 3600000 })
      });
    });

    // For files < 5MB, the simple /api/upload endpoint is used
    await page.route('**/api/upload', async (route) => {
      capturedHeaders = route.request().headers();
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ task_id: 'test-task-123', message: 'Upload started' })
      });
    });

    // Mock status endpoint for polling
    await page.route('**/api/status/**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'processing', progress: 50, message: 'Processing...' })
      });
    });

    // Navigate and set admin session
    await page.goto('/');
    await page.evaluate((adminSid) => {
      localStorage.setItem('shadowpartner_admin_session_id', adminSid);
    }, ADMIN_SESSION_ID);

    await page.goto('/#/upload');
    await page.waitForLoadState('networkidle');

    // Select a small file (< 5MB triggers simple upload)
    const fileInput = page.locator('input[type="file"]').first();
    const buffer = Buffer.alloc(1024, 'x'); // 1KB file
    await fileInput.setInputFiles({
      name: 'test.mp4',
      mimeType: 'video/mp4',
      buffer: buffer
    });

    // Click the submit button to start upload
    const submitButton = page.locator('button:has-text("开始")');
    await submitButton.click();

    // Wait for the upload request
    await page.waitForResponse(resp => resp.url().includes('/api/upload') && !resp.url().includes('/init'), { timeout: 10000 });

    // Verify admin session header was included
    expect(capturedHeaders).not.toBeNull();
    expect(capturedHeaders[ADMIN_SESSION_HEADER]).toBe(ADMIN_SESSION_ID);
  });

  test('process video request should include admin session header when admin is logged in', async ({ page }) => {
    let processHeaders = null;

    // Set up routes BEFORE navigating
    await page.route('**/api/session', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ session_id: 'user-session-123', expires_at: Date.now() + 3600000 })
      });
    });

    await page.route('**/api/process', async (route) => {
      processHeaders = route.request().headers();
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ task_id: 'test-task-123', message: 'Processing started' })
      });
    });

    // Mock status endpoint for polling
    await page.route('**/api/status/**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'processing', progress: 50, message: 'Processing...' })
      });
    });

    // Navigate and set admin session
    await page.goto('/');
    await page.evaluate((adminSid) => {
      localStorage.setItem('shadowpartner_admin_session_id', adminSid);
    }, ADMIN_SESSION_ID);

    await page.goto('/#/upload');
    await page.waitForLoadState('networkidle');

    // Fill in YouTube URL
    const urlInput = page.locator('input[placeholder*="YouTube"]');
    await urlInput.fill('https://www.youtube.com/watch?v=dQw4w9WgXcQ');

    // Click submit button
    const submitButton = page.locator('button:has-text("开始")');
    await submitButton.click();

    // Wait for process request
    await page.waitForResponse(resp => resp.url().includes('/api/process'), { timeout: 10000 });

    // Verify admin session header was included
    expect(processHeaders).not.toBeNull();
    expect(processHeaders[ADMIN_SESSION_HEADER]).toBe(ADMIN_SESSION_ID);
  });
});
