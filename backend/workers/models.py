"""Data models for worker management and job tracking."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    """Status of a transcription job."""

    PENDING = "pending"  # Waiting to be assigned
    ASSIGNED = "assigned"  # Assigned to a worker
    PROCESSING = "processing"  # Worker is processing
    COMPLETED = "completed"  # Completed successfully
    FAILED = "failed"  # Failed with error


class WorkerStatus(str, Enum):
    """Status of a connected worker."""

    OFFLINE = "offline"
    IDLE = "idle"  # Connected and available
    BUSY = "busy"  # Connected and processing


# Pydantic models for WebSocket messages


class WorkerCapabilities(BaseModel):
    """Worker capabilities reported during registration."""

    model: str = "base"
    device: str = "cuda"
    fp16: bool = False


class RegisterMessage(BaseModel):
    """Worker registration message (client → server)."""

    type: str = "register"
    token: str
    worker_id: str
    capabilities: Optional[WorkerCapabilities] = None


class RegisteredMessage(BaseModel):
    """Registration confirmation message (server → client)."""

    type: str = "registered"
    worker_id: str
    server_time: float


class JobAssignedMessage(BaseModel):
    """Job assignment message (server → client)."""

    type: str = "job_assigned"
    job_id: str
    audio_url: str
    audio_size: int
    options: dict = Field(default_factory=dict)


class JobCompleteMessage(BaseModel):
    """Job completion message (client → server)."""

    type: str = "job_complete"
    job_id: str
    result: dict


class JobCompleteAckMessage(BaseModel):
    """Job completion acknowledgment (server → client)."""

    type: str = "job_complete_ack"
    job_id: str


class JobProgressMessage(BaseModel):
    """Job progress message (client → server)."""

    type: str = "job_progress"
    job_id: str
    progress: int
    message: str


class JobFailedMessage(BaseModel):
    """Job failure message (client → server)."""

    type: str = "job_failed"
    job_id: str
    error: str


class HeartbeatMessage(BaseModel):
    """Heartbeat message (client → server)."""

    type: str = "heartbeat"


class HeartbeatAckMessage(BaseModel):
    """Heartbeat acknowledgment (server → client)."""

    type: str = "heartbeat_ack"
    server_time: float


class ErrorMessage(BaseModel):
    """Error message (server → client)."""

    type: str = "error"
    code: str
    message: str


# Dataclass models for internal state


@dataclass
class TranscribeJob:
    """Internal representation of a transcription job."""

    job_id: str
    task_id: str  # Associated task_id for progress updates
    audio_path: str  # Local audio path in storage
    audio_url: str  # Pre-signed URL for worker download
    status: JobStatus
    worker_id: Optional[str] = None  # Worker currently handling this job
    assigned_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    timeout_at: Optional[datetime] = None  # Timeout for this job
    retry_count: int = 0
    max_retries: int = 2
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    progress: int = 0
    progress_message: str = ""
    options: Dict[str, Any] = field(default_factory=dict)  # Job options (language, etc.)

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        return {
            "job_id": self.job_id,
            "task_id": self.task_id,
            "status": self.status.value,
            "worker_id": self.worker_id,
            "progress": self.progress,
            "message": self.progress_message,
        }


@dataclass
class WorkerInfo:
    """Information about a connected worker."""

    worker_id: str
    status: WorkerStatus
    connected_at: datetime
    last_heartbeat: datetime
    current_job_id: Optional[str] = None
    capabilities: Dict[str, Any] = field(default_factory=dict)
    jobs_completed: int = 0
    jobs_failed: int = 0
    ws_connection: Optional[Any] = None  # WebSocket connection

    def is_alive(self, timeout_seconds: int = 30) -> bool:
        """Check if worker is still alive based on heartbeat."""
        elapsed = (datetime.now() - self.last_heartbeat).total_seconds()
        return elapsed < timeout_seconds

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        return {
            "worker_id": self.worker_id,
            "status": self.status.value,
            "connected_at": self.connected_at.isoformat(),
            "last_heartbeat": self.last_heartbeat.isoformat(),
            "jobs_completed": self.jobs_completed,
            "jobs_failed": self.jobs_failed,
            "capabilities": self.capabilities,
        }


@dataclass
class WorkerStats:
    """Statistics about workers and jobs."""

    connected: int = 0
    idle: int = 0
    busy: int = 0
    pending_jobs: int = 0
    assigned_jobs: int = 0
    processing_jobs: int = 0
    workers: List[dict] = field(default_factory=list)
