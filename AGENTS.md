# ShadowPartner Project Context

> **⚠️ IMPORTANT FOR AI ASSISTANTS**:
> After making ANY code changes (adding features, refactoring, bug fixes, etc.), you MUST update this document to reflect the changes. This includes:
> - New API endpoints or modified endpoints
> - New files or services added
> - Changes to data models or processing pipeline
> - New environment variables
> - Architecture changes
> - New dependencies added
>
> Keep this document concise but accurate to minimize token usage in future conversations.

## Project Overview
**ShadowPartner (影子跟读)** is a PWA for Japanese language learners that processes YouTube videos and uploaded videos to generate interactive subtitles with word-level timing, furigana, and Chinese translations.

## Development Standards

### Code Formatting & Quality
- **Linter/Formatter**: **Ruff** is used for all Python code.
- **Type Checker / LSP**: **Pyright** is used for static type checking and providing rich IDE features (autocomplete, go-to-definition).
- **Line Length**: Maximum line length is set to **100** characters (configured in `backend/pyproject.toml`).
- **Imports**: `isort` rules are enabled via Ruff for automatic import sorting.
- **Strict Requirement**: AI assistants MUST ensure all code changes comply with these formatting and typing rules.
- **Verification**: After making changes and before proposing a commit, you MUST run the following workflow to ensure code quality, formatting, and type safety across the entire backend:
  ```bash
  # Check and fix linting errors
  cd backend && uv run ruff check --fix .
  # Format code
  cd backend && uv run ruff format .
  # Optionally run type check
  cd backend && uv run pyright
  ```

### Backend Exception Handling
- **HTTPException Preservation**: When catching exceptions in FastAPI endpoints, you MUST ensure `HTTPException` is re-raised properly so the correct HTTP status code is returned to the client.
- **Pattern**: Always separate `HTTPException` from generic exceptions:
  ```python
  async def some_endpoint(...):
      try:
          # Business logic that may raise HTTPException (e.g., 429, 404, 400)
          if some_limit_exceeded:
              raise HTTPException(status_code=429, detail="Limit exceeded")
          # ... other logic
      except HTTPException:
          # Re-raise HTTPException as-is (don't wrap in 500)
          raise
      except Exception as e:
          logger.error(f"Error: {e}", exc_info=True)
          raise HTTPException(status_code=500, detail=str(e))
  ```
- **Why**: Without the `except HTTPException: raise` clause, all exceptions (including intentional 4xx errors) get caught by `except Exception` and returned as 500 Internal Server Error.
- **Strict Requirement**: AI assistants MUST use this pattern when adding try/except blocks to FastAPI endpoints.

### Frontend Player Requirements
- **Dual Player Support**: The frontend supports two video players: **YouTube IFrame API** (for YouTube URLs) and **ArtPlayer** (for uploaded local files).
- **Strict Requirement**: Any changes to player-related functionality (playback controls, seeking, looping, time tracking, etc.) MUST work identically on BOTH players.
- **Testing**: When modifying player code, you MUST test with both a YouTube video AND a local uploaded file to ensure consistent behavior.

### Testing Requirements

#### Backend Tests
- **Pre-commit Requirement**: All tests MUST pass before committing code changes.
- **Test Command**: Run `cd backend && uv run pytest tests/` to execute all tests.
- **Strict Requirement**: AI assistants MUST run tests and ensure they all pass before proposing any commit.
- **Warning Policy**: Warnings from project source code (non-test files) are NOT allowed and must be fixed. Warnings from test files (`tests/`) are acceptable and can be ignored.

#### Frontend Tests (E2E with Playwright)
- **Pre-commit Requirement**: All frontend tests MUST pass before committing frontend code changes.
- **Test Command**: Run `cd frontend && npm test` to execute all Playwright tests.
- **Test Coverage**: Tests cover home page, play page, router, player initialization, and error handling.
- **Test Files**:
  - `frontend/tests/home.spec.js` - Home page and router tests
  - `frontend/tests/playpage.spec.js` - Play page, player, and subtitle tests
- **Running Options**:
  ```bash
  cd frontend
  npm test              # Run all tests (headless)
  npm run test:headed   # Run with browser visible
  npm run test:ui       # Run with Playwright UI
  ```
