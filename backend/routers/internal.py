"""Internal API router for temp file access and other internal endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator

import aiofiles
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/internal", tags=["internal"])


def _get_worker_temp_dir() -> str:
    """Get the worker temp directory from services registry."""
    from services_registry import worker_temp_dir

    if not worker_temp_dir:
        raise RuntimeError(
            "Services not initialized. Call services_registry.init_services() at startup."
        )
    return worker_temp_dir


@router.get("/temp-file")
async def get_temp_file(path: str, sig: str):
    """Get a temporary file via pre-signed URL.

    This endpoint is used by GPU workers to download audio files
    for transcription. Access is controlled by signature validation.

    Supports two file sources:
    1. Storage files (path starts with "storage/")
    2. Worker temp files (absolute path in worker temp directory)
    """
    import services_registry

    storage_bridge = services_registry.storage_bridge
    if not storage_bridge:
        raise HTTPException(status_code=503, detail="Worker storage bridge not available")

    # Validate signature
    if not storage_bridge.validate_signature(path, sig):
        raise HTTPException(status_code=403, detail="Invalid or expired signature")

    # Determine content type based on extension
    if path.endswith(".mp3"):
        media_type = "audio/mpeg"
    elif path.endswith(".wav"):
        media_type = "audio/wav"
    elif path.endswith(".m4a"):
        media_type = "audio/mp4"
    elif path.endswith(".mp4"):
        media_type = "video/mp4"
    else:
        media_type = "application/octet-stream"

    async def _stream_file(file_path: Path, chunk_size: int = 1024 * 1024) -> AsyncIterator[bytes]:
        async with aiofiles.open(file_path, "rb") as handle:
            while True:
                chunk = await handle.read(chunk_size)
                if not chunk:
                    break
                yield chunk

    try:
        # Storage files use relative paths; absolute paths are worker temp files.
        if not Path(path).is_absolute():
            storage = services_registry.storage
            if storage is None:
                raise HTTPException(status_code=503, detail="Storage service not available")

            storage_path = path[8:] if path.startswith("storage/") else path
            try:
                if not await storage.exists(storage_path):
                    raise HTTPException(status_code=404, detail="File not found in storage")
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Storage lookup failed for {path}: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail="Error reading file metadata")

            return StreamingResponse(storage.iter_file(storage_path), media_type=media_type)

        # Check if path is within worker temp directory (security check)
        abs_path = Path(path).resolve()
        temp_dir = Path(_get_worker_temp_dir()).resolve()

        if not abs_path.is_relative_to(temp_dir):
            raise HTTPException(status_code=403, detail="Access denied: path outside temp dir")

        if not abs_path.exists():
            raise HTTPException(status_code=404, detail="File not found")

        try:
            async with aiofiles.open(abs_path, "rb"):
                pass
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to open temp file {abs_path}: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Error reading file")

        return StreamingResponse(_stream_file(abs_path), media_type=media_type)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to stream temp file {path}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error reading file")
