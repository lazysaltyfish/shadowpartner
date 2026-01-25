# ShadowPartner Backend Context

## Update Policy
- Update this file for any backend change (endpoints, models, pipeline, env vars,
  scripts, or storage behavior).
- Update root `AGENTS.md` only when backend changes affect architecture or
  backend <-> frontend/worker contracts.

## Responsibilities
- FastAPI API server, auth/session management, DB access, storage abstraction,
  background processing orchestration, and worker coordination.

## Code Formatting & Quality
- **Linter/Formatter**: Ruff (Python)
- **Type Checker / LSP**: Pyright
- **Line Length**: 100 (see `backend/pyproject.toml`)
- **Imports**: isort rules via Ruff

## Backend Exception Handling (FastAPI)
When catching exceptions in endpoints, re-raise `HTTPException` as-is:
```python
async def some_endpoint(...):
    try:
        ...
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
```

## Testing Requirements
```bash
cd backend && uv run ruff check --fix .
cd backend && uv run ruff format .
cd backend && uv run pyright    # optional but recommended
cd backend && uv run pytest tests/
```
- Warnings from project source (non-test files) are not allowed.
- If tests mutate env vars used by `get_settings()`, call
  `settings.get_settings.cache_clear()` to refresh cached config.

## Backend Structure (`/backend`)
```
main.py                        # FastAPI app factory + wiring
lifecycle.py                   # Startup/shutdown hooks
middleware.py                  # Request logging + CORS
rate_limiter.py                # Rate limiting singleton (slowapi wrapper)
api_policy.py                  # Centralized rate limit tier definitions
routers/                       # Modular router architecture
  ├── __init__.py              # Exports all routers
  ├── decorators.py            # Rate limit decorator
  ├── public.py                # Public endpoints (no auth required)
  ├── auth.py                  # Endpoints requiring X-Session-Id
  ├── admin_auth.py            # Admin login/logout (no auth required)
  ├── admin.py                 # Admin endpoints (users, assets, subtitles)
  ├── playlist.py              # Playlist management endpoints
  ├── internal.py              # Internal API for worker file access
  └── workers.py               # WebSocket endpoint for GPU workers
session_manager.py             # Anonymous auth session management + admin
processing.py                  # Download/transcribe/analyze/translate pipeline
uploads.py                     # Upload sessions + sweeper + storage integration
models.py                      # Pydantic models + UploadSession/AuthSession
state.py                       # In-memory task store + upload/admin sessions
workers/                       # GPU Worker server components
  ├── __init__.py              # WorkerManager export
  ├── models.py                # Worker data models
  ├── job_queue.py             # Async job queue with timeout and retry
  ├── storage_bridge.py        # Pre-signed URL generation for worker file access
  └── manager.py               # WebSocket server for worker connections
db/                            # Database module
  ├── __init__.py
  ├── engine.py                # Database engine (SQLite setup)
  ├── models.py                # SQLModel models
  └── crud.py                  # CRUD operations + admin CRUD
services_registry.py           # Service initialization + worker wiring
settings.py                    # Centralized environment settings loader
validators.py                  # Upload file validation (size/type/mime)
utils/
  ├── logger.py                # Logging
  ├── resilience.py            # Retry/backoff helpers
  └── task_manager.py          # Async task helpers
scripts/
  ├── cleanup_database.py      # Database cleanup script
  └── migrate_storage_prefix.py  # Storage migration script (legacy)
tests/                         # Unit tests
```

## Processing Pipeline
### Standard Pipeline (No User Subtitle)
```
Input (YouTube URL or File)
  -> Check cache (SubtitleTrack DB)
  -> [Cache hit] Return cached result
  -> [Cache miss] Download audio/video
  -> Transcribe with GPU Worker (required)
  -> [Worker offline] Task fails with error
  -> Japanese NLP + furigana (worker MeCab)
  -> Batch translate to Chinese
  -> Vocabulary extraction
  -> Save to DB (SubtitleTrack table)
  -> Return segments with interactive words
```