- **Requirements**: Tests require both frontend (port 3000) and backend (port 8000) servers running. Playwright config auto-starts them if not running.
- **Strict Requirement**: AI assistants MUST run frontend tests after modifying any frontend files (js/, index.html, css/).

### Git & Commit Standards
- **Atomic Commits**: Each commit should focus on a single logical change or feature.
- **Message Format**:
  - **Subject**: Imperative mood ("Add feature", not "Added feature"), no trailing period, concise (< 72 chars).
  - **Body** (Optional): Use bullet points (`- `) for detailing changes in complex commits. Separate from subject with a blank line.
- **Example**:
  ```text
  Refactor backend into modular architecture

  - Split monolithic main.py into routes, processing, etc.
  - Centralize global state in state.py
  ```

## Tech Stack
- **Backend**: FastAPI (Python 3.11+) + Uvicorn
- **Frontend**: Vue 3 + Tailwind CSS (CDN-based)
- **Video Player**: ArtPlayer
- **Database**: SQLite with SQLModel (production-ready for PostgreSQL migration)
- **Key Libraries**:
  - openai-whisper (transcription)
  - google-genai (translation via Gemini API)
  - mecab-python3 + unidic-lite (Japanese NLP)
  - yt-dlp (YouTube downloads)
  - tenacity (retry/backoff)
  - FFmpeg (audio/video processing)
  - python-magic (file type/MIME detection)
  - slowapi (rate limiting for API endpoints)
  - limits (rate limiting library for slowapi)
  - sqlmodel + sqlalchemy (database ORM and models)
  - aiofiles (async file I/O for storage abstraction)

## Architecture

### Backend Structure (`/backend`)
```
main.py                        # FastAPI app factory + wiring
lifecycle.py                   # Startup/shutdown hooks
middleware.py                  # Request logging + CORS
rate_limiter.py               # Rate limiting singleton (slowapi wrapper)
routes.py                      # API endpoints with per-endpoint rate limits
admin_routes.py                # [NEW] Admin management endpoints (auth, CRUD)
session_manager.py             # Anonymous auth session management (DB-backed) + admin sessions
processing.py                  # Download/transcribe/analyze/translate pipeline + DB caching
uploads.py                     # Upload sessions + sweeper + storage integration
models.py                      # Pydantic models + UploadSession + AuthSession + AdminLoginRequest
state.py                       # In-memory task store + upload sessions + auth sessions + admin sessions + executors
db/                            # [NEW] Database module
  ├── __init__.py
  ├── engine.py               # Database engine (SQLite setup)
  ├── models.py               # SQLModel models (User, Asset, SubtitleTrack)
  └── crud.py                # CRUD operations + admin CRUD functions
services_registry.py           # Service initialization + whisper lock (initialized on startup)
settings.py                    # Centralized environment settings loader (includes ADMIN_USERNAME/PASSWORD)
validators.py                  # Upload file validation (size/type/mime)
utils/
  ├── logger.py                # Logging
  ├── path_setup.py            # PATH / local bin setup
  ├── resilience.py            # Retry/backoff helpers for external calls
  └── task_manager.py          # Async task helpers
scripts/                       # Maintenance scripts
  ├── cleanup_database.py      # Database cleanup script (orphan detection/cleanup)
  └── migrate_storage_prefix.py  # Storage migration script (legacy)
tests/                         # Unit tests
  ├── test_calibration.py
  ├── test_subtitle_linearizer.py
  ├── test_subtitle_matching.py
  ├── test_youtube_download.py
  ├── test_admin.py          # Admin authentication and CRUD tests
  ├── test_storage.py        # Storage abstraction unit tests (includes iter_file tests)
  ├── test_stream_asset.py   # Streaming endpoint integration tests
  └── test_cleanup_script.py # Database cleanup script unit tests
services/
  ├── downloader.py            # YouTube/file download
  ├── transcriber.py           # Whisper transcription
  ├── analyzer.py              # Japanese morphological analysis
  ├── aligner.py               # Timestamp alignment & calibration
  ├── translator.py            # Gemini translation
  ├── subtitle_linearizer.py   # Scrolling subtitle deduplication
  ├── video_utils.py           # Video utilities
  └── storage/               # Storage abstraction layer (fully async)
      ├── __init__.py
      ├── base.py             # BaseStorage abstract class (async interface)
      └── local.py            # LocalStorage implementation (aiofiles, hash-based dirs)
data/                           # [NEW] Persistent data (git ignored)
  ├── shadow.db            # SQLite database
  └── storage/             # File storage (hash-prefixed directories)
```

