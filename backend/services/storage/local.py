from __future__ import annotations

import asyncio
import mimetypes
import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from typing import BinaryIO

import aiofiles

from services.storage.base import BaseStorage
from utils.logger import get_logger

logger = get_logger(__name__)


class LocalStorage(BaseStorage):
    """Local file system storage provider with hash-based directory structure.

    Uses Python native async operations (aiofiles) for optimal performance.
    """

    def __init__(self, root_dir: str = "data/storage"):
        """Initialize local storage.

        Args:
            root_dir: Root directory for file storage
        """
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _get_hash_prefix_path(self, identifier: str) -> Path:
        """Get path with hash prefix (first 2 chars of hash portion).

        This prevents too many files in a single directory.

        The identifier format is "upload_<hash>", where hash is a 16-char hex string.
        We extract the hash part and use its first 2 characters as directory prefix.

        Example: "upload_a1b2c3d4e5f6g7h8" -> "a1" -> "data/storage/a1/"
        """
        # Extract hash part after "upload_" prefix
        if identifier.startswith("upload_"):
            hash_part = identifier[7:]  # Remove "upload_" prefix
        else:
            hash_part = identifier

        # Use first 2 chars of hash as prefix
        if len(hash_part) < 2:
            prefix = "00"
        else:
            prefix = hash_part[:2]

        return self.root_dir / prefix

    def _get_full_path(self, identifier: str) -> Path:
        """Get full path for a file."""
        hash_prefix_path = self._get_hash_prefix_path(identifier)
        return hash_prefix_path / identifier

    async def save(self, file_obj: BinaryIO, path: str) -> str:
        """Save file and return storage path."""
        target_path = self._get_full_path(path)

        # Ensure parent directory exists
        target_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"Saving file to storage: {target_path}")

        def write_file() -> None:
            file_obj.seek(0)
            with open(target_path, "wb") as f:
                shutil.copyfileobj(file_obj, f, length=1024 * 1024)

        await asyncio.to_thread(write_file)

        logger.info(f"Saved file to storage: {target_path}")
        return str(path)

    async def get(self, path: str) -> BinaryIO:
        """Get file by path."""
        full_path = self._get_full_path(path)

        if not full_path.exists():
            raise FileNotFoundError(f"File not found: {full_path}")

        return open(full_path, "rb")

    def iter_file(
        self,
        path: str,
        start: int | None = None,
        end: int | None = None,
        chunk_size: int = 8192,
    ) -> AsyncIterator[bytes]:
        """Iterate file content in chunks."""
        full_path = self._get_full_path(path)

        async def iterator() -> AsyncIterator[bytes]:
            if not full_path.exists():
                raise FileNotFoundError(f"File not found: {full_path}")

            range_start = start
            if end is not None and range_start is None:
                range_start = 0

            remaining = None
            if range_start is not None and end is not None:
                remaining = end - range_start + 1
                if remaining <= 0:
                    return

            async with aiofiles.open(full_path, "rb") as f:
                if range_start is not None:
                    await f.seek(range_start)

                while True:
                    if remaining is None:
                        read_size = chunk_size
                    else:
                        if remaining <= 0:
                            break
                        read_size = min(chunk_size, remaining)

                    chunk = await f.read(read_size)
                    if not chunk:
                        break
                    yield chunk
                    if remaining is not None:
                        remaining -= len(chunk)

        return iterator()

    async def delete(self, path: str) -> bool:
        """Delete file by path."""
        full_path = self._get_full_path(path)

        if not full_path.exists():
            return False

        try:
            full_path.unlink()
            logger.info(f"Deleted file from storage: {path}")

            # Clean empty parent directories
            parent = full_path.parent
            if parent != self.root_dir:
                try:
                    parent.rmdir()  # Only removes if empty
                except OSError:
                    pass  # Directory not empty, ignore

            return True
        except Exception as e:
            logger.warning(f"Failed to delete file {path}: {e}")
            return False

    async def exists(self, path: str) -> bool:
        """Check if file exists."""
        full_path = self._get_full_path(path)
        return full_path.exists()

    async def get_full_path(self, path: str) -> str:
        """Get full filesystem path for a relative path."""
        full_path = self._get_full_path(path)
        return str(full_path)

    async def get_file_size(self, path: str) -> int:
        """Get file size in bytes."""
        full_path = self._get_full_path(path)

        if not full_path.exists():
            raise FileNotFoundError(f"File not found: {full_path}")

        return full_path.stat().st_size

    async def get_mime_type(self, path: str) -> str:
        """Get MIME type for file."""
        ext = Path(path).suffix
        mime_type, _ = mimetypes.guess_type(f"file{ext}")
        return mime_type or "application/octet-stream"
