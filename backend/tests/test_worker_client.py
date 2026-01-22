"""Tests for worker client capability validation."""

from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

# Ensure worker package is importable when running tests from backend/
ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))
WORKER_DIR = ROOT_DIR / "worker"
if str(WORKER_DIR) not in sys.path:
    sys.path.append(str(WORKER_DIR))

# Stub out aiohttp so worker imports succeed in backend test environment.
if "aiohttp" not in sys.modules:
    sys.modules["aiohttp"] = types.ModuleType("aiohttp")

# Stub out worker-only dependencies so imports succeed without GPU stack.
if "ffmpeg" not in sys.modules:
    sys.modules["ffmpeg"] = types.ModuleType("ffmpeg")
if "whisper" not in sys.modules:
    whisper_stub = types.ModuleType("whisper")
    whisper_stub.Whisper = object

    def _missing_whisper(*_args, **_kwargs):
        raise RuntimeError("whisper module not available in backend tests")

    whisper_stub.load_model = _missing_whisper
    sys.modules["whisper"] = whisper_stub


@pytest.fixture(autouse=True)
def _worker_env(monkeypatch):
    """Provide required worker env vars for client initialization."""
    monkeypatch.setenv("WORKER_TOKEN", "test-token")


# Import the helper functions from worker client
# We need to test the _validate_capability_mismatch function
# Since it's a module-level function, we'll import it directly


class TestValidateCapabilityMismatch:
    """Test the _validate_capability_mismatch helper function."""

    def test_validate_capability_mismatch_model_size(self):
        """Test model size mismatch detection."""
        from worker.client import _validate_capability_mismatch

        error = _validate_capability_mismatch(
            requested="large",
            actual="base",
            capability_name="Model size",
        )
        assert error == "Model size mismatch: requested large, worker has base"

    def test_validate_capability_mismatch_fp16(self):
        """Test FP16 mismatch detection."""
        from worker.client import _validate_capability_mismatch

        error = _validate_capability_mismatch(
            requested=True,
            actual=False,
            capability_name="FP16",
        )
        assert error == "FP16 mismatch: requested True, worker has False"

    def test_validate_capability_mismatch_device(self):
        """Test device mismatch detection."""
        from worker.client import _validate_capability_mismatch

        error = _validate_capability_mismatch(
            requested="cuda",
            actual="cpu",
            capability_name="Device",
        )
        assert error == "Device mismatch: requested cuda, worker has cpu"

    def test_validate_capability_mismatch_no_mismatch(self):
        """Test when there's no mismatch."""
        from worker.client import _validate_capability_mismatch

        error = _validate_capability_mismatch(
            requested="base",
            actual="base",
            capability_name="Model size",
        )
        assert error is None

    def test_validate_capability_mismatch_fp16_no_mismatch(self):
        """Test FP16 with no mismatch."""
        from worker.client import _validate_capability_mismatch

        error = _validate_capability_mismatch(
            requested=True,
            actual=True,
            capability_name="FP16",
        )
        assert error is None

    def test_validate_capability_mismatch_none_requested(self):
        """Test when requested value is None."""
        from worker.client import _validate_capability_mismatch

        error = _validate_capability_mismatch(
            requested=None,
            actual="base",
            capability_name="Model size",
        )
        assert error == "Model size mismatch: requested None, worker has base"

    def test_validate_capability_mismatch_string_vs_bool(self):
        """Test string vs bool comparison."""
        from worker.client import _validate_capability_mismatch

        error = _validate_capability_mismatch(
            requested="true",
            actual=True,
            capability_name="FP16",
        )
        assert error == "FP16 mismatch: requested true, worker has True"

    def test_validate_capability_mismatch_empty_string(self):
        """Test empty string comparison."""
        from worker.client import _validate_capability_mismatch

        error = _validate_capability_mismatch(
            requested="",
            actual="base",
            capability_name="Model size",
        )
        assert error == "Model size mismatch: requested , worker has base"


