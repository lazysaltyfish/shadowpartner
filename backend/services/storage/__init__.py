"""Storage abstraction layer module."""

from .base import BaseStorage
from .local import LocalStorage

__all__ = ["BaseStorage", "LocalStorage"]
