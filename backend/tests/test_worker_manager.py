"""Tests for WorkerManager and worker-related functionality."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import WebSocket, WebSocketDisconnect

from workers.manager import WorkerManager
from workers.models import (
    JobCompleteMessage,
    JobFailedMessage,
    JobProgressMessage,
    RegisterMessage,
    WorkerCapabilities,
    WorkerStatus,
)
from workers.storage_bridge import StorageBridge


@pytest.fixture
def mock_storage_bridge():
    """Create a mock storage bridge."""
    bridge = Mock(spec=StorageBridge)
    bridge.validate_signature = Mock(return_value=True)
    bridge.generate_signature = Mock(return_value="test_signature")
    bridge.revoke_signature = Mock()
    bridge.cleanup_expired_signatures = Mock()
    return bridge


@pytest.fixture
def worker_manager(mock_storage_bridge):
    """Create a WorkerManager instance for testing."""
    api_tokens = {"worker_1": "token_1", "worker_2": "token_2"}
    manager = WorkerManager(
        api_tokens=api_tokens,
        storage_bridge=mock_storage_bridge,
        heartbeat_interval=1,
        heartbeat_timeout=3,
        job_timeout=10,
    )
    yield manager
    # Cleanup
    asyncio.run(manager.stop())


@pytest.fixture
def mock_websocket():
    """Create a mock WebSocket."""
    ws = Mock(spec=WebSocket)
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    ws.send_text = AsyncMock()
    ws.receive_text = AsyncMock()
    ws.close = AsyncMock()
    ws.closed = False
    return ws


class TestWorkerManagerInitialization:
    """Test WorkerManager initialization and basic properties."""

    def test_init_with_defaults(self, mock_storage_bridge):
        """Test initialization with default parameters."""
        manager = WorkerManager(
            api_tokens={"worker_1": "token_1"},
            storage_bridge=mock_storage_bridge,
        )
        assert manager.heartbeat_interval == 15
        assert manager.heartbeat_timeout == 30
        assert manager.job_timeout == 600
        assert len(manager.workers) == 0

    def test_init_with_custom_params(self, mock_storage_bridge):
        """Test initialization with custom parameters."""
        manager = WorkerManager(
            api_tokens={"worker_1": "token_1"},
            storage_bridge=mock_storage_bridge,
            heartbeat_interval=5,
            heartbeat_timeout=10,
            job_timeout=300,
        )
        assert manager.heartbeat_interval == 5
        assert manager.heartbeat_timeout == 10
        assert manager.job_timeout == 300

    def test_has_active_worker_empty(self, worker_manager):
        """Test has_active_worker returns False when no workers."""
        assert worker_manager.has_active_worker() is False

    def test_has_active_worker_with_worker(self, worker_manager, mock_websocket):
        """Test has_active_worker returns True when workers are connected."""
        # Register a worker
        asyncio.run(
            worker_manager._register_worker(
                mock_websocket,
                "worker_1",
                WorkerCapabilities(model="base", device="cuda", fp16=False),
            )
        )
        assert worker_manager.has_active_worker() is True


class TestWorkerRegistration:
    """Test worker registration and authentication."""

    @pytest.mark.asyncio
    async def test_register_worker_success(self, worker_manager, mock_websocket):
        """Test successful worker registration."""
        await worker_manager._register_worker(
            mock_websocket,
            "worker_1",
            WorkerCapabilities(model="base", device="cuda", fp16=False),
        )

        assert "worker_1" in worker_manager.workers
        worker = worker_manager.workers["worker_1"]
        assert worker.worker_id == "worker_1"
        assert worker.status.value == "idle"
        assert worker.ws_connection == mock_websocket
        assert worker.capabilities == {"model": "base", "device": "cuda", "fp16": False}

    @pytest.mark.asyncio
    async def test_unregister_worker(self, worker_manager, mock_websocket):
        """Test worker unregistration."""
        await worker_manager._register_worker(
            mock_websocket,
            "worker_1",
            WorkerCapabilities(model="base", device="cuda", fp16=False),
        )
        assert "worker_1" in worker_manager.workers

        await worker_manager._unregister_worker("worker_1")
        assert "worker_1" not in worker_manager.workers

    @pytest.mark.asyncio
    async def test_unregister_nonexistent_worker(self, worker_manager):
        """Test unregistering a non-existent worker (should not raise error)."""
        await worker_manager._unregister_worker("nonexistent")
        # Should not raise any exception

    @pytest.mark.asyncio
    async def test_unregister_worker_with_job(self, worker_manager, mock_websocket):
        """Test unregistering a worker that has a current job."""
        await worker_manager._register_worker(
            mock_websocket,
            "worker_1",
            WorkerCapabilities(model="base", device="cuda", fp16=False),
        )

        # Simulate worker having a job
        worker = worker_manager.workers["worker_1"]
        worker.current_job_id = "test_job_123"

        # Mock job_queue.release_worker_job
        with patch.object(
            worker_manager.job_queue,
            "release_worker_job",
            new_callable=AsyncMock,
        ) as mock_release:
            await worker_manager._unregister_worker("worker_1")
            mock_release.assert_called_once_with("worker_1")


class TestHandleConnection:
    """Test handle_connection method."""

    @pytest.mark.asyncio
    async def test_handle_connection_invalid_first_message(self, worker_manager, mock_websocket):
        """Test connection rejected when first message is not register."""
        mock_websocket.receive_text.return_value = json.dumps({"type": "invalid"})

        await worker_manager.handle_connection(mock_websocket)

        mock_websocket.send_json.assert_called()
        mock_websocket.close.assert_called()

    @pytest.mark.asyncio
    async def test_handle_connection_invalid_token(self, worker_manager, mock_websocket):
        """Test connection rejected with invalid token."""
        register_msg = RegisterMessage(
            type="register",
            worker_id="unknown_worker",
            token="wrong_token",
            capabilities=WorkerCapabilities(model="base", device="cuda", fp16=False),
        )
        mock_websocket.receive_text.return_value = json.dumps(register_msg.model_dump())

        await worker_manager.handle_connection(mock_websocket)

        mock_websocket.send_json.assert_called()
        mock_websocket.close.assert_called()

    @pytest.mark.asyncio
    async def test_handle_connection_wrong_token(self, worker_manager, mock_websocket):
        """Test connection rejected with wrong token for known worker."""
        register_msg = RegisterMessage(
            type="register",
            worker_id="worker_1",
            token="wrong_token",
            capabilities=WorkerCapabilities(model="base", device="cuda", fp16=False),
        )
        mock_websocket.receive_text.return_value = json.dumps(register_msg.model_dump())

        await worker_manager.handle_connection(mock_websocket)

        mock_websocket.send_json.assert_called()
        mock_websocket.close.assert_called()

    @pytest.mark.asyncio
    async def test_handle_connection_success(self, worker_manager, mock_websocket):
        """Test successful connection handling."""
        register_msg = RegisterMessage(
            type="register",
            worker_id="worker_1",
            token="token_1",
            capabilities=WorkerCapabilities(model="base", device="cuda", fp16=False),
        )
        mock_websocket.receive_text.return_value = json.dumps(register_msg.model_dump())

        # Track if worker was registered during message loop
        worker_registered_during_loop = False

        async def mock_message_loop(websocket, worker_id):
            nonlocal worker_registered_during_loop
            # Check if worker is registered during message loop
            worker_registered_during_loop = "worker_1" in worker_manager.workers
            await asyncio.sleep(0.1)

        with patch.object(worker_manager, "_message_loop", new_callable=AsyncMock) as mock_loop:
            mock_loop.side_effect = mock_message_loop
            await worker_manager.handle_connection(mock_websocket)

        mock_websocket.accept.assert_called()
        # Worker should have been registered during the message loop
        assert worker_registered_during_loop is True

    @pytest.mark.asyncio
    async def test_handle_connection_json_error(self, worker_manager, mock_websocket):
        """Test connection handling with JSON decode error."""
        mock_websocket.receive_text.return_value = "invalid json"

        await worker_manager.handle_connection(mock_websocket)

        # Should send error message but not close connection
        mock_websocket.send_json.assert_called()
        mock_websocket.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_connection_websocket_disconnect(self, worker_manager, mock_websocket):
        """Test connection handling with WebSocket disconnect."""
        mock_websocket.receive_text.side_effect = WebSocketDisconnect()

        await worker_manager.handle_connection(mock_websocket)

        # Should not raise exception, worker should be unregistered
        assert "worker_1" not in worker_manager.workers


class TestHeartbeat:
    """Test heartbeat handling."""

    @pytest.mark.asyncio
    async def test_handle_heartbeat(self, worker_manager, mock_websocket):
        """Test heartbeat updates worker's last_heartbeat."""
        await worker_manager._register_worker(
            mock_websocket, "worker_1", WorkerCapabilities(model="base", device="cuda", fp16=False)
        )

        worker = worker_manager.workers["worker_1"]
        old_heartbeat = worker.last_heartbeat

        await asyncio.sleep(0.1)
        await worker_manager._handle_heartbeat("worker_1")

        assert worker.last_heartbeat > old_heartbeat
        mock_websocket.send_json.assert_called()

    @pytest.mark.asyncio
    async def test_handle_heartbeat_unknown_worker(self, worker_manager):
        """Test heartbeat from unknown worker (should not raise error)."""
        await worker_manager._handle_heartbeat("unknown_worker")
        # Should not raise any exception


