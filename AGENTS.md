# ShadowPartner Project Context (High-Level)

## Update Policy
- For any change in backend/frontend/worker, update that subproject's `AGENTS.md`.
- Update this root `AGENTS.md` only when changes affect architecture or
  module-to-module communication (API contracts, worker protocol, shared storage
  layout).
- If a change is confined to a single subproject without cross-module impact,
  this root document does not need to be updated.

## Project Overview
**ShadowPartner (影子跟读)** is a PWA for Japanese language learners that processes
YouTube videos and uploaded videos to generate interactive subtitles with
word-level timing, furigana, and Chinese translations.

## Subprojects
- `backend/AGENTS.md` - API server, data models, processing pipeline, storage,
  backend tests, deployment.
- `frontend/AGENTS.md` - PWA UI, routing, player behavior, frontend tests,
  deployment.
- `worker/AGENTS.md` - GPU worker client, transcription/NLP, worker config,
  deployment.

## Tech Stack
- Backend: FastAPI (Python 3.11+) + Uvicorn, SQLModel + SQLite
- Frontend: Vue 3 + Tailwind CSS (CDN-based)
- Worker: Python + openai-whisper + MeCab + FFmpeg
- Players: YouTube IFrame API + ArtPlayer

## Architecture Overview
- **Backend** exposes REST endpoints, manages auth sessions, database, storage,
  and task orchestration.
- Admin subtitle track listings include `asset_title` for frontend display when available.
- Ingestion endpoints (`/api/process`, `/api/upload*`) are admin-only; admin asset responses no longer include uploader fields.
- **Worker** connects via WebSocket for transcription/NLP/thumbnail generation;
  processing requires an online worker.
- **Frontend** is a static PWA that consumes backend APIs and supports both
  YouTube URLs and uploaded files.

## High-Level Processing Flow
- Input (YouTube URL or upload) -> backend task -> worker transcription/NLP ->
  backend persists subtitle tracks -> frontend playback with interactive
  subtitles.
- User-subtitle uploads still rely on worker-generated timestamps; backend
  aligns and stores processed results.

## Repo Layout
- `backend/` - API server and data pipeline
- `frontend/` - PWA UI
- `worker/` - GPU worker client
- `docs/` - Deployment and documentation
- `data/` - Runtime data (git ignored)

## Git & Commit Standards
- Atomic commits per logical change.
- Subject: imperative mood, no trailing period, < 72 chars.
- Optional body uses `- ` bullets after a blank line.
- Do not add `Co-Authored-By` trailers.
