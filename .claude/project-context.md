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
**ShadowPartner (影子跟读)** is a PWA for Japanese language learners that processes YouTube videos to generate interactive subtitles with word-level timing, furigana, and Chinese translations.

## Development Standards

### Code Formatting & Quality
- **Linter/Formatter**: **Ruff** is used for all Python code.
- **Line Length**: Maximum line length is set to **100** characters (configured in `backend/pyproject.toml`).
- **Imports**: `isort` rules are enabled via Ruff for automatic import sorting.
- **Strict Requirement**: AI assistants MUST ensure all code changes comply with these formatting rules.
- **Verification**: Before proposing or making a commit, you MUST run the following command in the `backend` directory to verify and fix formatting:
  ```bash
  cd backend && uv run ruff check --fix . && uv run ruff format .
  ```

## Tech Stack
- **Backend**: FastAPI (Python 3.11+) + Uvicorn
- **Frontend**: Vue 3 + Tailwind CSS (CDN-based)
- **Video Player**: ArtPlayer
- **Key Libraries**:
  - openai-whisper (transcription)
  - google-genai (translation via Gemini API)
  - mecab-python3 + unidic-lite (Japanese NLP)
  - yt-dlp (YouTube downloads)
  - FFmpeg (audio/video processing)

## Architecture

### Backend Structure (`/backend`)
```
main.py                        # FastAPI app factory + wiring
lifecycle.py                   # Startup/shutdown hooks
middleware.py                  # Request logging + CORS
routes.py                      # API endpoints
processing.py                  # Download/transcribe/analyze/translate pipeline
uploads.py                     # Upload sessions + sweeper + file helpers
models.py                      # Pydantic models + UploadSession
state.py                       # In-memory task store + upload sessions + executors
services_registry.py           # Service initialization + whisper lock (initialized on startup)
settings.py                    # Centralized environment settings loader
services/
  ├── downloader.py            # YouTube/file download
  ├── transcriber.py           # Whisper transcription
  ├── analyzer.py              # Japanese morphological analysis
  ├── aligner.py               # Timestamp alignment & calibration
  ├── translator.py            # Gemini translation
  ├── subtitle_linearizer.py   # Scrolling subtitle deduplication
  └── video_utils.py           # Video utilities
```

### Frontend Structure (`/frontend`)
```
index.html                    # Main HTML
js/app.js (670 lines)         # Vue 3 application
service-worker.js             # PWA offline support
manifest.json                 # PWA config
```

## Processing Pipeline

### Standard Pipeline (No User Subtitle)
```
Input (YouTube URL or File)
  → Download audio/video (downloader.py)
  → Whisper transcription with word timestamps (transcriber.py)
  → Japanese morphological analysis + furigana (analyzer.py)
  → Batch translate to Chinese (translator.py)
  → Return segments with interactive words
  → Frontend displays with click-to-seek
```

### Pipeline with User Subtitle
```
Input (File + User SRT Subtitle)
  → Whisper transcription for timing reference (transcriber.py)
  → Load user subtitle (transcriber.py)
  → Deduplicate scrolling subtitles (subtitle_linearizer.py)
  → Check similarity between AI and user subtitle (warns if < threshold)
  → Align & calibrate user subtitle with AI timestamps (aligner.py)
  → Japanese morphological analysis + furigana (analyzer.py)
  → Batch translate to Chinese (translator.py)
  → Return segments (no word-level timestamps, only segment-level)
  → Frontend displays with click-to-seek
```

## Key API Endpoints

### Video Processing
- `POST /api/process` - Process YouTube video by URL (async)
  - Input: `{ "url": "youtube_url" }`
  - Returns: `{ "task_id": "uuid", "message": "..." }`
  - Triggers background download and processing

### File Upload (Simple - for small files)
- `POST /api/upload` - Upload video/audio file with optional subtitle (async)
  - Input: `file` (required), `subtitle` (optional SRT file)
  - Returns: `{ "task_id": "uuid", "message": "..." }`
  - One-shot upload for files that can be sent in a single request