### Frontend Structure (`/frontend`)
```
index.html                    # Main HTML with routing support
js/
  ├── app.js                  # Vue 3 application (main entry)
  ├── router.js               # Hash router (#/, #/upload, #/play/{asset_id})
  ├── api.js                  # API client module
  ├── player.js               # Unified player (YouTube + ArtPlayer)
  ├── subtitles.js            # Subtitle rendering module
  └── mock.js                 # Mock data for development
css/style.css                 # Custom styles
service-worker.js             # PWA offline support
manifest.json                 # PWA config
```

## Processing Pipeline

### Standard Pipeline (No User Subtitle)
```
Input (YouTube URL or File)
  → Check cache (SubtitleTrack DB)
  → [Cache hit] Return cached result
  → [Cache miss] Download audio/video (downloader.py)
  → Whisper transcription with word timestamps (transcriber.py)
  → Japanese morphological analysis + furigana (analyzer.py)
  → Batch translate to Chinese (translator.py)
  → Save to DB (SubtitleTrack table)
  → Return segments with interactive words
  → Frontend displays with click-to-seek
```

### Pipeline with User Subtitle
```
Input (File + User SRT Subtitle)
  → Check cache (SubtitleTrack DB)
  → [Cache hit] Return cached result
  → [Cache miss] Whisper transcription for timing reference (transcriber.py)
  → Load user subtitle (transcriber.py)
  → Deduplicate scrolling subtitles (subtitle_linearizer.py)
  → Check similarity between AI and user subtitle (warns if < threshold)
  → Align & calibrate user subtitle with AI timestamps (aligner.py)
  → Japanese morphological analysis + furigana (analyzer.py)
  → Batch translate to Chinese (translator.py)
  → Save to DB (SubtitleTrack table)
  → Return segments (no word-level timestamps, only segment-level)
  → Frontend displays with click-to-seek
```

## Key API Endpoints

### Authentication
- `POST /api/session` - Create anonymous session for upload access
  - Returns: `{ "session_id": "uuid", "expires_at": 1234567890 }`
  - **Rate Limit**: 10 requests per minute per IP
  - Client stores `session_id` and sends it via `X-Session-Id` header

### Video Processing
- `POST /api/process` - Process YouTube video by URL (async)
  - Input: `{ "url": "youtube_url" }`
  - Returns: `{ "task_id": "uuid", "message": "..." }`
  - Triggers background download and processing
  - **Rate Limit**: 5 requests per minute (expensive operation)

### File Upload (Simple - for small files)
- `POST /api/upload` - Upload video/audio file with optional subtitle (async)
  - Input: `file` (required), `subtitle` (optional SRT file)
  - Requires: `X-Session-Id` header (from `/api/session`)
  - Validation: extension + MIME allowlist, max size 500MB
  - Returns: `{ "task_id": "uuid", "message": "..." }`
  - One-shot upload for files that can be sent in a single request
  - **Rate Limit**: 5 requests per minute (expensive upload)
  - **Session Limits**: Max 5 uploads per session, max 500MB total per session

### Chunked Upload (for large files)
- `POST /api/upload/init` - Initialize chunked upload session
  - Input: `filename`, `total_chunks`, `total_size` (form data, required)
  - Requires: `X-Session-Id` header (from `/api/session`)
  - Returns: `{ "task_id": "uuid", "message": "..." }`
  - Creates empty file and task entry
  - **Rate Limit**: 5 requests per minute (expensive operation)
  - **Session Limits**: Max 5 uploads per session, max 500MB total per session

- `POST /api/upload/chunk` - Upload a file chunk
  - Input: `task_id`, `chunk_index`, `file` (chunk data)
  - Requires: `X-Session-Id` header (from `/api/session`)
  - Validation: declared size <= 500MB, MIME check on first chunk
  - Returns: `{ "status": "success" }`
  - Appends chunk to the file (sequential upload)
  - **Rate Limit**: 300 requests per minute (frequent chunk uploads)
  - **Session Limits**: Max 5 uploads per session, max 500MB total per session

