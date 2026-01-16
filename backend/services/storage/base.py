from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import BinaryIO


class BaseStorage(ABC):
    """Abstract base class for storage providers.

    All methods are async to support both local and cloud storage.
    """

    @abstractmethod
    async def save(self, file_obj: BinaryIO, path: str) -> str:
        """Save file and return storage path.

        Args:
            file_obj: File-like object to save
            path: Relative path (identifier) for the file

        Returns:
            Storage path (same as input path, or full path for some providers)
        """
        pass

    @abstractmethod
    async def get(self, path: str) -> BinaryIO:
        """Get file by path.

        Args:
            path: Relative path to the file

        Returns:
            File-like object for reading (caller is responsible for closing it)

        Raises:
            FileNotFoundError: If file doesn't exist
        """
        pass

    @abstractmethod
    def iter_file(
        self,
        path: str,
        start: int | None = None,
        end: int | None = None,
        chunk_size: int = 8192,
    ) -> AsyncIterator[bytes]:
        """Iterate file content in chunks.

        Args:
            path: Relative path to the file
            start: Optional start byte offset (inclusive)
            end: Optional end byte offset (inclusive)
            chunk_size: Maximum chunk size to read per iteration

        Yields:
            Byte chunks of the file content

        Raises:
            FileNotFoundError: If file doesn't exist
        """
        pass

    @abstractmethod
    async def delete(self, path: str) -> bool:
        """Delete file by path.

        Args:
            path: Relative path to the file

        Returns:
            True if deleted, False if file didn't exist
        """
        pass

    @abstractmethod
    async def exists(self, path: str) -> bool:
        """Check if file exists.

        Args:
            path: Relative path to the file

        Returns:
            True if exists, False otherwise
        """
        pass

    @abstractmethod
    async def get_full_path(self, path: str) -> str:
        """Get full filesystem path for a relative path.

        For cloud storage, returns a URI or identifier.
        For local storage, returns absolute filesystem path.

        Args:
            path: Relative path to the file

        Returns:
            Full filesystem path or storage URI
        """
        pass

    @abstractmethod
    async def get_file_size(self, path: str) -> int:
        """Get file size in bytes.

        Args:
            path: Relative path to the file

        Returns:
            File size in bytes

        Raises:
            FileNotFoundError: If file doesn't exist
        """
        pass

    @abstractmethod
    async def get_mime_type(self, path: str) -> str:
        """Get MIME type for file.

        Args:
            path: Relative path to the file

        Returns:
            MIME type string (e.g., "video/mp4", "audio/mpeg")
        """
        pass
