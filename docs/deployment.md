# Deployment Guide

This document describes how to deploy ShadowPartner as three Docker images:
backend, worker, and frontend. The backend requires a worker to be online for
processing; when no worker is connected, `/api/process` and upload init/complete
return HTTP 503.

## Components

- Backend: FastAPI API + SQLite storage + processing pipeline control.
- Worker: Whisper + ffmpeg + MeCab NLP processing, connects via WebSocket.
- Frontend: Static SPA served by nginx on port 3000.

## URL and Network Assumptions

- Frontend calls the backend at `<hostname>:8000` by default.
  - See `frontend/js/composables/useBackend.js`.
  - If you want a different backend host/port, edit that file and rebuild the
    frontend image, or place a reverse proxy in front.
- Backend must expose HTTP and WebSocket on the same port (default 8000).
- Worker uses `BACKEND_WS_URL` to connect via WebSocket and needs the backend
  HTTP base URL to be reachable for file downloads.

## Required Environment Variables

Backend:
- `GEMINI_API_KEY` (required)
- `WORKER_API_TOKENS` (required JSON map, example below)
- `BACKEND_BASE_URL` (required; reachable by worker, e.g. `http://backend:8000`)
- `ADMIN_USERNAME`, `ADMIN_PASSWORD` (recommended for admin UI)

Worker:
- `BACKEND_WS_URL` (required, e.g. `ws://backend:8000/ws/worker`)
- `WORKER_ID` (required, must match key in `WORKER_API_TOKENS`)
- `WORKER_TOKEN` (required, must match value in `WORKER_API_TOKENS`)
- `WHISPER_MODEL_SIZE` (optional, default `base`)
- `WHISPER_DEVICE` (optional, `cpu` or `cuda`)
- `WHISPER_FP16` (optional, `true`/`false`)

Frontend:
- No runtime environment variables.
- The backend base URL is resolved in `frontend/js/composables/useBackend.js`.

## Data Persistence

Backend stores data under `/app/data`:
- `/app/data/shadow.db` (SQLite database)
- `/app/data/storage` (uploaded media + generated artifacts)

Mount `/app/data` to a host path for persistence (example shown below).

## Build Images

```bash
docker build -t shadowpartner-backend ./backend
docker build -t shadowpartner-worker ./worker
docker build -t shadowpartner-frontend ./frontend
```

## Run (Docker)

Create a shared network so backend and worker can reach each other:

```bash
docker network create shadowpartner
```

Backend:

```bash
docker run -d --name shadowpartner-backend \
  --network shadowpartner \
  -p 8000:8000 \
  -e GEMINI_API_KEY=your_key \
  -e WORKER_API_TOKENS='{"gpu-01":"your_secret_token"}' \
  -e BACKEND_BASE_URL=http://shadowpartner-backend:8000 \
  -e ADMIN_USERNAME=admin \
  -e ADMIN_PASSWORD=change_me \
  -v /srv/shadowpartner/data:/app/data \
  shadowpartner-backend
```

Worker (CPU example):

```bash
docker run -d --name shadowpartner-worker \
  --network shadowpartner \
  -e BACKEND_WS_URL=ws://shadowpartner-backend:8000/ws/worker \
  -e WORKER_ID=gpu-01 \
  -e WORKER_TOKEN=your_secret_token \
  -e WHISPER_DEVICE=cpu \
  shadowpartner-worker
```

Required worker env: `BACKEND_WS_URL`, `WORKER_ID`, `WORKER_TOKEN`.

Worker (GPU notes):
- The default worker image is based on `python:3.11-slim` and does not include
  CUDA libraries. For GPU use, build a custom worker image with a CUDA base and
  install a CUDA-enabled PyTorch wheel before `openai-whisper`.
- Run with `--gpus all` when using NVIDIA runtime.

Frontend:

```bash
docker run -d --name shadowpartner-frontend \
  -p 3000:3000 \
  shadowpartner-frontend
```

## Caddy Example (Static Frontend + Backend Proxy)

If you serve the static frontend and reverse-proxy the backend under the same
host, you can avoid rebuilding the frontend when the backend base URL changes.

```caddyfile
example.com {
  encode zstd gzip

  handle /api/* {
    reverse_proxy backend:8000
  }

  handle /ws/worker {
    reverse_proxy backend:8000
  }

  handle {
    root * /srv/shadowpartner/frontend
    try_files {path} /index.html
    file_server
  }
}
```

Notes:
- Replace `backend:8000` with your backend host/port (docker network name or IP).
- `/ws/worker` is the backend WebSocket endpoint for workers (not used by the frontend).

## Optional: Docker Compose (Example)

This is a minimal example to show wiring. Adjust to your environment.

```yaml
version: "3.9"
services:
  backend:
    image: shadowpartner-backend
    ports: ["8000:8000"]
    environment:
      GEMINI_API_KEY: "your_key"
      WORKER_API_TOKENS: '{"gpu-01":"your_secret_token"}'
      BACKEND_BASE_URL: "http://backend:8000"
    volumes:
      - /srv/shadowpartner/data:/app/data

  worker:
    image: shadowpartner-worker
    depends_on: [backend]
    environment:
      BACKEND_WS_URL: "ws://backend:8000/ws/worker"
      WORKER_ID: "gpu-01"
      WORKER_TOKEN: "your_secret_token"
      WHISPER_DEVICE: "cpu"

  frontend:
    image: shadowpartner-frontend
    ports: ["3000:3000"]
```

## Verification

Backend health (should show worker_available true when worker is connected):

```bash
curl http://localhost:8000/health
```

Frontend should be reachable at:

```text
http://localhost:3000
```

## Troubleshooting

- `/api/process` returns 503: worker is not connected or misconfigured.
- Worker auth fails: verify `WORKER_ID` and `WORKER_TOKEN` match
  `WORKER_API_TOKENS`.
- Worker cannot download files: ensure `BACKEND_BASE_URL` is reachable from the
  worker container (and is not a localhost-only URL).
