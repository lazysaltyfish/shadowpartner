"""Worker module for Whisper GPU offloading.

This module provides WebSocket-based communication for offloading Whisper
transcription to GPU workers that connect via reverse connection.
"""

from workers.manager import WorkerManager

__all__ = ["WorkerManager"]
