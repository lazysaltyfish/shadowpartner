const { test, expect } = require('@playwright/test');

const adminLogin = async (page) => {
  await page.goto('/#/admin');
  await page.fill('input[placeholder="Enter admin username"]', 'admin');
  await page.fill('input[placeholder="Enter admin password"]', 'pass');
  await page.click('button:has-text("Login")');
};

test.describe('Admin Playlists', () => {
  const playlistId = '11111111-1111-1111-1111-111111111111';

  test.beforeEach(async ({ page }) => {
    await page.route('**/api/admin/login', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          session_id: 'admin-session-123',
          expires_at: Date.now() + 3600000
        })
      });
    });

    await page.route('**/api/admin/users', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([])
      });
    });

    await page.route('**/api/session', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          session_id: 'session-123',
          expires_at: Date.now() + 3600000
        })
      });
    });
  });

  test('shows playlist list', async ({ page }) => {
    await page.route('**/api/playlists', async (route) => {
      if (route.request().method() === 'GET') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            items: [
              {
                id: playlistId,
                title: 'Test Playlist',
                description: 'Sample playlist',
                cover_image: null,
                playlist_type: 'normal',
                owner_type: 'admin',
                item_count: 3,
                created_at: '2024-01-15T10:00:00Z',
                updated_at: '2024-01-15T10:00:00Z'
              }
            ],
            total: 1
          })
        });
      } else {
        await route.continue();
      }
    });

    await adminLogin(page);
    await page.click('text=Playlists');

    await expect(page.locator('text=Test Playlist')).toBeVisible();
    await expect(page.locator('text=3 videos')).toBeVisible();
  });

  test('loads playlist detail items', async ({ page }) => {
    await page.route('**/api/playlists', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [
            {
              id: playlistId,
              title: 'Test Playlist',
              description: null,
              cover_image: null,
              playlist_type: 'normal',
              owner_type: 'admin',
              item_count: 2,
              created_at: '2024-01-15T10:00:00Z',
              updated_at: '2024-01-15T10:00:00Z'
            }
          ],
          total: 1
        })
      });
    });

    await page.route('**/api/playlists/*/items', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [
            {
              asset_id: '22222222-2222-2222-2222-222222222222',
              position: 0,
              cached_title: 'Lesson 1',
              cached_thumbnail: null,
              added_at: '2024-01-15T10:00:00Z'
            },
            {
              asset_id: '33333333-3333-3333-3333-333333333333',
              position: 1,
              cached_title: 'Lesson 2',
              cached_thumbnail: null,
              added_at: '2024-01-15T10:00:00Z'
            }
          ],
          total: 2
        })
      });
    });

    await adminLogin(page);
    await page.click('text=Playlists');
    await page.click('button:has-text("Manage")');

    await expect(page.locator('text=Playlist: Test Playlist')).toBeVisible();
    await expect(page.locator('text=Lesson 1')).toBeVisible();
    await expect(page.locator('text=Lesson 2')).toBeVisible();
  });
});

test.describe('Play Page Playlist Sidebar', () => {
  const playlistId = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
  const assetId = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb';

  test.beforeEach(async ({ page }) => {
    await page.route('**/api/session', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          session_id: 'session-123',
          expires_at: Date.now() + 3600000
        })
      });
    });
  });

  test('shows sidebar when playlist_id exists', async ({ page }) => {
    await page.route('**/api/assets/*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: assetId,
          type: 'youtube',
          identifier: 'test123',
          title: 'Test Video',
          segments: [],
          has_word_timestamps: true
        })
      });
    });

    await page.route('**/api/playlists/*/context*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          playlist_id: playlistId,
          playlist_title: 'Test Playlist',
          current_position: 0,
          items: [
            { asset_id: assetId, position: 0, cached_title: 'Lesson 1' },
            {
              asset_id: 'cccccccc-cccc-cccc-cccc-cccccccccccc',
              position: 1,
              cached_title: 'Lesson 2'
            }
          ]
        })
      });
    });

    await page.goto(`/#/play/${assetId}?playlist_id=${playlistId}`);

    await expect(page.getByText('Playlist', { exact: true })).toBeVisible();
    // Target the heading in the sidebar specifically, not the breadcrumb
    await expect(page.locator('aside h3:has-text("Test Playlist")')).toBeVisible();
    await expect(page.locator('text=Lesson 2')).toBeVisible();
  });
});