### Pipeline with User Subtitle
```
Input (File + User SRT Subtitle)
  -> Check cache (SubtitleTrack DB)
  -> [Cache hit] Return cached result
  -> [Cache miss] Whisper transcription for timing reference (worker-only)
  -> Load user subtitle
  -> Deduplicate scrolling subtitles
  -> Similarity check vs AI subtitle
  -> Align & calibrate user subtitle with AI timestamps
  -> Japanese NLP + furigana (worker MeCab)
  -> Batch translate to Chinese
  -> Vocabulary extraction
  -> Save to DB (SubtitleTrack table)
  -> Return segments (segment-level timestamps only)
```

## Key API Endpoints
### Authentication
- `POST /api/session` - Create anonymous session for upload access
  - Returns: `{ "session_id": "uuid", "expires_at": 1234567890 }`
  - Rate limit: 10 requests/min/IP
- `X-CLI-Token` - Optional automation header (when `CLI_MAGIC_TOKEN` is set)
  - Maps to both auth/admin sessions internally (no need to call `/api/session` or `/api/admin/login`)
  - Bypasses rate limiting and upload session caps for CLI tooling

### Video Processing
- `POST /api/process` - Process YouTube video by URL (async)
  - Input: `{ "url": "youtube_url" }`
  - Returns: `{ "task_id": "uuid", "message": "..." }`
  - Worker required (503 if offline)
  - Rate limit: 5 requests/min

### File Upload (Simple)
- `POST /api/upload` - Upload video/audio with optional subtitle (async)
  - Requires `X-Session-Id`
  - Validation: allowlist + max size 500MB
  - Worker required
  - Rate limit: 5 requests/min
  - Session limits: max 5 uploads, 500MB total

### Chunked Upload
- `POST /api/upload/init` - Init chunked upload session
- `POST /api/upload/chunk` - Upload chunk (sequential)
- `POST /api/upload/subtitle` - Upload subtitle for chunked session
- `POST /api/upload/complete` - Complete chunked upload and process
  - All endpoints require `X-Session-Id`
  - Rate limits: init/complete 5/min, subtitle 10/min, chunk 300/min

### Task Status
- `GET /api/status/{task_id}` - Get task status/progress
  - Rate limit: 120 requests/min

### Public Asset Access
- `GET /api/assets/{asset_id}` - Asset details or list (`asset_id=list`)
- `GET /api/assets/{asset_id}/thumbnail` - Stream upload thumbnail
- `GET /api/assets/{asset_id}/stream` - Stream upload media (Range supported)
- `GET /api/assets/{asset_id}/vocabulary` - Extracted vocabulary

### Health Check
- `GET /` - API heartbeat (exempt)
- `GET /health` - Comprehensive health check (exempt)

### Admin Authentication
- `POST /api/admin/login` - Admin login
- `POST /api/admin/logout` - Admin logout (requires `X-Admin-Session-Id`)

### Admin User Management
- `GET /api/admin/users` - List users
- `DELETE /api/admin/users/{user_id}` - Delete user + assets

### Admin Asset Management
- `GET /api/admin/assets` - List assets
- `DELETE /api/admin/assets/{asset_id}` - Delete asset + tracks
- `GET /api/admin/assets/{asset_id}/meta` - Get metadata
- `PATCH /api/admin/assets/{asset_id}/meta` - Update metadata

### Admin Subtitle Track Management
- `GET /api/admin/subtitle-tracks` - List subtitle tracks (includes `asset_title` when available)
- `DELETE /api/admin/subtitle-tracks/{track_id}` - Delete track

### Playlists
Public endpoints:
- `GET /api/playlists`
- `GET /api/playlists/{playlist_id}`
- `GET /api/playlists/{playlist_id}/items`
- `GET /api/playlists/{playlist_id}/context?asset_id={asset_id}`

