from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Optional

from pydantic import BaseModel


class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskInfo(BaseModel):
    task_id: str
    status: TaskStatus
    progress: int = 0  # 0 to 100
    message: str = "Waiting to start..."
    result: Optional[Any] = None
    error: Optional[str] = None


@dataclass
class UploadSession:
    task_id: str
    temp_file: str
    next_index: int = 0
    expected_total_chunks: Optional[int] = None
    expected_total_size: Optional[int] = None
    subtitle_path: Optional[str] = None
    updated_at: float = field(default_factory=time.time)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    completed: bool = False
    processing_started: bool = False


class VideoRequest(BaseModel):
    url: str


class ProcessingMetrics(BaseModel):
    download_time: float = 0.0
    transcribe_time: float = 0.0
    analysis_time: float = 0.0
    translation_time: float = 0.0
    total_time: float = 0.0


class Word(BaseModel):
    text: str
    reading: Optional[str] = None
    start: float
    end: float


class Segment(BaseModel):
    words: List[Word]
    translation: str
    start: float
    end: float


class VideoResponse(BaseModel):
    video_id: str
    title: str
    segments: List[Segment]
    metrics: Optional[ProcessingMetrics] = None
    # False when using user-provided subtitles (no word-level timing)
    has_word_timestamps: bool = True
    warnings: List[str] = []


class AsyncProcessResponse(BaseModel):
    task_id: str
    message: str