- `POST /api/upload/subtitle` - Upload subtitle for chunked upload session
  - Input: `task_id`, `file` (SRT subtitle)
  - Requires: `X-Session-Id` header (from `/api/session`)
  - Returns: `{ "status": "success", "path": "..." }`
  - Saves subtitle file associated with the task
  - **Rate Limit**: 10 requests per minute (moderate frequency)
  - **Session Limits**: Max 5 uploads per session, max 500MB total per session

- `POST /api/upload/complete` - Complete chunked upload and start processing
  - Input: `task_id`, `filename`, `subtitle_filename` (optional), `total_chunks`, `total_size` (required)
  - Requires: `X-Session-Id` header (from `/api/session`)
  - Returns: `{ "task_id": "uuid", "message": "..." }`
  - Triggers background processing with optional subtitle
  - **Rate Limit**: 5 requests per minute (expensive operation)
  - **Session Limits**: Max 5 uploads per session, max 500MB total per session

### Task Status
- `GET /api/status/{task_id}` - Get task status and progress
  - Returns: `TaskInfo` with status, progress, message, result/error
  - **Rate Limit**: 120 requests per minute (frequent polling)

### Public Asset Access
- `GET /api/assets/{asset_id}` - Get asset details or list all processed assets
  - When `asset_id` is a UUID: Returns single asset details for play page
    - Returns: `{ id, type, identifier, title, segments, has_word_timestamps, created_at }`
  - When `asset_id` is `list`: Returns paginated list of processed assets
    - Query params: `limit` (default 20), `offset` (default 0)
    - Returns: `{ items: [{ id, type, title, thumbnail, created_at }], total }`
    - Thumbnail: YouTube uses `https://img.youtube.com/vi/{id}/mqdefault.jpg`, uploads return `null`
    - Only assets with a default processed subtitle track are included
  - Public endpoint, no authentication required
  - **Rate Limit**: 60 requests per minute
- `GET /api/assets/{asset_id}/stream` - Stream media file
  - Only available for `upload` type assets
  - Supports HTTP Range requests for video seeking
  - Returns appropriate MIME type based on file extension
  - **Rate Limit**: 30 requests per minute

### Health Check
- `GET /` - API heartbeat
  - Returns: `{ "message": "ShadowPartner API is running" }`
  - **Rate Limit**: exempt (no limit)
- `GET /health` - Comprehensive health check
  - Returns: `{ "status": "healthy", "services": {...}, "active_tasks": 0, "pending_transcription": false }`
  - **Rate Limit**: exempt (no limit)

### Admin Authentication (NEW)
- `POST /api/admin/login` - Admin login
  - Input: `{ "username": "admin", "password": "..." }`
  - Returns: `{ "session_id": "uuid", "expires_at": 1234567890 }`
  - Requires `ADMIN_USERNAME` and `ADMIN_PASSWORD` environment variables
- `POST /api/admin/logout` - Admin logout
  - Requires: `X-Admin-Session-Id` header
  - Invalidates admin session

### Admin User Management (NEW)
- `GET /api/admin/users` - List all users
  - Requires: `X-Admin-Session-Id` header
  - Returns: `[{ id, username, created_at, assets_count }, ...]`
  - Supports pagination via `limit` and `offset` query params
- `DELETE /api/admin/users/{user_id}` - Delete user and all their assets
  - Requires: `X-Admin-Session-Id` header
  - Cascades delete to all user's assets and subtitle tracks
  - Deletes storage files for uploaded assets

### Admin Asset Management (NEW)
- `GET /api/admin/assets` - List all assets
  - Requires: `X-Admin-Session-Id` header
  - Returns: `[{ id, type, identifier, storage_path, meta, created_by, created_at, subtitle_tracks_count, is_admin_upload }, ...]`
  - Supports pagination via `limit` and `offset` query params
- `DELETE /api/admin/assets/{asset_id}` - Delete asset and all subtitle tracks
  - Requires: `X-Admin-Session-Id` header
  - Cascades delete to all asset's subtitle tracks
  - Deletes storage file if it exists
- `GET /api/admin/assets/{asset_id}/meta` - Get asset metadata
  - Requires: `X-Admin-Session-Id` header
  - Returns: `{ id, type, identifier, title, description, is_admin_upload }`
