# Auto Uploader (CLI)

Uploads YouTube URLs to the ShadowPartner backend and optionally groups assets
into playlists. Uses `X-CLI-Token` when `CLI_MAGIC_TOKEN` is configured on the
backend.

## Requirements
- Python 3.11+
- `uv` for dependency management

## Environment
- `CLI_MAGIC_TOKEN` (used by the CLI and backend)
- `BACKEND_BASE_URL` (defaults to `http://localhost:8000`)

## Setup (uv)
Install dependencies once:

```bash
uv sync --project tools/auto_uploader
```

## Usage
Set the CLI token (either env var or flag):

```bash
export CLI_MAGIC_TOKEN="your-token"
```

Single URL:

```bash
uv run --project tools/auto_uploader \
  python -m tools.auto_uploader \
  --url "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

List file (supports comments with `#`, `;`, or `//`):

```bash
uv run --project tools/auto_uploader \
  python -m tools.auto_uploader \
  --list urls.txt
```

Override token via CLI flag (optional):

```bash
uv run --project tools/auto_uploader \
  python -m tools.auto_uploader \
  --cli-token "your-token" \
  --url "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

Create a playlist while uploading:

```bash
uv run --project tools/auto_uploader \
  python -m tools.auto_uploader \
  --list urls.txt \
  --playlist-title "My Playlist" \
  --playlist-description "Imported URLs"
```

Clone a YouTube playlist into a new backend playlist:

```bash
uv run --project tools/auto_uploader \
  python -m tools.auto_uploader \
  --youtube-playlist "https://www.youtube.com/playlist?list=..."
```

## Notes
- The CLI always normalizes YouTube URLs to `https://www.youtube.com/watch?v=ID`.
- Batch failures are logged and skipped.
- Use `--sleep` to add delays between uploads.
- If `--url` contains a `list=` parameter, the CLI prompts to upload the entire playlist.