Admin endpoints (require `X-Admin-Session-Id`):
- `POST /api/playlists`
- `PUT /api/playlists/{playlist_id}`
- `DELETE /api/playlists/{playlist_id}`
- `POST /api/playlists/{playlist_id}/items`
- `PUT /api/playlists/{playlist_id}/items/{asset_id}`
- `DELETE /api/playlists/{playlist_id}/items/{asset_id}`
- `GET /api/assets/search?q={term}`

## Implementation Notes (Backend)
- Storage abstraction lives under `backend/services/storage/` and is fully async.
  Local storage uses hashed paths `data/storage/{prefix}/{identifier}` and
  supports chunked iteration via `iter_file()`.
- Processing results are cached in `SubtitleTrack` and reused when available.
- Translation failures abort processing to avoid partial persistence.
- Guest users are auto-created when sessions are created.
- Upload sessions enforce per-session limits, reject out-of-order chunks, and
  are swept by a TTL sweeper.
- Ingestion endpoints (`/api/process`, `/api/upload*`) require admin sessions.
- Ingestion endpoints accept `X-CLI-Token` when `CLI_MAGIC_TOKEN` is configured.
- Assets no longer track uploader; `created_by` is deprecated and not returned by admin APIs.
- Worker-generated JPEG thumbnails are stored as `meta.thumbnail_path` and
  served from `/api/assets/{asset_id}/thumbnail`.
- Async tasks use a shared `ThreadPoolExecutor` and a `TaskManager` with a
  5s drain window for graceful shutdown.
- YouTube downloads are offloaded to a background thread to avoid blocking.
- Rate limiting uses slowapi; key limits: `/api/process` 5/min,
  `/api/upload*` 5/min (10/min for subtitle, 300/min for chunks),
  `/api/status` 120/min, `/` and `/health` exempt.
- Requests with `X-CLI-Token` bypass rate limiting.
- Anonymous sessions enforce max 5 uploads and 500MB total; sessions expire
  after 1 hour by default.
- Admin sessions use 24-hour TTL and are cleaned every 5 minutes.
- Playlist items use ordered positions; reorder uses an offset to avoid unique
  constraint collisions before normalization.
- CRUD uses typed casts to satisfy Pyright without changing runtime behavior.

## Maintenance Script: Database Cleanup
See `backend/scripts/cleanup_database.py` for orphan detection and cleanup.
Use `--dry-run` by default; `--force` is required for deletion.

## Data Models (Database)
### User
```python
{
  id: UUID,
  username: Optional[str],
  password_hash: Optional[str],
  created_at: DateTime,
}
```

### Asset
```python
{
  id: UUID,
  type: Enum,  # "youtube" or "upload"
  identifier: str,
  storage_path: Optional[str],
  meta: Optional[dict],
  created_by: Optional[UUID],  # deprecated (no longer populated)
  is_admin_upload: bool,
  created_at: DateTime,
}
```

### SubtitleTrack
```python
{
  id: UUID,
  asset_id: UUID,
  track_type: Enum,  # "raw" or "processed"
  source: Enum,  # "user_upload" or "ai_generated"
  language: str,
  content: dict,
  is_default: bool,
  created_at: DateTime,
}
```

### Playlist
```python
{
  id: UUID,
  title: str,
  description: Optional[str],
  cover_image: Optional[str],
  playlist_type: Enum,
  owner_type: Enum,
  owner_id: Optional[UUID],
  created_at: DateTime,
  updated_at: DateTime,
}
```

### PlaylistAsset
```python
{
  id: UUID,
  playlist_id: UUID,
  asset_id: UUID,
  position: int,
  cached_title: str,
  cached_thumbnail: Optional[str],
  added_at: DateTime,
}
```

### VocabularyItem
```python
{
  id: UUID,
  asset_id: UUID,
  word: str,
  reading: str,
  surface_form: str,
  jlpt_level: Optional[str],
  part_of_speech: str,
  meaning_cn: str,
  meaning_en: Optional[str],
  learning_note: Optional[str],
  start_time: float,
  end_time: float,
  context_sentence: str,
  created_at: DateTime,
}
```