- `PATCH /api/admin/assets/{asset_id}/meta` - Update asset metadata
  - Requires: `X-Admin-Session-Id` header
  - Input: `{ "title": "...", "description": "..." }` (both optional)
  - Returns: Updated metadata object

### Admin Subtitle Track Management (NEW)
- `GET /api/admin/subtitle-tracks` - List all subtitle tracks
  - Requires: `X-Admin-Session-Id` header
  - Returns: `[{ id, asset_id, track_type, source, language, is_default, created_at }, ...]`
  - Supports pagination via `limit` and `offset` query params
- `DELETE /api/admin/subtitle-tracks/{track_id}` - Delete subtitle track
  - Requires: `X-Admin-Session-Id` header

## Maintenance Scripts

### Database Cleanup Script (`backend/scripts/cleanup_database.py`)

A standalone CLI tool to detect and clean up orphaned database records and storage files that can accumulate due to backend bugs or manual interventions.

**Types of Orphans Detected**:
1. **Orphaned SubtitleTracks**: Records referencing non-existent assets (referential integrity violations)
2. **Orphaned Assets**: Asset records with missing storage files (files deleted but DB records remain)
3. **Orphaned Files**: Storage files with no corresponding database record (files not tracked in DB)
4. **Orphaned Users**: Users with no assets (accumulated guest accounts, with optional age-based filtering)

**Usage**:
```bash
# Dry-run to see what would be deleted (default: True unless --force is used)
cd backend
python scripts/cleanup_database.py --dry-run --verbose

# Clean up orphaned subtitle tracks and assets only
python scripts/cleanup_database.py --force

# Clean up everything including orphaned files and users
python scripts/cleanup_database.py --force --cleanup-orphaned-files --cleanup-orphaned-users

# Clean up users older than 7 days with no assets
python scripts/cleanup_database.py --force --cleanup-orphaned-users --user-age-threshold 7
```

**CLI Arguments**:
- `--dry-run`: Report only, don't delete (default: True)
- `--force`: Actually perform deletions (required for any deletion)
- `--cleanup-orphaned-files`: Clean up storage files with no database record (default: False)
- `--cleanup-orphaned-users`: Clean up users with no assets (default: False)
- `--user-age-threshold`: Days threshold for user cleanup (default: 30)
- `--verbose, -v`: Detailed logging
- `--quiet, -q`: Minimal output

**Cleanup Order** (maintains referential integrity):
1. SubtitleTracks (no dependencies)
2. Assets (cascade to tracks)
3. Files (no DB dependencies)
4. Users (cascade to assets, but assets already verified)

**Safety Features**:
- Default dry-run mode requires explicit `--force` for actual deletions
- Graceful handling of missing storage files
- Comprehensive logging of all actions
- Idempotent (safe to run multiple times)

**Production Recommendations**:
- Run weekly via cron: `0 2 * * 0 cd /path/to/backend && python scripts/cleanup_database.py --cleanup-orphaned-users --user-age-threshold 30`
- Monitor cleanup statistics for anomalies (high orphan counts may indicate bugs)
- Always backup database before running with `--force`

## Data Models

### Database Models (Persistent Storage)

#### User
```python
{
  id: UUID,  # Primary key
  username: Optional[str],  # Explicit login (null for guests)
  password_hash: Optional[str],  # Hashed password
  created_at: DateTime,
}
```

#### Asset
```python
{
  id: UUID,  # Primary key
  type: Enum,  # "youtube" or "upload"
  identifier: str,  # YouTube ID or file SHA256 (unique index)
  storage_path: Optional[str],  # Only for UPLOAD type
  meta: Optional[dict],  # Title, description, duration, thumbnail URL
  created_by: UUID,  # FK -> User.id
  is_admin_upload: bool,  # True if uploaded by admin (default: False)
  created_at: DateTime,
}
```

#### SubtitleTrack
```python
{
  id: UUID,  # Primary key
  asset_id: UUID,  # FK -> Asset.id
  track_type: Enum,  # "raw" or "processed"
  source: Enum,  # "user_upload" or "ai_generated"
  language: str,  # ISO 639-1 (ja, zh, en) - auto-detected by Whisper
  content: dict,  # JSON with segments, metrics, and optional language_detection metadata
  is_default: bool,
  created_at: DateTime,
}
```