class TestJobHandling:
    """Test job completion, progress, and failure handling."""

    @pytest.mark.asyncio
    async def test_handle_job_complete(self, worker_manager, mock_websocket):
        """Test job completion handling."""
        await worker_manager._register_worker(
            mock_websocket, "worker_1", WorkerCapabilities(model="base", device="cuda", fp16=False)
        )

        # Create a job
        job = await worker_manager.job_queue.create_job(
            task_id="task_123",
            audio_path="/path/to/audio.mp3",
            audio_url="http://example.com/audio.mp3",
        )

        await worker_manager.job_queue.assign_job("worker_1")

        # Assign job to worker
        worker = worker_manager.workers["worker_1"]
        worker.current_job_id = job.job_id
        worker.status = WorkerStatus.BUSY

        msg = JobCompleteMessage(
            type="job_complete",
            job_id=job.job_id,
            result={"segments": [], "language": "ja"},
        )

        await worker_manager._handle_job_complete("worker_1", msg)

        assert worker.status.value == "idle"
        assert worker.current_job_id is None
        assert worker.jobs_completed == 1
        mock_websocket.send_json.assert_any_call({"type": "job_complete_ack", "job_id": job.job_id})

    @pytest.mark.asyncio
    async def test_handle_job_complete_unknown_worker(self, worker_manager):
        """Test job completion from unknown worker."""
        msg = JobCompleteMessage(
            type="job_complete",
            job_id="job_123",
            result={"segments": []},
        )

        await worker_manager._handle_job_complete("unknown_worker", msg)
        # Should not raise any exception

    @pytest.mark.asyncio
    async def test_handle_job_complete_stale_job(self, worker_manager, mock_websocket):
        """Test stale job completion sends ack and requeues worker."""
        await worker_manager._register_worker(
            mock_websocket, "worker_1", WorkerCapabilities(model="base", device="cuda", fp16=False)
        )

        msg = JobCompleteMessage(
            type="job_complete",
            job_id="missing_job",
            result={"segments": []},
        )

        await worker_manager._handle_job_complete("worker_1", msg)

        mock_websocket.send_json.assert_any_call(
            {"type": "job_complete_ack", "job_id": "missing_job"}
        )

    @pytest.mark.asyncio
    async def test_handle_job_progress(self, worker_manager, mock_websocket):
        """Test job progress handling."""
        await worker_manager._register_worker(
            mock_websocket, "worker_1", WorkerCapabilities(model="base", device="cuda", fp16=False)
        )

        # Create a job
        job = await worker_manager.job_queue.create_job(
            task_id="task_123",
            audio_path="/path/to/audio.mp3",
            audio_url="http://example.com/audio.mp3",
        )

        await worker_manager.job_queue.assign_job("worker_1")

        msg = JobProgressMessage(
            type="job_progress",
            job_id=job.job_id,
            progress=50,
            message="Processing...",
        )

        await worker_manager._handle_job_progress("worker_1", msg)

        # Verify progress was updated
        job_status = worker_manager.job_queue.get_job(job.job_id)
        assert job_status.progress == 50
        assert job_status.progress_message == "Processing..."

    @pytest.mark.asyncio
    async def test_handle_job_failed(self, worker_manager, mock_websocket):
        """Test job failure handling."""
        await worker_manager._register_worker(
            mock_websocket, "worker_1", WorkerCapabilities(model="base", device="cuda", fp16=False)
        )

        # Create a job
        job = await worker_manager.job_queue.create_job(
            task_id="task_123",
            audio_path="/path/to/audio.mp3",
            audio_url="http://example.com/audio.mp3",
        )

        await worker_manager.job_queue.assign_job("worker_1")

        # Assign job to worker
        worker = worker_manager.workers["worker_1"]
        worker.current_job_id = job.job_id
        worker.status = WorkerStatus.BUSY

        msg = JobFailedMessage(
            type="job_failed",
            job_id=job.job_id,
            error="Transcription failed",
        )

        # Mock _assign_next_job to prevent reassigning the job
        with patch.object(worker_manager, "_assign_next_job", new_callable=AsyncMock):
            await worker_manager._handle_job_failed("worker_1", msg)

        assert worker.status == WorkerStatus.IDLE
        assert worker.current_job_id is None
        assert worker.jobs_failed == 1

    @pytest.mark.asyncio
    async def test_handle_job_failed_unknown_worker(self, worker_manager):
        """Test job failure from unknown worker."""
        msg = JobFailedMessage(
            type="job_failed",
            job_id="job_123",
            error="Error",
        )

        await worker_manager._handle_job_failed("unknown_worker", msg)
        # Should not raise any exception


