# ShadowPartner Worker Context

## Update Policy
- Update this file for any worker change (protocol, config, dependencies,
  processing behavior, deployment).
- Update root `AGENTS.md` only when changes affect architecture or
  backend <-> worker contracts.

## Responsibilities
- Standalone GPU worker client for transcription, Japanese NLP, and optional
  thumbnail generation.
- Connects to backend via WebSocket and streams results back.

## Worker Structure (`/worker`)
```
main.py                # Worker entry point
client.py              # WebSocket client with auto-reconnect + heartbeat
analyzer.py            # MeCab-based Japanese NLP
text_utils.py          # Whisper text cleanup
transcriber.py         # Whisper wrapper with progress reporting
downloader.py          # Audio file downloader with cache
config.py              # Configuration loader
logger.py              # Logging setup
setup_ffmpeg.py        # Auto-install ffmpeg/ffprobe into worker/bin
pyproject.toml         # Worker dependencies (uv)
requirements.txt       # Legacy pip snapshot (optional)
.env.example           # Configuration template
README.md              # Worker documentation
```

## Worker Architecture
- **WebSocket reverse connection**: `ws://backend:8000/ws/worker` (default)
- **Authentication**: token mapping in `WORKER_API_TOKENS`
- **Job flow**: backend generates pre-signed URL -> worker downloads ->
  worker transcribes (+ optional thumbnail) -> worker sends result
- **Completion ACK**: backend sends `job_complete_ack`; worker retains cached
  audio until ack, then cleans cache
- **Fault tolerance**: heartbeat (15s), timeout (30s), retry (max 2)
- **Progress reporting**: estimated from audio duration and processing rate

## Implementation Notes (Worker)
- Worker dependencies are managed via `pyproject.toml` (uv).\n  `requirements.txt` is legacy-only.
- MeCab tagger instances are thread-local to avoid cross-thread conflicts.
- FFmpeg/ffprobe can be auto-installed into `worker/bin` if missing.
- Whisper is lazy-imported in `transcriber.load_model()` to avoid GPU/torch init during test collection.
- Worker tests stub the `whisper` module early in `worker/tests/conftest.py` to prevent accidental GPU use.
- Worker tests force CPU-only runs by setting `CUDA_VISIBLE_DEVICES=""` and `PYTORCH_NO_CUDA=1` in `worker/tests/conftest.py`.
- FFmpeg setup helpers are unit-tested in `worker/tests/test_setup_ffmpeg.py` without network downloads.

## Environment Variables (.env)
- `BACKEND_WS_URL` - WebSocket URL (default: ws://localhost:8000/ws/worker)
- `WORKER_TOKEN` - Worker auth token (must match `WORKER_API_TOKENS`)
- `WORKER_ID` - Worker identifier (must match token map key)
- `WHISPER_MODEL_SIZE` - tiny/base/small/medium/large (default: base)
- `WHISPER_DEVICE` - cuda/cpu/None (auto, default: cuda)
- `WHISPER_FP16` - true/false (default: false)
- `AUDIO_CACHE_DIR` - Default `./cache/audio`
- `MAX_CACHE_SIZE_GB` - Default 10

## Testing Requirements
- Worker behavior is validated via backend tests:
```bash
cd backend && uv run pytest tests/test_worker_client.py tests/test_worker_manager.py
```
- If worker gains its own test suite, run from `worker/` as documented.
- Heartbeat tests mock `ws.closed = False` and patch `asyncio.sleep` to avoid long waits.

## Running the Worker
```bash
cd worker
cp .env.example .env
# Edit .env with backend URL and worker credentials
pip install uv
uv sync --no-dev
uv run python main.py
```

## Docker (Worker)
```bash
docker build -f worker/Dockerfile -t shadowpartner-worker .
```
