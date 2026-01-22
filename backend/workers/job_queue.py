"""Job queue for managing transcription jobs."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from state import update_task
from utils.logger import get_logger
from workers.models import JobStatus, TranscribeJob

logger = get_logger(__name__)


class JobQueue:
    """Queue for managing transcription jobs with timeout and retry support."""

    def __init__(
        self,
        job_timeout_seconds: int = 600,
        max_retries: int = 2,
    ):
        self.jobs: Dict[str, TranscribeJob] = {}
        self.pending_queue: asyncio.Queue[str] = asyncio.Queue()
        self.worker_jobs: Dict[str, str] = {}  # worker_id -> job_id
        self.job_timeout_seconds = job_timeout_seconds
        self.max_retries = max_retries
        self._lock = asyncio.Lock()
        self._timeout_task: Optional[asyncio.Task] = None

    def start(self):
        """Start the timeout checker task."""
        if self._timeout_task is None or self._timeout_task.done():
            self._timeout_task = asyncio.create_task(self._timeout_checker())

    async def stop(self):
        """Stop the timeout checker task."""
        if self._timeout_task and not self._timeout_task.done():
            self._timeout_task.cancel()
            try:
                await self._timeout_task
            except asyncio.CancelledError:
                pass

    async def create_job(
        self,
        task_id: str,
        audio_path: str,
        audio_url: str,
        options: Optional[dict] = None,
    ) -> TranscribeJob:
        """Create a new transcription job."""
        job_id = str(uuid.uuid4())

        job = TranscribeJob(
            job_id=job_id,
            task_id=task_id,
            audio_path=audio_path,
            audio_url=audio_url,
            status=JobStatus.PENDING,
            max_retries=self.max_retries,
            options=options or {},
        )

        async with self._lock:
            self.jobs[job_id] = job
            await self.pending_queue.put(job_id)

        logger.info(f"[JobQueue] Job created: {job_id} for task {task_id}")
        return job

    async def get_next_job(self) -> Optional[TranscribeJob]:
        """Get the next pending job."""
        if self.pending_queue.empty():
            return None

        job_id = await self.pending_queue.get()

        async with self._lock:
            job = self.jobs.get(job_id)
            if job and job.status == JobStatus.PENDING:
                return job
            # Job might have been cancelled or updated
            return None

    async def assign_job(self, worker_id: str) -> Optional[str]:
        """Assign a job to a worker. Returns job_id or None."""
        job = await self.get_next_job()
        if not job:
            return None

        async with self._lock:
            job.status = JobStatus.ASSIGNED
            job.worker_id = worker_id
            job.assigned_at = datetime.now()
            job.timeout_at = datetime.now() + timedelta(seconds=self.job_timeout_seconds)
            self.worker_jobs[worker_id] = job.job_id

            # Update task status
            update_task(
                job.task_id,
                JobStatus.PROCESSING.value,  # type: ignore
                10,
                f"Transcribing on worker {worker_id}...",
            )

        logger.info(f"[JobQueue] Job assigned: {job.job_id} -> worker {worker_id}")
        return job.job_id

    async def mark_processing(self, job_id: str) -> bool:
        """Mark a job as being processed."""
        async with self._lock:
            job = self.jobs.get(job_id)
            if job and job.status == JobStatus.ASSIGNED:
                job.status = JobStatus.PROCESSING
                job.started_at = datetime.now()
                logger.info(f"[JobQueue] Job processing: {job_id}")
                return True
            return False

    async def complete_job(self, job_id: str, result: dict) -> bool:
        """Mark a job as completed."""
        async with self._lock:
            job = self.jobs.get(job_id)
            if not job:
                logger.warning(f"[JobQueue] Complete unknown job: {job_id}")
                return False

            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.now()
            job.result = result
            job.progress = 100
            job.progress_message = "Complete"

            # Clear worker association
            if job.worker_id and job.worker_id in self.worker_jobs:
                del self.worker_jobs[job.worker_id]

            logger.info(f"[JobQueue] Job completed: {job_id}")
            return True

    async def fail_job(self, job_id: str, error: str) -> bool:
        """Mark a job as failed."""
        async with self._lock:
            job = self.jobs.get(job_id)
            if not job:
                logger.warning(f"[JobQueue] Fail unknown job: {job_id}")
                return False

            await self._retry_or_fail(job, error=error)

            # Clear worker association
            if job.worker_id and job.worker_id in self.worker_jobs:
                del self.worker_jobs[job.worker_id]

            return True

    async def update_progress(self, job_id: str, progress: int, message: str) -> bool:
        """Update job progress."""
        async with self._lock:
            job = self.jobs.get(job_id)
            if job:
                job.progress = progress
                job.progress_message = message

                # Forward to task
                update_task(
                    job.task_id,
                    JobStatus.PROCESSING.value,  # type: ignore
                    progress,
                    message,
                )
                return True
            return False

    async def _retry_or_fail(self, job: TranscribeJob, error: Optional[str] = None):
        """Retry job or mark as permanently failed."""
        if error:
            job.error = error
        job.retry_count += 1

        if job.retry_count > job.max_retries:
            job.status = JobStatus.FAILED
            job.completed_at = datetime.now()
            job.worker_id = None
            job.assigned_at = None
            job.timeout_at = None
            if job.error:
                job.progress_message = job.error
            else:
                job.progress_message = "Job failed"
            logger.error(f"[JobQueue] Job failed after {job.max_retries} retries: {job.job_id}")
        else:
            # Re-queue for retry
            job.status = JobStatus.PENDING
            job.worker_id = None
            job.assigned_at = None
            job.timeout_at = None
            job.error = None
            job.progress = 0
            job.progress_message = "Retrying..."
            await self.pending_queue.put(job.job_id)
            logger.warning(
                f"[JobQueue] Job requeued: {job.job_id} (retry {job.retry_count}/{job.max_retries})"
            )

    async def release_worker_job(self, worker_id: str) -> Optional[str]:
        """Release a job from a worker (worker disconnected). Returns job_id if any."""
        async with self._lock:
            job_id = self.worker_jobs.pop(worker_id, None)
            if job_id:
                job = self.jobs.get(job_id)
                if job and job.status in (JobStatus.ASSIGNED, JobStatus.PROCESSING):
                    await self._retry_or_fail(job, error="Worker disconnected")
                    logger.info(f"[JobQueue] Released job from worker: {job_id}")
                    return job_id
        return None

    async def _timeout_checker(self):
        """Check for timed out jobs periodically."""
        while True:
            try:
                await asyncio.sleep(30)  # Check every 30 seconds
                await self.check_timeouts()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[JobQueue] Error in timeout checker: {e}", exc_info=True)

    async def check_timeouts(self) -> List[str]:
        """Check for timed out jobs and requeue them. Returns list of timed out job IDs."""
        now = datetime.now()
        timed_out = []

        async with self._lock:
            for job_id, job in list(self.jobs.items()):
                if (
                    job.status in (JobStatus.ASSIGNED, JobStatus.PROCESSING)
                    and job.timeout_at
                    and now > job.timeout_at
                ):
                    logger.warning(f"[JobQueue] Job timed out: {job_id}")
                    await self._retry_or_fail(job, error="Job timed out")

                    # Clear worker association
                    if job.worker_id and job.worker_id in self.worker_jobs:
                        del self.worker_jobs[job.worker_id]

                    timed_out.append(job_id)

        return timed_out

    def get_job(self, job_id: str) -> Optional[TranscribeJob]:
        """Get a job by ID."""
        return self.jobs.get(job_id)

    async def get_job_status(self, job_id: str) -> Optional[dict]:
        """Get job status as dict."""
        job = self.jobs.get(job_id)
        if job:
            return job.to_dict()
        return None

    def get_stats(self) -> dict:
        """Get queue statistics."""
        pending = self.pending_queue.qsize()
        assigned = sum(1 for j in self.jobs.values() if j.status == JobStatus.ASSIGNED)
        processing = sum(1 for j in self.jobs.values() if j.status == JobStatus.PROCESSING)

        return {
            "pending": pending,
            "assigned": assigned,
            "processing": processing,
            "total": len(self.jobs),
        }

    async def cleanup_old_jobs(self, older_than_hours: int = 24):
        """Remove completed/failed jobs older than specified hours."""
        cutoff = datetime.now() - timedelta(hours=older_than_hours)
        removed = []

        async with self._lock:
            for job_id, job in list(self.jobs.items()):
                if (
                    job.status in (JobStatus.COMPLETED, JobStatus.FAILED)
                    and job.completed_at
                    and job.completed_at < cutoff
                ):
                    del self.jobs[job_id]
                    removed.append(job_id)

        if removed:
            logger.info(f"[JobQueue] Cleaned up {len(removed)} old jobs")