class TestJobAssignment:
    """Test job assignment to workers."""

    @pytest.mark.asyncio
    async def test_assign_next_job_success(self, worker_manager, mock_websocket):
        """Test successful job assignment."""
        await worker_manager._register_worker(
            mock_websocket, "worker_1", WorkerCapabilities(model="base", device="cuda", fp16=False)
        )

        # Create a job
        job = await worker_manager.job_queue.create_job(
            task_id="task_123",
            audio_path="/path/to/audio.mp3",
            audio_url="http://example.com/audio.mp3",
        )

        # Assign next job
        await worker_manager._assign_next_job("worker_1")

        # Verify worker state
        worker = worker_manager.workers["worker_1"]
        assert worker.status.value == "busy"
        assert worker.current_job_id == job.job_id
        mock_websocket.send_json.assert_called()

    @pytest.mark.asyncio
    async def test_assign_next_job_worker_busy(self, worker_manager, mock_websocket):
        """Test job assignment when worker is busy."""
        await worker_manager._register_worker(
            mock_websocket, "worker_1", WorkerCapabilities(model="base", device="cuda", fp16=False)
        )

        # Set worker as busy
        worker = worker_manager.workers["worker_1"]
        worker.status = WorkerStatus.BUSY

        # Try to assign next job
        await worker_manager._assign_next_job("worker_1")

        # Worker should still be busy
        assert worker.status.value == "busy"
        assert worker.current_job_id is None

    @pytest.mark.asyncio
    async def test_assign_next_job_no_jobs(self, worker_manager, mock_websocket):
        """Test job assignment when no jobs are available."""
        await worker_manager._register_worker(
            mock_websocket, "worker_1", WorkerCapabilities(model="base", device="cuda", fp16=False)
        )

        # Try to assign next job (no jobs in queue)
        await worker_manager._assign_next_job("worker_1")

        # Worker should still be idle
        worker = worker_manager.workers["worker_1"]
        assert worker.status.value == "idle"
        assert worker.current_job_id is None

    @pytest.mark.asyncio
    async def test_assign_next_job_unknown_worker(self, worker_manager):
        """Test job assignment to unknown worker."""
        await worker_manager._assign_next_job("unknown_worker")
        # Should not raise any exception


