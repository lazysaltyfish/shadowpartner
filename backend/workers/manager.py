"""Worker manager for handling WebSocket connections from GPU workers."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Dict, Optional

from fastapi import WebSocket, WebSocketDisconnect

from utils.logger import get_logger
from workers.job_queue import JobQueue
from workers.models import (
    ErrorMessage,
    HeartbeatAckMessage,
    JobAssignedMessage,
    JobCompleteAckMessage,
    JobCompleteMessage,
    JobFailedMessage,
    JobProgressMessage,
    RegisteredMessage,
    RegisterMessage,
    WorkerCapabilities,
    WorkerInfo,
    WorkerStats,
    WorkerStatus,
)
from workers.storage_bridge import StorageBridge

logger = get_logger(__name__)


class WorkerManager:
    """Manages WebSocket connections from GPU workers."""

    def __init__(
        self,
        api_tokens: Dict[str, str],
        storage_bridge: StorageBridge,
        heartbeat_interval: int = 15,
        heartbeat_timeout: int = 30,
        job_timeout: int = 600,
    ):
        self.api_tokens = api_tokens
        self.storage_bridge = storage_bridge
        self.heartbeat_interval = heartbeat_interval
        self.heartbeat_timeout = heartbeat_timeout
        self.job_timeout = job_timeout

        self.workers: Dict[str, WorkerInfo] = {}
        self.job_queue = JobQueue(job_timeout_seconds=job_timeout)
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None

    def start(self):
        """Start background tasks."""
        self.job_queue.start()
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._heartbeat_checker())
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop(self):
        """Stop background tasks and close all connections."""
        await self.job_queue.stop()
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()

        # Close all WebSocket connections
        for worker in list(self.workers.values()):
            if worker.ws_connection:
                try:
                    await worker.ws_connection.close()
                except Exception:
                    pass

        self.workers.clear()
        logger.info("[WorkerManager] Stopped, all connections closed")

    async def handle_connection(self, websocket: WebSocket):
        """Handle a new WebSocket connection from a worker."""
        await websocket.accept()

        worker_id = None
        try:
            # First message must be register
            data = await websocket.receive_text()
            msg = json.loads(data)

            if msg.get("type") != "register":
                await self._send_error(
                    websocket, "INVALID_HANDSHAKE", "First message must be register"
                )
                await websocket.close()
                return

            register_msg = RegisterMessage(**msg)

            # Validate token
            if register_msg.worker_id not in self.api_tokens:
                await self._send_error(websocket, "INVALID_TOKEN", "Invalid worker token")
                await websocket.close()
                logger.warning(
                    f"[WorkerManager] Rejected connection from unknown worker: "
                    f"{register_msg.worker_id}"
                )
                return

            expected_token = self.api_tokens[register_msg.worker_id]
            if register_msg.token != expected_token:
                await self._send_error(websocket, "INVALID_TOKEN", "Invalid worker token")
                await websocket.close()
                logger.warning(
                    f"[WorkerManager] Rejected connection with invalid token: "
                    f"{register_msg.worker_id}"
                )
                return

            worker_id = register_msg.worker_id
            await self._register_worker(websocket, worker_id, register_msg.capabilities)

            # Send registered confirmation
            await websocket.send_json(
                RegisteredMessage(
                    type="registered",
                    worker_id=worker_id,
                    server_time=datetime.now().timestamp(),
                ).model_dump()
            )

            logger.info(f"[WorkerManager] Worker registered: {worker_id}")

            # Message loop
            await self._message_loop(websocket, worker_id)

        except json.JSONDecodeError as e:
            logger.error(f"[WorkerManager] JSON decode error: {e}")
            await self._send_error(websocket, "INVALID_JSON", str(e))
        except WebSocketDisconnect:
            logger.info(f"[WorkerManager] Worker disconnected: {worker_id}")
        except Exception as e:
            logger.error(f"[WorkerManager] Error handling connection: {e}", exc_info=True)
        finally:
            if worker_id:
                await self._unregister_worker(worker_id)

    async def _register_worker(
        self,
        websocket: WebSocket,
        worker_id: str,
        capabilities: Optional[WorkerCapabilities],
    ):
        """Register a new worker."""
        now = datetime.now()
        caps_dict = capabilities.model_dump() if capabilities else {}

        self.workers[worker_id] = WorkerInfo(
            worker_id=worker_id,
            status=WorkerStatus.IDLE,
            connected_at=now,
            last_heartbeat=now,
            capabilities=caps_dict,
            ws_connection=websocket,
        )

    async def _unregister_worker(self, worker_id: str):
        """Unregister a worker and reassign its job if any."""
        if worker_id not in self.workers:
            return

        worker = self.workers[worker_id]

        # Release any current job
        if worker.current_job_id:
            await self.job_queue.release_worker_job(worker_id)

        del self.workers[worker_id]
        logger.info(f"[WorkerManager] Worker unregistered: {worker_id}")

    async def _message_loop(self, websocket: WebSocket, worker_id: str):
        """Handle messages from a worker."""
        worker = self.workers.get(worker_id)
        if not worker:
            return

        try:
            while True:
                data = await websocket.receive_text()
                msg = json.loads(data)
                msg_type = msg.get("type")

                if msg_type == "heartbeat":
                    await self._handle_heartbeat(worker_id)

                elif msg_type == "job_complete":
                    await self._handle_job_complete(worker_id, JobCompleteMessage(**msg))

                elif msg_type == "job_progress":
                    await self._handle_job_progress(worker_id, JobProgressMessage(**msg))

                elif msg_type == "job_failed":
                    await self._handle_job_failed(worker_id, JobFailedMessage(**msg))

                else:
                    logger.warning(f"[WorkerManager] Unknown message type: {msg_type}")

        except WebSocketDisconnect:
            raise
        except Exception as e:
            logger.error(f"[WorkerManager] Error in message loop: {e}", exc_info=True)

    async def _handle_heartbeat(self, worker_id: str):
        """Handle heartbeat from worker."""
        worker = self.workers.get(worker_id)
        if worker:
            worker.last_heartbeat = datetime.now()

            # Send ack
            try:
                await worker.ws_connection.send_json(
                    HeartbeatAckMessage(
                        type="heartbeat_ack",
                        server_time=datetime.now().timestamp(),
                    ).model_dump()
                )
            except Exception as e:
                logger.warning(f"[WorkerManager] Failed to send heartbeat ack: {e}")

    async def _send_job_complete_ack(self, worker: WorkerInfo, job_id: str) -> None:
        if not worker.ws_connection:
            return
        try:
            await worker.ws_connection.send_json(
                JobCompleteAckMessage(type="job_complete_ack", job_id=job_id).model_dump()
            )
        except Exception as e:
            logger.warning(f"[WorkerManager] Failed to send job complete ack: {e}")

    async def _handle_job_complete(self, worker_id: str, msg: JobCompleteMessage):
        """Handle job completion from worker."""
        worker = self.workers.get(worker_id)
        if not worker:
            logger.warning(f"[WorkerManager] Job complete from unknown worker: {worker_id}")
            return

        job_id = msg.job_id
        result = msg.result

        job = self.job_queue.get_job(job_id)
        if not job or job.worker_id != worker_id:
            logger.warning(
                f"[WorkerManager] Stale job completion ignored: job={job_id} worker={worker_id}"
            )
            worker.current_job_id = None
            worker.status = WorkerStatus.IDLE
            await self._send_job_complete_ack(worker, job_id)
            await self._assign_next_job(worker_id)
            return

        if await self.job_queue.complete_job(job_id, result):
            worker.jobs_completed += 1
            worker.current_job_id = None
            worker.status = WorkerStatus.IDLE
            logger.info(f"[WorkerManager] Job complete: {job_id} by {worker_id}")

        await self._send_job_complete_ack(worker, job_id)

        # Assign next job if available
        await self._assign_next_job(worker_id)

    async def _handle_job_progress(self, worker_id: str, msg: JobProgressMessage):
        """Handle job progress update from worker."""
        job = self.job_queue.get_job(msg.job_id)
        if not job or job.worker_id != worker_id:
            logger.debug(
                f"[WorkerManager] Ignoring progress for stale job={msg.job_id} worker={worker_id}"
            )
            return
        await self.job_queue.update_progress(msg.job_id, msg.progress, msg.message)
        logger.debug(f"[WorkerManager] Job progress: {msg.job_id} ({msg.progress}%)")

    async def _handle_job_failed(self, worker_id: str, msg: JobFailedMessage):
        """Handle job failure from worker."""
        worker = self.workers.get(worker_id)
        if not worker:
            logger.warning(f"[WorkerManager] Job failed from unknown worker: {worker_id}")
            return

        job_id = msg.job_id
        error = msg.error

        job = self.job_queue.get_job(job_id)
        if not job or job.worker_id != worker_id:
            logger.warning(
                f"[WorkerManager] Stale job failure ignored: job={job_id} worker={worker_id}"
            )
            worker.current_job_id = None
            worker.status = WorkerStatus.IDLE
            await self._assign_next_job(worker_id)
            return

        if await self.job_queue.fail_job(job_id, error):
            worker.jobs_failed += 1
            worker.current_job_id = None
            worker.status = WorkerStatus.IDLE
            logger.warning(f"[WorkerManager] Job failed: {job_id} by {worker_id} - {error}")

        # Assign next job if available
        await self._assign_next_job(worker_id)

    async def _assign_next_job(self, worker_id: str):
        """Assign next available job to worker."""
        worker = self.workers.get(worker_id)
        if not worker or worker.status != WorkerStatus.IDLE:
            return

        job_id = await self.job_queue.assign_job(worker_id)
        if not job_id:
            return

        job = self.job_queue.get_job(job_id)
        if not job:
            return

        worker.status = WorkerStatus.BUSY
        worker.current_job_id = job_id

        # Build options based on job options and worker capabilities
        worker_model = worker.capabilities.get("model", "base")
        worker_fp16 = worker.capabilities.get("fp16", False)

        # Start with job options, then fill in worker-specific settings
        options = dict(job.options) if job.options else {}
        options.setdefault("language", "ja")
        options.setdefault("model_size", worker_model)
        options.setdefault("fp16", worker_fp16)

        # Send job assignment
        try:
            await worker.ws_connection.send_json(
                JobAssignedMessage(
                    type="job_assigned",
                    job_id=job_id,
                    audio_url=job.audio_url,
                    audio_size=0,  # TODO: Get actual file size
                    options=options,
                ).model_dump()
            )
            await self.job_queue.mark_processing(job_id)
            logger.info(
                f"[WorkerManager] Job assigned: {job_id} -> {worker_id} "
                f"(model={options.get('model_size')}, fp16={options.get('fp16')})"
            )
        except Exception as e:
            logger.error(f"[WorkerManager] Failed to assign job: {e}")
            worker.status = WorkerStatus.IDLE
            worker.current_job_id = None
            await self.job_queue.release_worker_job(worker_id)

    async def _heartbeat_checker(self):
        """Check for workers that haven't sent heartbeat recently."""
        while True:
            try:
                await asyncio.sleep(self.heartbeat_interval)

                offline_workers = []
                for worker_id, worker in list(self.workers.items()):
                    if not worker.is_alive(self.heartbeat_timeout):
                        offline_workers.append(worker_id)

                for worker_id in offline_workers:
                    logger.warning(f"[WorkerManager] Heartbeat timeout: {worker_id}")
                    await self._unregister_worker(worker_id)

                await self._assign_idle_workers()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[WorkerManager] Error in heartbeat checker: {e}")

    async def _cleanup_loop(self):
        """Periodic cleanup of expired resources."""
        while True:
            try:
                await asyncio.sleep(300)  # Every 5 minutes
                self.storage_bridge.cleanup_expired_signatures()
                await self.job_queue.cleanup_old_jobs()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[WorkerManager] Error in cleanup loop: {e}")

    async def _send_error(self, websocket: WebSocket, code: str, message: str):
        """Send an error message to the client."""
        try:
            await websocket.send_json(
                ErrorMessage(type="error", code=code, message=message).model_dump()
            )
        except Exception:
            pass

    def has_active_worker(self) -> bool:
        """Check if there's at least one active (idle or busy) worker."""
        return bool(self.workers)

    async def _assign_idle_workers(self):
        """Assign pending jobs to any idle workers."""
        for worker_id, worker in list(self.workers.items()):
            if worker.status == WorkerStatus.IDLE:
                await self._assign_next_job(worker_id)

    async def submit_transcribe_job(
        self,
        task_id: str,
        audio_path: str,
        audio_url: str,
        timeout: int = 600,
        options: Optional[dict] = None,
    ) -> dict:
        """Submit a transcription job to be processed by a worker.

        Args:
            task_id: The task ID for progress updates
            audio_path: Local storage path of the audio file
            audio_url: Pre-signed URL for worker download
            timeout: Maximum time to wait for completion
            options: Optional job options (language, model_size, etc.)

        Returns:
            The transcription result

        Raises:
            asyncio.TimeoutError: If job doesn't complete in time
            RuntimeError: If no workers are available
        """
        if not self.has_active_worker():
            raise RuntimeError("No workers available")

        # Create job with options
        job = await self.job_queue.create_job(task_id, audio_path, audio_url, options=options)

        # Try to assign immediately
        for worker_id, worker in self.workers.items():
            if worker.status == WorkerStatus.IDLE:
                await self._assign_next_job(worker_id)
                break

        # Wait for completion with timeout
        start_time = asyncio.get_event_loop().time()
        check_interval = 1.0

        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > timeout:
                raise asyncio.TimeoutError(f"Job {job.job_id} timed out after {timeout}s")

            job_status = self.job_queue.get_job(job.job_id)
            if not job_status:
                raise RuntimeError(f"Job {job.job_id} not found")

            if job_status.status.value in ("completed", "failed"):
                if job_status.status.value == "completed" and job_status.result:
                    return job_status.result
                raise RuntimeError(f"Job {job.job_id} failed: {job_status.error}")

            await asyncio.sleep(check_interval)

    def get_stats(self) -> WorkerStats:
        """Get statistics about workers and jobs."""
        idle = sum(1 for w in self.workers.values() if w.status == WorkerStatus.IDLE)
        busy = sum(1 for w in self.workers.values() if w.status == WorkerStatus.BUSY)
        queue_stats = self.job_queue.get_stats()

        return WorkerStats(
            connected=len(self.workers),
            idle=idle,
            busy=busy,
            pending_jobs=queue_stats["pending"],
            assigned_jobs=queue_stats["assigned"],
            processing_jobs=queue_stats["processing"],
            workers=[w.to_dict() for w in self.workers.values()],
        )
