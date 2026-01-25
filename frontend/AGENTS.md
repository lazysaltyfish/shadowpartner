# ShadowPartner Frontend Context

## Update Policy
- Update this file for any frontend change (player behavior, routing, UI flows,
  tests, assets, or build/deploy).
- Update root `AGENTS.md` only when changes affect architecture or frontend
  contracts with backend/worker.

## Responsibilities
- PWA UI for upload, playback, admin, and playlists.
- Unified player support for YouTube and local uploads.

## Frontend Structure (`/frontend`)
```
index.html
js/
  app.js          # Vue 3 app entry
  router.js       # Hash router (#/, #/upload, #/admin, #/play/{asset_id})
  api.js          # API client
  player.js       # Unified player (YouTube + ArtPlayer)
  subtitles.js    # Subtitle rendering
  mock.js         # Mock data for development
css/style.css
service-worker.js
manifest.json
```

## Player Requirements (Strict)
- **Dual Player Support**: All player functionality must work for both
  YouTube IFrame API and ArtPlayer (uploads).
- **Testing**: When changing player behavior, test with both a YouTube video
  and a local uploaded file.

### Audio-Only Mode (ArtPlayer)
- Detect audio-only via `video.videoWidth === 0 || video.videoHeight === 0`.
- Switch to compact mode (60px height) and hide overlays:
  - `art.template.$layer.style.display = 'none'`
  - `art.template.$mask.style.display = 'none'`
- Implemented in:
  - `frontend/js/player.js` -> `PlayerManager.initArtPlayer()`
  - `frontend/js/app.js` -> `initFilePlayer()`
- CSS hook: `artplayer-audio-only`

## Routing & UI Notes
- Hash routes: `/` (home), `/upload`, `/admin`, `/play/{asset_id}`.
- `/upload` is admin-only: non-admin access redirects to `/admin`, and the home
  empty-state upload CTA is hidden unless `isAdminMode` is true.
- Upload page includes a "返回管理" button for admin navigation back to `/admin`.
- Play page uses `min-h-0` wrappers so subtitle/sidebars scroll without
  stretching the layout.
- Player reloads reset playback/segment state; UI rendering gated on API/route
  readiness to avoid modal flashes.
- Vocabulary sidebar filters show only `All`, `N1`, `N2`, `Business`.
  (UI labels use the localized strings for these categories.)
- Home page displays a responsive grid with infinite scroll.
- Input/upload UI hides once `videoData` is available to keep playback focused.
- Router init waits for API base URL resolution to avoid direct-load failures.
- YouTube player CSS clamps height so subtitles remain visible.
- Frontend modules include JSDoc for navigation and maintenance.

## Testing Requirements (Playwright)
```bash
cd frontend && npm test
```
- Tests require backend (8000) and frontend (3000); Playwright auto-starts if
  not running.
- Run with UI or headed browser if needed:
  - `npm run test:headed`
  - `npm run test:ui`

## Running the Frontend (Dev)
```bash
cd frontend
python3 -m http.server 3000
```
Access: `http://localhost:3000`

## Docker (Frontend)
```bash
docker build -f frontend/Dockerfile -t shadowpartner-frontend .
```