### Content Structure (Processed Tracks)
```python
{
  "title": str,
  "segments": [...],
  "metrics": {...},
  "has_word_timestamps": bool,
  "warnings": [...],
  "language_detection": {
    "detected_language": str,
    "language_probs": {str: float},
  }
}
```

## In-Memory Models
### TaskInfo
```python
{
  task_id: str,
  status: TaskStatus,
  progress: int,
  message: str,
  result: Optional[VideoResponse],
  error: Optional[str]
}
```

### ProcessingMetrics
```python
{
  download_time: float,
  transcribe_time: float,
  analysis_time: float,
  translation_time: float,
  total_time: float
}
```

### VideoResponse
```python
{
  video_id: str,
  asset_id: Optional[str],
  title: str,
  segments: List[Segment],
  metrics: Optional[ProcessingMetrics],
  has_word_timestamps: bool,
  warnings: List[str],
}
```

### Segment
```python
{
  words: List[Word],
  translation: str,
  start: float,
  end: float
}
```

### Word
```python
{
  text: str,
  reading: Optional[str],
  start: float,
  end: float
}
```

### AuthSession
```python
{
  session_id: str,
  ip_address: str,
  created_at: float,
  expires_at: float,
  user_id: UUID,
  upload_count: int,
  total_size: int,
}
```

## Environment Variables (.env)
- `DATABASE_URL` - Default `sqlite:///./data/shadow.db`
- `STORAGE_ROOT_DIR` - Default `data/storage`
- `GEMINI_API_KEY` - Gemini API key (translation)
- `GEMINI_MODEL_ID` - Default `gemini-3-flash-preview`
- `TRANSLATE_BATCH_CHUNK_SIZE` - Default 50
- `SUBTITLE_SIMILARITY_THRESHOLD` - Default 0.1
- `HTTP_PROXY` / `HTTPS_PROXY` - Optional proxy for YouTube downloads
- `UPLOAD_SESSION_TTL_SECONDS` - Default 600
- `UPLOAD_SESSION_SWEEP_SECONDS` - Default 60
- `RATE_LIMIT_ENABLED` - Default true
- `RATE_LIMIT_DEFAULT_REQUESTS_PER_MINUTE` - Default 60
- `RATE_LIMIT_HEALTH_CHECK_PER_MINUTE` - Default 120 (currently exempt)
- `RATE_LIMIT_STATUS_PER_MINUTE` - Default 120
- `RATE_LIMIT_UPLOAD_PER_MINUTE` - Default 5
- `RATE_LIMIT_PROCESS_PER_MINUTE` - Default 5
- `AUTH_SESSION_TTL_SECONDS` - Default 3600
- `AUTH_SESSION_MAX_UPLOADS` - Default 5
- `AUTH_SESSION_MAX_TOTAL_SIZE` - Default 524288000
- `ADMIN_USERNAME` - Required for admin access
- `ADMIN_PASSWORD` - Required for admin access
- `CLI_MAGIC_TOKEN` - Optional automation token for `X-CLI-Token`
- `WORKER_WS_PORT` - WebSocket port (default 8000)
- `WORKER_API_TOKENS` - JSON mapping worker_id:token
- `WORKER_HEARTBEAT_INTERVAL` - Default 15
- `WORKER_HEARTBEAT_TIMEOUT` - Default 30
- `WORKER_JOB_TIMEOUT` - Default 600
- `WORKER_TRANSCRIBE_RETRY_ATTEMPTS` - Default 2
- `BACKEND_BASE_URL` - Default http://localhost:8000
- `TEMP_FILE_TTL` - Default 3600

## Running the Backend
```bash
cd backend
export GEMINI_API_KEY="your_key"
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

**No rate limits (test mode):**
```bash
cd backend
uv run python main.py --no-rate-limit --port 8000
```

## AI Workflow: Adding New APIs
1. Choose the router based on access level.
2. Apply rate limits via `@rate_limit()` with `request: Request`.
3. Run backend tests (see Testing Requirements).

## Docker (Backend)
```bash
docker build -f backend/Dockerfile -t shadowpartner-backend .
```