### Chunked Upload (for large files)
- `POST /api/upload/init` - Initialize chunked upload session
  - Input: `filename`, `total_chunks`, `total_size` (form data, required)
  - Returns: `{ "task_id": "uuid", "message": "..." }`
  - Creates empty file and task entry

- `POST /api/upload/chunk` - Upload a file chunk
  - Input: `task_id`, `chunk_index`, `file` (chunk data)
  - Returns: `{ "status": "success" }`
  - Appends chunk to the file (sequential upload)

- `POST /api/upload/subtitle` - Upload subtitle for chunked upload session
  - Input: `task_id`, `file` (SRT subtitle)
  - Returns: `{ "status": "success", "path": "..." }`
  - Saves subtitle file associated with the task

- `POST /api/upload/complete` - Complete chunked upload and start processing
  - Input: `task_id`, `filename`, `subtitle_filename` (optional), `total_chunks`, `total_size` (required)
  - Returns: `{ "task_id": "uuid", "message": "..." }`
  - Triggers background processing with optional subtitle

### Task Status
- `GET /api/status/{task_id}` - Get task status and progress
  - Returns: `TaskInfo` with status, progress, message, result/error

### Health Check
- `GET /` - API health check
  - Returns: `{ "message": "ShadowPartner API is running" }`

## Data Models

### TaskInfo (for async task tracking)
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

### ProcessingMetrics
```python
{
  download_time: float,  # Seconds (0.0 for uploaded files)
  transcribe_time: float,  # Seconds
  analysis_time: float,  # Seconds (Japanese NLP)
  translation_time: float,  # Seconds
  total_time: float  # Seconds
}
```

### VideoResponse
```python
{
  video_id: str,
  title: str,
  segments: List[Segment],
  metrics: Optional[ProcessingMetrics],  # None if processing failed
  has_word_timestamps: bool,  # False when using user-provided subtitles
  warnings: List[str]  # Warnings about subtitle similarity, etc.
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
  reading: Optional[str],  # Hiragana furigana
  start: float,
  end: float
}
```

## Environment Variables (.env)
- `WHISPER_DEVICE` - GPU/CPU selection (cuda/cpu/None for auto, default: None)
- `WHISPER_FP16` - Half-precision inference (true/false, default: false)
- `WHISPER_MODEL_SIZE` - Model size (tiny/base/small/medium/large, default: base)
- `GEMINI_API_KEY` - Google Gemini API key (required for translation)
- `GEMINI_MODEL_ID` - Gemini model (default: gemini-3-flash-preview)
- `TRANSLATE_BATCH_CHUNK_SIZE` - Translation batch size (default: 50)
- `SUBTITLE_SIMILARITY_THRESHOLD` - Similarity warning threshold (0.0-1.0, default: 0.1)
- `HTTP_PROXY` / `HTTPS_PROXY` - Optional proxy settings for YouTube downloads
- `UPLOAD_SESSION_TTL_SECONDS` - Chunked upload session TTL (default: 600)
- `UPLOAD_SESSION_SWEEP_SECONDS` - Sweep interval for expiring uploads (default: 60)

## Key Features
1. **Video Input**: YouTube URL or local file upload (drag-and-drop supported)
2. **Audio Processing**: Download → Convert to MP3 → Whisper transcription
3. **Japanese NLP**: MeCab morphological analysis + automatic furigana generation
4. **Translation**: Batch translation via Google Gemini API
5. **Subtitle Alignment**: Align AI timestamps with reference subtitles, handle scrolling duplicates
6. **Interactive Playback**: Word-level highlighting, click-to-seek functionality
7. **PWA**: Offline support via Service Worker, installable app

## Important Implementation Details
- **Stateless Architecture**: No database, in-memory task storage only
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

**Frontend**:
```bash
cd frontend
python -m http.server 3000
```

Access at: http://localhost:3000