class TestSubmitTranscribeJob:
    """Test submit_transcribe_job method."""

    @pytest.mark.asyncio
    async def test_submit_transcribe_job_no_workers(self, worker_manager):
        """Test submitting job when no workers are available."""
        with pytest.raises(RuntimeError, match="No workers available"):
            await worker_manager.submit_transcribe_job(
                task_id="task_123",
                audio_path="/path/to/audio.mp3",
                audio_url="http://example.com/audio.mp3",
            )

    @pytest.mark.asyncio
    async def test_submit_transcribe_job_success(self, worker_manager, mock_websocket):
        """Test successful job submission."""
        await worker_manager._register_worker(
            mock_websocket, "worker_1", WorkerCapabilities(model="base", device="cuda", fp16=False)
        )

        # Mock the job queue to return a completed job
        mock_job = Mock()
        mock_job.job_id = "job_123"
        mock_job.status.value = "completed"
        mock_job.result = {"segments": [], "language": "ja"}

        with patch.object(
            worker_manager.job_queue,
            "create_job",
            new_callable=AsyncMock,
        ) as mock_create:
            mock_create.return_value = mock_job

            with patch.object(worker_manager.job_queue, "get_job", return_value=mock_job):
                result = await worker_manager.submit_transcribe_job(
                    task_id="task_123",
                    audio_path="/path/to/audio.mp3",
                    audio_url="http://example.com/audio.mp3",
                )

        assert result == {"segments": [], "language": "ja"}

    @pytest.mark.asyncio
    async def test_submit_transcribe_job_timeout(self, worker_manager, mock_websocket):
        """Test job submission that times out."""
        await worker_manager._register_worker(
            mock_websocket,
            "worker_1",
            WorkerCapabilities(model="base", device="cuda", fp16=False),
        )

        # Mock the job queue to return a pending job
        mock_job = Mock()
        mock_job.job_id = "job_123"
        mock_job.status.value = "pending"
        mock_job.result = None

        with patch.object(
            worker_manager.job_queue,
            "create_job",
            new_callable=AsyncMock,
        ) as mock_create:
            mock_create.return_value = mock_job

            with patch.object(worker_manager.job_queue, "get_job", return_value=mock_job):
                with pytest.raises(asyncio.TimeoutError):
                    await worker_manager.submit_transcribe_job(
                        task_id="task_123",
                        audio_path="/path/to/audio.mp3",
                        audio_url="http://example.com/audio.mp3",
                        timeout=1,  # Short timeout
                    )

    @pytest.mark.asyncio
    async def test_submit_transcribe_job_failed(self, worker_manager, mock_websocket):
        """Test job submission that fails."""
        await worker_manager._register_worker(
            mock_websocket,
            "worker_1",
            WorkerCapabilities(model="base", device="cuda", fp16=False),
        )

        # Mock the job queue to return a failed job
        mock_job = Mock()
        mock_job.job_id = "job_123"
        mock_job.status.value = "failed"
        mock_job.error = "Transcription error"

        with patch.object(
            worker_manager.job_queue,
            "create_job",
            new_callable=AsyncMock,
        ) as mock_create:
            mock_create.return_value = mock_job

            with patch.object(worker_manager.job_queue, "get_job", return_value=mock_job):
                with pytest.raises(RuntimeError, match="Job job_123 failed"):
                    await worker_manager.submit_transcribe_job(
                        task_id="task_123",
                        audio_path="/path/to/audio.mp3",
                        audio_url="http://example.com/audio.mp3",
                    )


