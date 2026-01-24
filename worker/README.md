# Whisper GPU Worker

Standalone worker process for offloading Whisper transcription to a GPU machine.
Connects to the ShadowPartner backend via WebSocket.

## Requirements

- Python 3.11+
- CUDA-capable GPU (recommended)
- FFmpeg (auto-installed on startup for Linux/Windows; manual install on macOS)

## Installation

```bash
# Install dependencies (uv)
pip install uv
uv sync --no-dev

# Copy and configure environment
cp .env.example .env
# Edit .env with your settings
```

## Configuration

Edit `.env` file:

```bash
BACKEND_WS_URL=ws://your-backend.com:8000/ws/worker
WORKER_TOKEN=your_secret_token
WORKER_ID=gpu-01
WHISPER_MODEL_SIZE=base  # tiny, base, small, medium, large
WHISPER_DEVICE=cuda      # cuda or cpu
WHISPER_FP16=false       # true for GPU with FP16 support
```

## Running

```bash
uv run python main.py
```

The worker will:
1. Load the Whisper model
2. Connect to the backend via WebSocket
3. Register with authentication token
4. Wait for transcription jobs
5. Automatically reconnect on disconnection

## Backend Setup

Add the worker to your backend `.env`:

```bash
WORKER_API_TOKENS={"gpu-01":"your_secret_token"}
BACKEND_BASE_URL=http://your-backend.com
```

## Architecture

```
┌─────────────────┐     WebSocket     ┌──────────────────┐
│  GPU Worker     │ ◄─────────────────► │   Backend        │
│                 │                     │                  │
│  - Whisper      │   job_assigned      │  - Job Queue    │
│  - Progress     │ ◄─────────────────► │  - Manager      │
│  - Reconnect   │   job_complete      │  - Storage       │
└─────────────────┘                     └──────────────────┘
       │                                          │
       │                                          │
       ▼                                          ▼
  Download audio                         Pre-signed URL
  from backend                           for file access
```

## Message Flow

1. **Register**: Worker sends token and capabilities
2. **Job Assigned**: Backend sends job with audio URL
3. **Download**: Worker downloads audio via HTTP
4. **Transcribe**: Worker runs Whisper with progress updates
5. **Complete**: Worker sends result back
6. **Next Job**: Worker requests next available job

## Progress Reporting

Since Whisper doesn't support native progress callbacks, the worker estimates progress based on:
- Audio duration
- Historical processing rate
- Updates every 5% or 5 seconds

## Troubleshooting

**Connection refused**
- Check BACKEND_WS_URL is correct
- Verify backend WebSocket server is running on port 8000
- Check firewall rules

**Authentication failed**
- Verify WORKER_TOKEN matches backend WORKER_API_TOKENS
- Verify WORKER_ID matches the key in backend tokens

**Transcription errors**
- Worker auto-installs FFmpeg into `worker/bin` when missing (Linux/Windows).
- Check FFmpeg is installed: `ffmpeg -version`
- Verify audio files can be downloaded
- Check GPU availability: `nvidia-smi`