class TestSendJobFailed:
    """Test the _send_job_failed helper function."""

    @pytest.mark.asyncio
    async def test_send_job_failed_success(self):
        """Test sending job_failed message successfully."""
        from unittest.mock import AsyncMock, Mock

        from worker.client import _send_job_failed

        mock_ws = Mock()
        mock_ws.send = AsyncMock()

        await _send_job_failed(mock_ws, "job_123", "Test error")

        mock_ws.send.assert_called_once()
        call_args = mock_ws.send.call_args[0][0]
        assert '"type": "job_failed"' in call_args
        assert '"job_id": "job_123"' in call_args
        assert '"error": "Test error"' in call_args

    @pytest.mark.asyncio
    async def test_send_job_failed_connection_closed(self):
        """Test sending job_failed when connection is closed."""
        from unittest.mock import AsyncMock, Mock

        from worker.client import _send_job_failed

        mock_ws = Mock()
        mock_ws.send = AsyncMock(side_effect=Exception("Connection closed"))

        # Should not raise exception
        await _send_job_failed(mock_ws, "job_123", "Test error")

        mock_ws.send.assert_called_once()


class TestWhisperWorkerClientInit:
    """Test WhisperWorkerClient initialization."""

    def test_init_with_config_path(self):
        """Test initialization with config path."""
        from worker.client import WhisperWorkerClient

        # Config path is reserved for future use, should be ignored
        client = WhisperWorkerClient(config_path="/some/path/.env")
        assert client.config is not None
        assert hasattr(client, "reconnect_delay")
        assert hasattr(client, "max_reconnect_delay")
        assert hasattr(client, "current_job_id")
        assert hasattr(client, "ws")
        assert hasattr(client, "downloader")
        assert hasattr(client, "transcriber")
        assert hasattr(client, "_running")

    def test_init_without_config_path(self):
        """Test initialization without config path."""
        from worker.client import WhisperWorkerClient

        client = WhisperWorkerClient()
        assert client.config is not None
        assert client._running is False


class TestWorkerClientStop:
    """Test WhisperWorkerClient stop method."""

    @pytest.mark.asyncio
    async def test_stop_without_connection(self):
        """Test stopping client without active connection."""
        from worker.client import WhisperWorkerClient

        client = WhisperWorkerClient()
        client.stop()

        assert client._running is False

    @pytest.mark.asyncio
    async def test_stop_with_connection_no_job(self):
        """Test stopping client with connection but no current job."""
        from unittest.mock import AsyncMock, Mock

        from worker.client import WhisperWorkerClient

        client = WhisperWorkerClient()
        mock_ws = Mock()
        mock_ws.close = AsyncMock()
        client.ws = mock_ws
        client._running = True

        client.stop()

        assert client._running is False
        mock_ws.close.assert_called()

    @pytest.mark.asyncio
    async def test_stop_with_connection_and_job(self):
        """Test stopping client with connection and current job."""
        from unittest.mock import AsyncMock, Mock, patch

        from worker.client import WhisperWorkerClient

        client = WhisperWorkerClient()
        mock_ws = Mock()
        mock_ws.close = AsyncMock()
        client.ws = mock_ws
        client.current_job_id = "job_123"
        client._running = True

        with patch("worker.client._send_job_failed", new_callable=AsyncMock) as mock_send:
            client.stop()

            assert client._running is False
            mock_send.assert_called_once()
            # Verify the call arguments
            call_args = mock_send.call_args[0]
            assert call_args[0] == mock_ws
            assert call_args[1] == "job_123"
            assert "Worker shutdown during processing" in call_args[2]


class TestWorkerClientReconnect:
    """Test WhisperWorkerClient reconnect logic."""

    @pytest.mark.asyncio
    async def test_reconnect_exponential_backoff(self):
        """Test reconnect with exponential backoff."""
        from unittest.mock import patch

        from worker.client import WhisperWorkerClient

        client = WhisperWorkerClient()
        client.reconnect_delay = 1
        client.max_reconnect_delay = 30

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await client._reconnect()

        mock_sleep.assert_called_once_with(1)
        assert client.reconnect_delay == 2  # Doubled

    @pytest.mark.asyncio
    async def test_reconnect_max_delay(self):
        """Test reconnect doesn't exceed max delay."""
        from unittest.mock import patch

        from worker.client import WhisperWorkerClient

        client = WhisperWorkerClient()
        client.reconnect_delay = 16
        client.max_reconnect_delay = 30

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await client._reconnect()

        mock_sleep.assert_called_once_with(16)
        assert client.reconnect_delay == 30  # Capped at max