**Content Structure** (processed tracks):
```python
{
  "title": str,
  "segments": [...],  # Word-level segments with translations
  "metrics": {...},   # Processing metrics
  "has_word_timestamps": bool,
  "warnings": [...],
  "language_detection": {  # [NEW] Whisper language detection results
    "detected_language": str,  # ISO 639-1 code
    "language_probs": {str: float},  # All language probabilities
  }
}
```

### In-Memory Models (Session Management)

#### TaskInfo (for async task tracking)
```python
{
  task_id: str,
  status: TaskStatus,  # "pending" | "processing" | "completed" | "failed"
  progress: int,  # 0-100
  message: str,
  result: Optional[VideoResponse],  # Present when status is "completed"
  error: Optional[str]  # Present when status is "failed"
}
```

#### ProcessingMetrics
```python
{
  download_time: float,  # Seconds (0.0 for uploaded files)
  transcribe_time: float,  # Seconds
  analysis_time: float,  # Seconds (Japanese NLP)
  translation_time: float,  # Seconds
  total_time: float  # Seconds
}
```

#### VideoResponse
```python
{
  video_id: str,
  asset_id: Optional[str],  # Asset UUID for play page routing
  title: str,
  segments: List[Segment],
  metrics: Optional[ProcessingMetrics],  # None if processing failed
  has_word_timestamps: bool,  # False when using user-provided subtitles
  warnings: List[str],  # Warnings about subtitle similarity, etc.
}
```

#### Segment
```python
{
  words: List[Word],
  translation: str,
  start: float,
  end: float
}
```

#### Word
```python
{
  text: str,
  reading: Optional[str],  # Hiragana furigana
  start: float,
  end: float
}
```

#### AuthSession (for anonymous upload authentication)
```python
{
  session_id: str,  # UUID for session identification
  ip_address: str,  # IP address of session creator
  created_at: float,  # Unix timestamp
  expires_at: float,  # Unix timestamp (1 hour TTL by default)
  user_id: UUID,  # Links to DB User (persistent)
  upload_count: int,  # Number of uploads initiated (max 5)
  total_size: int,  # Total bytes uploaded (max 500MB)
}
```

