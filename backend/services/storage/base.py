from __future__ import annotations

from abc import ABC, abstractmethod
from typing import BinaryIO


class BaseStorage(ABC):
    """Abstract base class for storage providers."""

    @abstractmethod
    async def save(self, file_obj: BinaryIO, path: str) -> str:
        """Save file and return storage path.

        Args:
            file_obj: File-like object to save
            path: Relative path (identifier) for the file

        Returns:
            Full storage path to the saved file
        """
        pass

    @abstractmethod
    async def get(self, path: str) -> BinaryIO:
        """Get file by path.

        Args:
            path: Relative path to the file

        Returns:
            File-like object for reading
        """
        pass

    @abstractmethod
    async def delete(self, path: str) -> bool:
        """Delete file by path.

        Args:
            path: Relative path to the file

        Returns:
            True if deleted, False otherwise
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
    def get_full_path(self, path: str) -> str:
        """Get full filesystem path for a relative path.

        Args:
            path: Relative path to the file

        Returns:
            Full filesystem path
        """
        pass
