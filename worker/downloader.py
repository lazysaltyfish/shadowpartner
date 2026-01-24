"""Audio file downloader for Whisper GPU Worker."""

from __future__ import annotations

import os

import aiohttp
from logger import get_logger

logger = get_logger(__name__)


class AudioDownloader:
    """Download audio files from pre-signed URLs."""

    def __init__(self, cache_dir: str):
        self.cache_dir = cache_dir
        self._ensure_cache_dir()

    def _ensure_cache_dir(self):
        """Create cache directory if it doesn't exist."""
        os.makedirs(self.cache_dir, exist_ok=True)

    def _get_cache_path(self, job_id: str, extension: str = "wav") -> str:
        """Get cache file path for a job."""
        return os.path.join(self.cache_dir, f"{job_id}.{extension}")

    async def download(
        self, url: str, job_id: str, extension: str = "wav"
    ) -> tuple[str, int]:
        """Download audio file from URL.

        Args:
            url: Pre-signed URL to download from
            job_id: Job ID for cache filename
            extension: File extension (default: wav)

        Returns:
            Tuple of (local_path, file_size)

        Raises:
            Exception: If download fails
        """
        dest_path = self._get_cache_path(job_id, extension)

        if os.path.exists(dest_path):
            existing_size = os.path.getsize(dest_path)
            if existing_size > 0:
                logger.info(
                    f"[Downloader] Using cached file: {dest_path} ({existing_size} bytes)"
                )
                return dest_path, existing_size
            os.remove(dest_path)

        logger.info(f"[Downloader] Starting download: {url} -> {dest_path}")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        raise Exception(f"Download failed: HTTP {resp.status}")

                    total_size = int(resp.headers.get("content-length", 0))
                    downloaded = 0
                    last_report = 0

                    with open(dest_path, "wb") as f:
                        async for chunk in resp.content.iter_chunked(8192):
                            f.write(chunk)
                            downloaded += len(chunk)

                            # Log progress every MB
                            if (
                                total_size > 0
                                and downloaded - last_report >= 1024 * 1024
                            ):
                                progress = downloaded / total_size * 100
                                logger.debug(f"[Downloader] Progress: {progress:.1f}%")
                                last_report = downloaded

            logger.info(
                f"[Downloader] Download complete: {dest_path} ({downloaded} bytes)"
            )
            return dest_path, downloaded

        except Exception as e:
            # Clean up partial download
            if os.path.exists(dest_path):
                os.remove(dest_path)
            raise Exception(f"Download failed: {e}") from e

    async def cleanup(self, job_id: str):
        """Remove downloaded file for a job.

        Args:
            job_id: Job ID to clean up
        """
        for ext in ["wav", "mp3", "m4a", "mp4"]:
            path = self._get_cache_path(job_id, ext)
            if os.path.exists(path):
                os.remove(path)
                logger.debug(f"[Downloader] Cleaned up: {path}")
                break

    def get_cache_size(self) -> int:
        """Get total cache size in bytes."""
        total = 0
        for root, _, files in os.walk(self.cache_dir):
            for file in files:
                path = os.path.join(root, file)
                total += os.path.getsize(path)
        return total

    async def cleanup_old_files(self, max_size_gb: int):
        """Clean up old files if cache exceeds max size.

        Args:
            max_size_gb: Maximum cache size in GB
        """
        max_bytes = max_size_gb * 1024 * 1024 * 1024
        current_size = self.get_cache_size()

        if current_size <= max_bytes:
            return

        logger.info(
            f"[Downloader] Cache size ({current_size / 1024 / 1024:.1f} MB) "
            f"exceeds limit ({max_size_gb} GB), cleaning up..."
        )

        # Get files sorted by modification time
        files = []
        for root, _, filenames in os.walk(self.cache_dir):
            for filename in filenames:
                path = os.path.join(root, filename)
                stat = os.stat(path)
                files.append((path, stat.st_mtime, stat.st_size))

        # Sort by modification time (oldest first)
        files.sort(key=lambda x: x[1])

        # Delete oldest files until under limit
        for path, _, size in files:
            if current_size <= max_bytes:
                break
            os.remove(path)
            current_size -= size
            logger.debug(f"[Downloader] Deleted old file: {path}")

        logger.info(
            f"[Downloader] Cleanup complete. New size: {current_size / 1024 / 1024:.1f} MB"
        )