## Environment Variables (.env)
- `DATABASE_URL` - Database connection string (default: sqlite:///./data/shadow.db)
- `STORAGE_ROOT_DIR` - Root directory for file storage (default: data/storage)
- `WHISPER_DEVICE` - GPU/CPU selection (cuda/cpu/None for auto, default: None)
- `WHISPER_FP16` - Half-precision inference (true/false, default: false)
- `WHISPER_MODEL_SIZE` - Model size (tiny/base/small/medium/large, default: base)
- `WHISPER_CONDITION_ON_PREVIOUS_TEXT` - Whether Whisper conditions on previous text (true/false, default: false). Setting to false reduces hallucinations and trailing text repetition, especially for Japanese content at end of audio files.
- `WHISPER_HALLUCINATION_SILENCE_THRESHOLD` - Silence threshold in seconds to skip when hallucination is detected (optional, default: None). Only used when word_timestamps is enabled.
- `GEMINI_API_KEY` - Google Gemini API key (required for translation)
- `GEMINI_MODEL_ID` - Gemini model (default: gemini-3-flash-preview)
- `TRANSLATE_BATCH_CHUNK_SIZE` - Translation batch size (default: 50)
- `SUBTITLE_SIMILARITY_THRESHOLD` - Similarity warning threshold (0.0-1.0, default: 0.1)
- `HTTP_PROXY` / `HTTPS_PROXY` - Optional proxy settings for YouTube downloads
- `UPLOAD_SESSION_TTL_SECONDS` - Chunked upload session TTL (default: 600)
- `UPLOAD_SESSION_SWEEP_SECONDS` - Sweep interval for expiring uploads (default: 60)
- `RATE_LIMIT_ENABLED` - Enable/disable rate limiting (true/false, default: true)
- `RATE_LIMIT_DEFAULT_REQUESTS_PER_MINUTE` - Default requests per minute for all endpoints (default: 60)
- `RATE_LIMIT_HEALTH_CHECK_PER_MINUTE` - Rate limit for / and /health endpoints (default: 120, currently exempt)
- `RATE_LIMIT_STATUS_PER_MINUTE` - Rate limit for /api/status/{task_id} endpoint (default: 120)
- `RATE_LIMIT_UPLOAD_PER_MINUTE` - Rate limit for /api/upload/* endpoints (default: 5)
- `RATE_LIMIT_PROCESS_PER_MINUTE` - Rate limit for /api/process endpoint (default: 5)
- `AUTH_SESSION_TTL_SECONDS` - Auth session TTL in seconds (default: 3600, 1 hour)
- `AUTH_SESSION_MAX_UPLOADS` - Max uploads per auth session (default: 5)
- `AUTH_SESSION_MAX_TOTAL_SIZE` - Max total upload size per session in bytes (default: 524288000, 500MB)
- `ADMIN_USERNAME` - Admin username for admin panel access (required for admin features)
- `ADMIN_PASSWORD` - Admin password for admin panel access (required for admin features)

## Key Features
1. **Video Input**: YouTube URL or local file upload (drag-and-drop supported)
2. **Audio Processing**: Download → Convert to MP3 → Whisper transcription
3. **Japanese NLP**: MeCab morphological analysis + automatic furigana generation
4. **Translation**: Batch translation via Google Gemini API
5. **Subtitle Alignment**: Align AI timestamps with reference subtitles, handle scrolling duplicates
6. **Interactive Playback**: Word-level highlighting, click-to-seek functionality
7. **PWA**: Offline support via Service Worker, installable app
8. **Admin Panel**: Admin interface for managing users, assets, and subtitle tracks (requires ADMIN_USERNAME/PASSWORD)
9. **Play Page Routing**: Dedicated play page via hash routing (`#/play/{asset_id}`), auto-redirect after processing
10. **Frontend Routing**: Hash-based SPA routing with `/` (home video grid), `/upload` (upload page), and `/play/{asset_id}` routes

## Important Implementation Details
- **Persistent Architecture**: Database-based storage with SQLite (easily upgradable to PostgreSQL via DATABASE_URL env var)
- **Repository Pattern**: `backend/db/crud.py` isolates business logic from database implementation
- **Asset Listing Pagination**: `get_all_assets` returns `(assets, total)` for paginated listings
- **SQLModel Typing**: CRUD query clauses are cast for Pyright compatibility without changing runtime behavior
- **Storage Abstraction**: `backend/services/storage/` provides unified async interface for local and future cloud storage; all persistent file operations (read/write/delete/stream) use storage abstraction consistently with chunked reads. LocalStorage implementation includes:
  - `iter_file()` method for chunked file iteration (supports Range requests for streaming)
  - Async methods: `save()`, `get()`, `delete()`, `exists()`, `get_file_size()`, `get_mime_type()`, `get_full_path()`
  - Hash-based storage: Files stored in `data/storage/{prefix}/{identifier}` where prefix is first 2 chars of hash
  - Directory cleanup: Empty parent directories are removed when last file is deleted
- **Hash-Based Storage**: Files stored in `data/storage/{prefix}/{identifier}` where prefix is first 2 chars of hash
- **Result Caching**: Processing results cached in SubtitleTrack table; checks cache before processing
- **Translation Guard**: Any translation failure (timeout/error/missing key) aborts processing and skips persistence
- **Guest User Auto-Creation**: Session creation automatically generates User record in DB
- **Deduplication**: Asset table uses unique constraint on (type, identifier) for fast duplicate detection
- **Async Processing**: Long-running tasks use background processing with task IDs
- **Settings**: Environment settings are centralized in `settings.py` and loaded once via `get_settings()`
- **Thread Pool**: A single shared `ThreadPoolExecutor` is used for CPU-bound tasks and translation batching
- **Background Tasks**: Managed by a TaskManager with a 5s drain window for graceful shutdown, then cancel
- **Whisper Queue**: Transcription is serialized (1 at a time) for both CPU and GPU devices
- **Download Offload**: YouTube downloads run in a background thread to avoid blocking the event loop
- **Thread-Local MeCab**: Analyzer uses per-thread Tagger instances for safe concurrent NLP
- **Upload I/O**: Upload writes and file hashing are offloaded to threads; chunked uploads track per-task session state to handle retries, reject out-of-order chunks, and validate total chunks/size; expired upload sessions are cleaned by a TTL sweeper
- **Frontend State**: Input/upload UI hides once `videoData` is available so the player/subtitle view is uncluttered
- **Furigana Logic**: Katakana → Hiragana conversion, handles special cases
- **Subtitle Calibration**: Character-level timestamp interpolation for precise alignment
- **Similarity Checking**: Validates user-provided subtitles against generated ones
- **Video ID Hashing**: Uploaded files get hashed video IDs for uniqueness
- **YouTube Player Sizing**: Frontend CSS enforces a 16:9 aspect ratio and iframe fill for `#youtube-player` to avoid collapsed embed height.
- **Play Page State**: Play-page loads reset playback/segment state; word highlighting respects per-asset `has_word_timestamps`; router init is non-blocking on health check while API base URL updates are propagated to the shared API client.
- **Frontend Docs**: Key frontend workflow functions and modules include JSDoc for easier navigation and maintenance.
- **Rate Limiting**: Implemented using slowapi (0.1.9) library with in-memory storage; different endpoints have different limits:
  - `/api/process`: 5/minute (expensive operation)
  - `/api/upload*`: 5/minute for upload/complete, 10/minute for subtitle, 300/minute for chunk
  - `/api/status/{task_id}`: 120/minute (frequent polling)
  - `/` and `/health`: exempt (no limit)
  - All other endpoints: 60/minute (default)
  - Rate limiter uses IP address as key, returns HTTP 429 when limit exceeded
  - Disable limits via `RATE_LIMIT_ENABLED=false` or `python main.py --no-rate-limit` (test runs)
- **Anonymous Authentication**: Upload endpoints require an anonymous session (via `/api/session`)
  - Client stores `session_id` and sends it via `X-Session-Id` header with configurable limits:
    - Max 5 uploads per session
    - Max 500MB total upload size per session
    - Session TTL: 1 hour (configurable)
  - Session creation rate limited: 10 requests per minute per IP
  - Expired sessions automatically cleaned every 60 seconds
  - YouTube URL processing (`/api/process`) accepts `X-Session-Id` when available to count toward session limits
  - Frontend auto-manages session: creates on first upload, reuses if valid, clears on 401 error
- **Admin Authentication**: Admin panel requires `ADMIN_USERNAME` and `ADMIN_PASSWORD` environment variables
  - Admin login via `POST /api/admin/login` returns admin session token
  - Admin session stored in `X-Admin-Session-Id` header for all admin requests
  - Admin sessions have 24-hour TTL and are cleaned every 5 minutes
  - Admin can view and delete any user-uploaded content (users, assets, subtitle tracks)
  - Storage file deletions resolve relative storage paths via the storage provider (or local hashed path fallback)
  - Frontend admin panel at `frontend/admin.html` provides tabbed interface for management
  - Asset identifiers in the admin assets table open the play page in a new tab
  - Admin uploads: When admin session is active, uploads are marked with `is_admin_upload=true`
  - Admin upload flow: After upload completes, edit modal appears for title/description before navigating to play page
  - Upload page shows "管理员模式" badge when admin session is detected
- **Frontend Routing**: Hash-based SPA routing for page navigation
  - Routes: `/` (home video grid), `/upload` (upload page), `/play/{asset_id}` (dedicated play page)
  - Home page displays responsive video grid with infinite scroll
  - Home grid cards navigate to play page on click
  - Auto-redirect to play page after processing completes (when `asset_id` is available)
  - Modular architecture: `router.js`, `api.js`, `player.js`, `subtitles.js`
  - Unified player interface supports both YouTube IFrame API and ArtPlayer
  - Direct URL access to play page via `#/play/{asset_id}` supported

## Running the Application

**Prerequisites**:
- Python 3.11+
- FFmpeg (for audio/video processing)
- uv (Python package manager)

**Backend**:
```bash
cd backend
export GEMINI_API_KEY="your_key"
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

**Backend (test, no rate limits)**:
```bash
cd backend
uv run python main.py --no-rate-limit --port 8000
```

**Frontend**:
```bash
cd frontend
python3 -m http.server 3000
```

Access at: http://localhost:3000

**Admin Panel**:
```bash
cd backend
export ADMIN_USERNAME="admin"
export ADMIN_PASSWORD="your_admin_password"
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Admin panel accessible at: http://localhost:3000/admin.html