class TestWorkerClientHeartbeat:
    """Test WhisperWorkerClient heartbeat sending."""

    @pytest.mark.asyncio
    async def test_send_heartbeat_success(self):
        """Test sending heartbeat successfully."""
        from unittest.mock import AsyncMock, Mock, patch

        from worker.client import WhisperWorkerClient

        client = WhisperWorkerClient()
        mock_ws = Mock()
        mock_ws.send = AsyncMock()
        mock_ws.closed = False
        client.ws = mock_ws

        with patch("worker.client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            mock_sleep.side_effect = [None, asyncio.CancelledError()]
            await client._send_heartbeat()

        mock_ws.send.assert_called()
        call_args = mock_ws.send.call_args[0][0]
        assert '"type": "heartbeat"' in call_args

    @pytest.mark.asyncio
    async def test_send_heartbeat_connection_closed(self):
        """Test heartbeat when connection is closed."""
        from unittest.mock import AsyncMock, Mock, patch

        from worker.client import WhisperWorkerClient

        client = WhisperWorkerClient()
        mock_ws = Mock()
        mock_ws.send = AsyncMock(side_effect=Exception("Connection closed"))
        mock_ws.closed = False
        client.ws = mock_ws

        with patch("worker.client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            mock_sleep.side_effect = [None, asyncio.CancelledError()]
            await client._send_heartbeat()

        mock_ws.send.assert_called()

    @pytest.mark.asyncio
    async def test_send_heartbeat_cancelled(self):
        """Test heartbeat cancellation."""
        from unittest.mock import AsyncMock, Mock, patch

        from worker.client import WhisperWorkerClient

        client = WhisperWorkerClient()
        mock_ws = Mock()
        mock_ws.send = AsyncMock()
        mock_ws.closed = False
        client.ws = mock_ws

        with patch("asyncio.sleep", new_callable=AsyncMock):
            task = asyncio.create_task(client._send_heartbeat())
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Should not have sent heartbeat since task was cancelled
        mock_ws.send.assert_not_called()


class TestWorkerClientRegistration:
    """Test WhisperWorkerClient registration."""

    @pytest.mark.asyncio
    async def test_register_success(self):
        """Test successful registration."""
        from unittest.mock import AsyncMock, Mock

        from worker.client import WhisperWorkerClient

        client = WhisperWorkerClient()
        mock_ws = Mock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(return_value='{"type": "registered", "worker_id": "test_worker"}')
        client.ws = mock_ws

        await client._register()

        mock_ws.send.assert_called_once()
        call_args = mock_ws.send.call_args[0][0]
        assert '"type": "register"' in call_args
        assert '"worker_id"' in call_args

    @pytest.mark.asyncio
    async def test_register_failure(self):
        """Test registration failure."""
        from unittest.mock import AsyncMock, Mock

        from worker.client import WhisperWorkerClient

        client = WhisperWorkerClient()
        mock_ws = Mock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(return_value='{"type": "error", "message": "Registration failed"}')
        client.ws = mock_ws

        with pytest.raises(Exception, match="Registration failed"):
            await client._register()


class TestWorkerClientCapabilityValidation:
    """Test worker client capability validation in job handling."""

    @pytest.mark.asyncio
    async def test_handle_job_assigned_model_mismatch(self):
        """Test handling job with model size mismatch."""
        from worker.client import WhisperWorkerClient

        client = WhisperWorkerClient()
        # Mock config to return base model
        mock_config = Mock()
        mock_config.whisper_model_size = "base"
        mock_config.whisper_fp16 = False
        client.config = mock_config

        mock_ws = Mock()
        mock_ws.send = AsyncMock()
        client.ws = mock_ws

        data = {
            "job_id": "job_123",
            "audio_url": "http://example.com/audio.mp3",
            "options": {"model_size": "large"},  # Requested large, but worker has base
        }

        with patch.object(client, "downloader"):
            await client._handle_job_assigned(data)

        mock_ws.send.assert_called()
        call_args = mock_ws.send.call_args[0][0]
        assert '"type": "job_failed"' in call_args
        assert '"error": "Model size mismatch' in call_args

    @pytest.mark.asyncio
    async def test_handle_job_assigned_fp16_mismatch(self):
        """Test handling job with FP16 mismatch."""
        from worker.client import WhisperWorkerClient

        client = WhisperWorkerClient()
        # Mock config to return fp16=False
        mock_config = Mock()
        mock_config.whisper_model_size = "base"
        mock_config.whisper_fp16 = False
        client.config = mock_config

        mock_ws = Mock()
        mock_ws.send = AsyncMock()
        client.ws = mock_ws

        data = {
            "job_id": "job_123",
            "audio_url": "http://example.com/audio.mp3",
            "options": {"fp16": True},  # Requested fp16=True, but worker has fp16=False
        }

        with patch.object(client, "downloader"):
            await client._handle_job_assigned(data)

        mock_ws.send.assert_called()
        call_args = mock_ws.send.call_args[0][0]
        assert '"type": "job_failed"' in call_args
        assert '"error": "FP16 mismatch' in call_args

    @pytest.mark.asyncio
    async def test_handle_job_assigned_no_mismatch(self):
        """Test handling job with no capability mismatch."""
        from worker.client import WhisperWorkerClient

        client = WhisperWorkerClient()
        # Mock config
        mock_config = Mock()
        mock_config.whisper_model_size = "base"
        mock_config.whisper_fp16 = False
        client.config = mock_config

        mock_ws = Mock()
        mock_ws.send = AsyncMock()
        client.ws = mock_ws

        data = {
            "job_id": "job_123",
            "audio_url": "http://example.com/audio.mp3",
            "options": {"model_size": "base", "fp16": False},
        }

        # Mock downloader and transcriber to avoid actual processing
        mock_downloader = Mock()
        mock_downloader.download = AsyncMock(return_value=("/path/to/audio.mp3", None))
        mock_downloader.cleanup = AsyncMock()
        mock_downloader.cleanup_old_files = AsyncMock()

        mock_transcriber = Mock()
        mock_transcriber.transcribe = AsyncMock(return_value={"segments": [], "language": "ja"})

        client.downloader = mock_downloader
        client.transcriber = mock_transcriber

        await client._handle_job_assigned(data)

        # Verify downloader was called
        mock_downloader.download.assert_called_once()
        mock_downloader.cleanup.assert_called_once()
        mock_transcriber.transcribe.assert_called_once()

        # Verify job_complete was sent
        call_args = mock_ws.send.call_args[0][0]
        assert '"type": "job_complete"' in call_args


class TestWorkerClientJobHandling:
    """Test worker client job handling."""

    @pytest.mark.asyncio
    async def test_handle_job_assigned_invalid_data(self):
        """Test handling job with invalid data."""
        from unittest.mock import AsyncMock, Mock

        from worker.client import WhisperWorkerClient

        client = WhisperWorkerClient()
        mock_ws = Mock()
        mock_ws.send = AsyncMock()
        client.ws = mock_ws

        # Missing job_id
        await client._handle_job_assigned({"audio_url": "http://example.com/audio.mp3"})

        # Should not send any message
        mock_ws.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_job_assigned_missing_audio_url(self):
        """Test handling job with missing audio_url."""
        from unittest.mock import AsyncMock, Mock

        from worker.client import WhisperWorkerClient

        client = WhisperWorkerClient()
        mock_ws = Mock()
        mock_ws.send = AsyncMock()
        client.ws = mock_ws

        # Missing audio_url
        await client._handle_job_assigned({"job_id": "job_123"})

        # Should not send any message
        mock_ws.send.assert_not_called()


# Helper to import asyncio for async tests