class TestGetStats:
    """Test get_stats method."""

    @pytest.mark.asyncio
    async def test_get_stats_empty(self, worker_manager):
        """Test get_stats with no workers."""
        stats = worker_manager.get_stats()
        assert stats.connected == 0
        assert stats.idle == 0
        assert stats.busy == 0
        assert stats.pending_jobs == 0
        assert stats.assigned_jobs == 0
        assert stats.processing_jobs == 0
        assert stats.workers == []

    @pytest.mark.asyncio
    async def test_get_stats_with_workers(self, worker_manager, mock_websocket):
        """Test get_stats with connected workers."""
        # Register two workers
        await worker_manager._register_worker(
            mock_websocket,
            "worker_1",
            WorkerCapabilities(model="base", device="cuda", fp16=False),
        )
        await worker_manager._register_worker(
            Mock(spec=WebSocket),
            "worker_2",
            WorkerCapabilities(model="base", device="cuda", fp16=False),
        )

        # Set one worker as busy
        worker_manager.workers["worker_1"].status = WorkerStatus.BUSY

        stats = worker_manager.get_stats()
        assert stats.connected == 2
        assert stats.idle == 1
        assert stats.busy == 1
        assert len(stats.workers) == 2


class TestStop:
    """Test stop method."""

    @pytest.mark.asyncio
    async def test_stop_closes_connections(self, worker_manager, mock_websocket):
        """Test that stop closes all WebSocket connections."""
        await worker_manager._register_worker(
            mock_websocket,
            "worker_1",
            WorkerCapabilities(model="base", device="cuda", fp16=False),
        )

        await worker_manager.stop()

        mock_websocket.close.assert_called()
        assert len(worker_manager.workers) == 0

    @pytest.mark.asyncio
    async def test_stop_handles_close_error(self, worker_manager, mock_websocket):
        """Test that stop handles close errors gracefully."""
        mock_websocket.close.side_effect = Exception("Close error")

        await worker_manager._register_worker(
            mock_websocket,
            "worker_1",
            WorkerCapabilities(model="base", device="cuda", fp16=False),
        )

        # Should not raise exception
        await worker_manager.stop()


