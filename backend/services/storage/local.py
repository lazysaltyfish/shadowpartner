from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import BinaryIO

from services.storage.base import BaseStorage
from utils.logger import get_logger

logger = get_logger(__name__)


class LocalStorage(BaseStorage):
    """Local file system storage provider with hash-based directory structure."""

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

    def _get_full_path(self, identifier: str, filename: str) -> Path:
        """Get full path for a file."""
        hash_prefix_path = self._get_hash_prefix_path(identifier)
        hash_prefix_path.mkdir(parents=True, exist_ok=True)
        return hash_prefix_path / identifier

    async def save(self, file_obj: BinaryIO, identifier: str) -> str:
        """Save file and return storage path."""
        target_path = self._get_full_path(identifier, identifier)

        # Ensure parent directory exists
        target_path.parent.mkdir(parents=True, exist_ok=True)

        # Save file
        logger.info(f"Saving file to storage: {target_path}")

        def write_file():
            file_obj.seek(0)
            with open(target_path, "wb") as f:
                shutil.copyfileobj(file_obj, f)

        await asyncio.to_thread(write_file)

        # Return relative path (identifier)
        return str(identifier)

    async def get(self, path: str) -> BinaryIO:
        """Get file by path."""
        full_path = self._get_full_path(path, path)

        if not full_path.exists():
            raise FileNotFoundError(f"File not found: {full_path}")

        return open(full_path, "rb")

    async def delete(self, path: str) -> bool:
        """Delete file by path."""
        full_path = self._get_full_path(path, path)

        if not full_path.exists():
            return False

        def remove_file():
            try:
                full_path.unlink()
                return True
            except Exception as e:
                logger.warning(f"Failed to delete file {full_path}: {e}")
                return False

        return await asyncio.to_thread(remove_file)

    async def exists(self, path: str) -> bool:
        """Check if file exists."""
        full_path = self._get_full_path(path, path)

        def check_exists():
            return full_path.exists()

        return await asyncio.to_thread(check_exists)

    def get_full_path(self, path: str) -> str:
        """Get full filesystem path for a relative path."""
        full_path = self._get_full_path(path, path)
        return str(full_path)