class TestHeartbeatChecker:
    """Test heartbeat checker background task."""

    @pytest.mark.asyncio
    async def test_heartbeat_checker_timeouts_worker(self, worker_manager, mock_websocket):
        """Test that heartbeat checker removes workers that timeout."""
        await worker_manager._register_worker(
            mock_websocket, "worker_1", WorkerCapabilities(model="base", device="cuda", fp16=False)
        )

        # Start background tasks
        worker_manager.start()

        # Wait for heartbeat timeout
        await asyncio.sleep(4)

        # Worker should be unregistered due to heartbeat timeout
        assert "worker_1" not in worker_manager.workers

        # Stop background tasks
        await worker_manager.stop()

    @pytest.mark.asyncio
    async def test_heartbeat_checker_keeps_alive_worker(self, worker_manager, mock_websocket):
        """Test that heartbeat checker keeps workers that send heartbeats."""
        await worker_manager._register_worker(
            mock_websocket, "worker_1", WorkerCapabilities(model="base", device="cuda", fp16=False)
        )

        # Start background tasks
        worker_manager.start()

        # Send heartbeat
        await worker_manager._handle_heartbeat("worker_1")

        # Wait for less than timeout
        await asyncio.sleep(2)

        # Worker should still be registered
        assert "worker_1" in worker_manager.workers

        # Stop background tasks
        await worker_manager.stop()


class TestCleanupLoop:
    """Test cleanup loop background task."""

    @pytest.mark.asyncio
    async def test_cleanup_loop_calls_cleanup(self, worker_manager, mock_storage_bridge):
        """Test that cleanup loop calls storage bridge and job queue cleanup."""
        with patch.object(
            worker_manager.job_queue, "cleanup_old_jobs", new_callable=AsyncMock
        ) as mock_cleanup:
            # Mock the sleep in the cleanup loop to trigger immediately
            with patch("workers.manager.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                mock_sleep.side_effect = [None, asyncio.CancelledError()]
                await worker_manager._cleanup_loop()

        # Verify cleanup was called
        mock_storage_bridge.cleanup_expired_signatures.assert_called()
        mock_cleanup.assert_called()


class TestWorkerCapabilities:
    """Test worker capabilities validation."""

    def test_worker_capabilities_model(self):
        """Test WorkerCapabilities with model."""
        caps = WorkerCapabilities(model="base", device="cuda", fp16=False)
        assert caps.model == "base"
        assert caps.device == "cuda"
        assert caps.fp16 is False

    def test_worker_capabilities_fp16(self):
        """Test WorkerCapabilities with fp16."""
        caps = WorkerCapabilities(model="large", device="cuda", fp16=True)
        assert caps.model == "large"
        assert caps.fp16 is True

    def test_worker_capabilities_to_dict(self):
        """Test WorkerCapabilities to_dict method."""
        caps = WorkerCapabilities(model="base", device="cuda", fp16=False)
        caps_dict = caps.model_dump()
        assert caps_dict == {"model": "base", "device": "cuda", "fp16": False}
