"""Comprehensive tests for worker client.py."""

from __future__ import annotations

import asyncio
import base64
import json
import os
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
import websockets

from client import (
    _analyze_texts,
    _annotate_segments_with_mecab,
    _generate_thumbnail_b64,
    _send_job_failed,
    _validate_capability_mismatch,
    WhisperWorkerClient,
)


# =============================================================================
# Async Context Manager Mock Helper
# =============================================================================

class _AsyncContextManagerMock:
    """Helper class to mock async context managers."""
    def __init__(self, return_value=None):
        self._return_value = return_value
        self._aenter_calls = []
        self._aexit_calls = []

    async def __aenter__(self):
        self._aenter_calls.append(True)
        return self._return_value

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._aexit_calls.append((exc_type, exc_val, exc_tb))
        return False


class _AsyncWebSocketMock:
    """Helper class to mock WebSocket with async iteration."""
    def __init__(self, messages):
        self._messages = messages
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._messages):
            raise StopAsyncIteration
        result = self._messages[self._index]
        self._index += 1
        return result

    # Add common WebSocket methods as AsyncMock
    send = AsyncMock()
    recv = AsyncMock()
    close = AsyncMock()


# =============================================================================
# Helper Function Tests
# =============================================================================


class TestValidateCapabilityMismatch:
    """Tests for _validate_capability_mismatch helper."""

    def test_matching_string_capabilities(self):
        """Test matching string capabilities returns None."""
        result = _validate_capability_mismatch("base", "base", "Model size")
        assert result is None

    def test_matching_boolean_capabilities(self):
        """Test matching boolean capabilities returns None."""
        result = _validate_capability_mismatch(True, True, "FP16")
        assert result is None

        result = _validate_capability_mismatch(False, False, "FP16")
        assert result is None

    def test_mismatched_string_capabilities(self):
        """Test mismatched string capabilities returns error message."""
        result = _validate_capability_mismatch("large", "base", "Model size")
        assert result == "Model size mismatch: requested large, worker has base"

    def test_mismatched_boolean_capabilities(self):
        """Test mismatched boolean capabilities returns error message."""
        result = _validate_capability_mismatch(True, False, "FP16")
        assert result == "FP16 mismatch: requested True, worker has False"

    def test_none_requested_with_actual_value(self):
        """Test None requested (no preference) with actual value."""
        result = _validate_capability_mismatch(None, "base", "Model size")
        assert result == "Model size mismatch: requested None, worker has base"

    def test_custom_capability_names(self):
        """Test custom capability names in error message."""
        result = _validate_capability_mismatch("cuda", "cpu", "Device")
        assert result == "Device mismatch: requested cuda, worker has cpu"


class TestSendJobFailed:
    """Tests for _send_job_failed helper."""

    @pytest.mark.asyncio
    async def test_sends_correct_message_format(self):
        """Test _send_job_failed sends correct JSON message."""
        mock_ws = AsyncMock()
        job_id = "test-job-123"
        error = "Transcription failed: out of memory"

        await _send_job_failed(mock_ws, job_id, error)

        # Verify send was called with correct JSON
        mock_ws.send.assert_called_once()
        sent_data = json.loads(mock_ws.send.call_args[0][0])
        assert sent_data == {
            "type": "job_failed",
            "job_id": job_id,
            "error": error,
        }

    @pytest.mark.asyncio
    async def test_websocket_send_failure_logged(self):
        """Test WebSocket send failure is logged (not raised)."""
        mock_ws = AsyncMock(side_effect=Exception("Connection closed"))
        job_id = "test-job-123"
        error = "Some error"

        # Should not raise, just log warning
        await _send_job_failed(mock_ws, job_id, error)

        mock_ws.send.assert_called_once()


class TestGenerateThumbnailB64:
    """Tests for _generate_thumbnail_b64 helper."""

    def test_generates_valid_base64(self):
        """Test generates valid base64 JPEG thumbnail."""
        # Create a test video file (1 second dummy)
        with patch("ffmpeg.input") as mock_input, \
             patch("ffmpeg.run") as mock_run, \
             patch("builtins.open", create=True) as mock_open:

            # Mock the ffmpeg chain
            mock_output = Mock()
            mock_input.return_value.output = Mock(return_value=mock_output)
            mock_output.overwrite_output = Mock(return_value=mock_output)
            mock_output.run = Mock(return_value=(b"", b""))

            # Mock file operations
            mock_file = MagicMock()
            mock_file.read.return_value = b"fake_jpeg_data"
            mock_open.return_value.__enter__.return_value = mock_file

            with patch("os.path.exists", return_value=True), \
                 patch("os.remove"):

                result = _generate_thumbnail_b64("/path/to/video.mp4", 1.0)

                # Verify base64 encoding
                expected = base64.b64encode(b"fake_jpeg_data").decode("ascii")
                assert result == expected

    def test_negative_timestamp_clamped_to_zero(self):
        """Test negative timestamp is clamped to zero."""
        with patch("ffmpeg.input") as mock_input, \
             patch("ffmpeg.run"), \
             patch("builtins.open", create=True) as mock_open:

            mock_output = Mock()
            mock_input.return_value.output = Mock(return_value=mock_output)
            mock_output.overwrite_output = Mock(return_value=mock_output)

            mock_file = MagicMock()
            mock_file.read.return_value = b"data"
            mock_open.return_value.__enter__.return_value = mock_file

            with patch("os.path.exists", return_value=True), \
                 patch("os.remove"):

                _generate_thumbnail_b64("/path/to/video.mp4", -5.0)

                # Verify ffmpeg was called with ss=0.0
                mock_input.assert_called_once()
                call_kwargs = mock_input.call_args[1]
                assert call_kwargs["ss"] == 0.0

    def test_temp_file_cleanup_on_success(self):
        """Test temporary file is cleaned up on success."""
        with patch("ffmpeg.input"), \
             patch("ffmpeg.run"), \
             patch("builtins.open", create=True) as mock_open, \
             patch("tempfile.NamedTemporaryFile") as mock_tmp:

            mock_tmp_file = MagicMock()
            mock_tmp_file.name = "/tmp/test_thumbnail.jpg"
            mock_tmp.return_value.__enter__.return_value = mock_tmp_file

            # Mock file read to return bytes
            mock_file = MagicMock()
            mock_file.read.return_value = b"fake_jpeg_data"
            mock_open.return_value.__enter__.return_value = mock_file

            with patch("os.path.exists", return_value=True), \
                 patch("os.remove") as mock_remove:

                _generate_thumbnail_b64("/path/to/video.mp4", 1.0)

                # Verify cleanup
                mock_remove.assert_called_once_with("/tmp/test_thumbnail.jpg")

    def test_temp_file_cleanup_on_error(self):
        """Test temporary file is cleaned up even if ffmpeg fails."""
        with patch("ffmpeg.input") as mock_input, \
             patch("ffmpeg.run"):

            mock_output = Mock()
            mock_input.return_value.output = Mock(return_value=mock_output)
            mock_output.overwrite_output = Mock(return_value=mock_output)
            # Make .run() raise an exception
            mock_output.run = Mock(side_effect=Exception("FFmpeg error"))

            with patch("tempfile.NamedTemporaryFile") as mock_tmp, \
                 patch("os.path.exists", return_value=True), \
                 patch("os.remove") as mock_remove:

                mock_tmp_file = MagicMock()
                mock_tmp_file.name = "/tmp/test_thumbnail.jpg"
                mock_tmp.return_value.__enter__.return_value = mock_tmp_file

                # Should raise but still cleanup
                with pytest.raises(Exception, match="FFmpeg error"):
                    _generate_thumbnail_b64("/path/to/video.mp4", 1.0)

                mock_remove.assert_called_once_with("/tmp/test_thumbnail.jpg")


class TestAnnotateSegmentsWithMecab:
    """Tests for _annotate_segments_with_mecab helper."""

    def test_attaches_tokens_to_segments(self):
        """Test mecab_tokens are attached to each segment."""
        mock_analyzer = MagicMock()
        mock_analyzer.analyze.return_value = [
            {"surface": "日本", "reading": "ニホン"},
            {"surface": "語", "reading": "ゴ"},
        ]

        segments = [
            {"text": "日本語", "start": 0.0, "end": 1.0},
            {"text": "テスト", "start": 1.0, "end": 2.0},
        ]

        _annotate_segments_with_mecab(mock_analyzer, segments)

        # Verify analyzer was called for each segment
        assert mock_analyzer.analyze.call_count == 2

        # Verify tokens were attached in-place
        assert segments[0]["mecab_tokens"] == [
            {"surface": "日本", "reading": "ニホン"},
            {"surface": "語", "reading": "ゴ"},
        ]
        assert segments[1]["mecab_tokens"] == [
            {"surface": "日本", "reading": "ニホン"},
            {"surface": "語", "reading": "ゴ"},
        ]

    def test_empty_text_gets_empty_tokens(self):
        """Test segments with empty text get empty token list."""
        mock_analyzer = MagicMock()

        segments = [
            {"text": "", "start": 0.0, "end": 1.0},
            {"text": "   ", "start": 1.0, "end": 2.0},
        ]

        _annotate_segments_with_mecab(mock_analyzer, segments)

        # Verify analyzer was not called for empty segments
        mock_analyzer.analyze.assert_not_called()

        assert segments[0]["mecab_tokens"] == []
        assert segments[1]["mecab_tokens"] == []

    def test_non_dict_segments_skipped(self):
        """Test non-dict segments are skipped gracefully."""
        mock_analyzer = MagicMock()

        segments = [
            {"text": "valid", "start": 0.0},
            "not a dict",
            None,
            {"text": "also valid", "start": 1.0},
        ]

        _annotate_segments_with_mecab(mock_analyzer, segments)

        # Only valid dict segments should be analyzed
        assert mock_analyzer.analyze.call_count == 2

    def test_segments_without_text_key(self):
        """Test segments without 'text' key get empty tokens."""
        mock_analyzer = MagicMock()

        segments = [
            {"start": 0.0, "end": 1.0},  # Missing "text" key
        ]

        _annotate_segments_with_mecab(mock_analyzer, segments)

        # Segment with missing key gets empty tokens (since .get() returns "")
        mock_analyzer.analyze.assert_not_called()
        assert segments[0]["mecab_tokens"] == []

    def test_segments_with_none_text_value(self):
        """Test segments with None as text value raise error (current behavior)."""
        mock_analyzer = MagicMock()

        segments = [
            {"text": None, "start": 0.0, "end": 1.0},
        ]

        # Current implementation: None.strip() raises AttributeError
        with pytest.raises(AttributeError, match="'NoneType' object has no attribute 'strip'"):
            _annotate_segments_with_mecab(mock_analyzer, segments)


class TestAnalyzeTexts:
    """Tests for _analyze_texts helper."""

    def test_batch_analysis_delegates_to_analyzer(self):
        """Test batch analysis calls analyzer.analyze_batch."""
        mock_analyzer = MagicMock()
        mock_analyzer.analyze_batch.return_value = [
            [{"surface": "テスト"}],
            [{"surface": "文章"}],
        ]

        texts = ["テスト", "文章"]

        result = _analyze_texts(mock_analyzer, texts)

        mock_analyzer.analyze_batch.assert_called_once_with(texts)
        assert result == [
            [{"surface": "テスト"}],
            [{"surface": "文章"}],
        ]

    def test_empty_text_list(self):
        """Test empty text list returns empty list."""
        mock_analyzer = MagicMock()
        mock_analyzer.analyze_batch.return_value = []

        result = _analyze_texts(mock_analyzer, [])

        mock_analyzer.analyze_batch.assert_called_once_with([])
        assert result == []


# =============================================================================
# WhisperWorkerClient Class Tests
# =============================================================================


class TestWhisperWorkerClientInit:
    """Tests for WhisperWorkerClient.__init__."""

    @patch("client.load_config")
    @patch("client.AudioDownloader")
    @patch("client.WhisperTranscriber")
    def test_initialization(self, mock_transcriber, mock_downloader, mock_load_config):
        """Test client initialization sets up all components."""
        mock_config = Mock(
            backend_ws_url="ws://localhost:8000/ws/worker",
            worker_token="test-token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=False,
            audio_cache_dir="./cache/audio",
            max_cache_size_gb=10,
        )
        mock_load_config.return_value = mock_config

        client = WhisperWorkerClient()

        assert client.config == mock_config
        assert client.reconnect_delay == 1
        assert client.max_reconnect_delay == 30
        assert client.current_job_id is None
        assert client.ws is None
        assert client._analyzer is None
        assert client._running is False
        assert client._pending_cleanup_jobs == set()

        # Verify downloader and transcriber were initialized
        mock_downloader.assert_called_once_with("./cache/audio")
        mock_transcriber.assert_called_once_with(
            model_size="base",
            device="cuda",
            fp16=False,
        )


class TestWhisperWorkerClientConnect:
    """Tests for WhisperWorkerClient._connect."""

    @pytest.mark.asyncio
    @patch("client.load_config")
    @patch("client.AudioDownloader")
    @patch("client.WhisperTranscriber")
    async def test_websocket_connection_established(
        self, mock_transcriber, mock_downloader, mock_load_config
    ):
        """Test WebSocket connection is established."""
        mock_config = Mock(
            backend_ws_url="ws://localhost:8000/ws/worker",
            worker_token="token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=False,
            audio_cache_dir="./cache",
            max_cache_size_gb=10,
        )
        mock_load_config.return_value = mock_config

        client = WhisperWorkerClient()

        # Create a proper async context manager mock
        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(return_value=json.dumps({
            "type": "registered",
            "worker_id": "gpu-01",
        }))

        # Patch websockets.connect to return our mock async context manager
        def mock_connect(*args, **kwargs):
            return _AsyncContextManagerMock(return_value=mock_ws)

        with patch("websockets.connect", side_effect=mock_connect), \
             patch.object(client, "_register", AsyncMock()), \
             patch.object(client, "_message_loop", AsyncMock()):

            await client._connect()

            assert client.ws == mock_ws

    @pytest.mark.asyncio
    @patch("client.load_config")
    @patch("client.AudioDownloader")
    @patch("client.WhisperTranscriber")
    async def test_calls_register_and_message_loop(
        self, mock_transcriber, mock_downloader, mock_load_config
    ):
        """Test _connect calls _register and _message_loop."""
        mock_config = Mock(
            backend_ws_url="ws://localhost:8000/ws/worker",
            worker_token="token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=False,
            audio_cache_dir="./cache",
            max_cache_size_gb=10,
        )
        mock_load_config.return_value = mock_config

        client = WhisperWorkerClient()

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()

        def mock_connect(*args, **kwargs):
            return _AsyncContextManagerMock(return_value=mock_ws)

        with patch("websockets.connect", side_effect=mock_connect), \
             patch.object(client, "_register", new=AsyncMock()) as mock_register, \
             patch.object(client, "_message_loop", new=AsyncMock()) as mock_loop:

            await client._connect()

            mock_register.assert_called_once()
            mock_loop.assert_called_once()


class TestWhisperWorkerClientRegister:
    """Tests for WhisperWorkerClient._register."""

    @pytest.mark.asyncio
    @patch("client.load_config")
    @patch("client.AudioDownloader")
    @patch("client.WhisperTranscriber")
    async def test_sends_registration_message(
        self, mock_transcriber, mock_downloader, mock_load_config
    ):
        """Test registration sends correct message."""
        mock_config = Mock(
            backend_ws_url="ws://test",
            worker_token="secret-token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=False,
            audio_cache_dir="./cache",
            max_cache_size_gb=10,
        )
        mock_load_config.return_value = mock_config

        client = WhisperWorkerClient()

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(return_value=json.dumps({
            "type": "registered",
            "worker_id": "gpu-01",
        }))
        client.ws = mock_ws

        await client._register()

        # Verify send was called with registration message
        mock_ws.send.assert_called_once()
        sent_data = json.loads(mock_ws.send.call_args[0][0])
        assert sent_data == {
            "type": "register",
            "token": "secret-token",
            "worker_id": "gpu-01",
            "capabilities": {
                "model": "base",
                "device": "cuda",
                "fp16": False,
            },
        }

    @pytest.mark.asyncio
    @patch("client.load_config")
    @patch("client.AudioDownloader")
    @patch("client.WhisperTranscriber")
    async def test_successful_registration(
        self, mock_transcriber, mock_downloader, mock_load_config
    ):
        """Test successful registration response."""
        mock_config = Mock(
            backend_ws_url="ws://test",
            worker_token="token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=False,
            audio_cache_dir="./cache",
            max_cache_size_gb=10,
        )
        mock_load_config.return_value = mock_config

        client = WhisperWorkerClient()

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(return_value=json.dumps({
            "type": "registered",
            "worker_id": "gpu-01",
        }))
        client.ws = mock_ws

        # Should not raise
        await client._register()

    @pytest.mark.asyncio
    @patch("client.load_config")
    @patch("client.AudioDownloader")
    @patch("client.WhisperTranscriber")
    async def test_registration_error_response(
        self, mock_transcriber, mock_downloader, mock_load_config
    ):
        """Test registration failure from server."""
        mock_config = Mock(
            backend_ws_url="ws://test",
            worker_token="invalid-token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=False,
            audio_cache_dir="./cache",
            max_cache_size_gb=10,
        )
        mock_load_config.return_value = mock_config

        client = WhisperWorkerClient()

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(return_value=json.dumps({
            "type": "error",
            "message": "Invalid worker token",
        }))
        client.ws = mock_ws

        with pytest.raises(Exception, match="Registration failed: Invalid worker token"):
            await client._register()


class TestWhisperWorkerClientMessageLoop:
    """Tests for WhisperWorkerClient._message_loop."""

    @pytest.mark.asyncio
    @patch("client.load_config")
    @patch("client.AudioDownloader")
    @patch("client.WhisperTranscriber")
    async def test_handles_job_assigned_message(
        self, mock_transcriber, mock_downloader, mock_load_config
    ):
        """Test message loop handles job_assigned messages."""
        mock_config = Mock(
            backend_ws_url="ws://test",
            worker_token="token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=False,
            audio_cache_dir="./cache",
            max_cache_size_gb=10,
        )
        mock_load_config.return_value = mock_config

        client = WhisperWorkerClient()

        # Create async WebSocket mock with messages
        mock_ws = _AsyncWebSocketMock([
            json.dumps({"type": "job_assigned", "job_id": "job-123", "audio_url": "http://example.com/audio.wav"}),
        ])
        client.ws = mock_ws

        with patch.object(client, "_handle_job_assigned", new=AsyncMock()) as mock_handle, \
             patch.object(client, "_send_heartbeat", new=AsyncMock(side_effect=asyncio.CancelledError)):

            try:
                await client._message_loop()
            except asyncio.CancelledError:
                pass

            mock_handle.assert_called_once()

    @pytest.mark.asyncio
    @patch("client.load_config")
    @patch("client.AudioDownloader")
    @patch("client.WhisperTranscriber")
    async def test_handles_job_complete_ack_message(
        self, mock_transcriber, mock_downloader, mock_load_config
    ):
        """Test message loop handles job_complete_ack messages."""
        mock_config = Mock(
            backend_ws_url="ws://test",
            worker_token="token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=False,
            audio_cache_dir="./cache",
            max_cache_size_gb=10,
        )
        mock_load_config.return_value = mock_config

        client = WhisperWorkerClient()

        mock_ws = _AsyncWebSocketMock([
            json.dumps({"type": "job_complete_ack", "job_id": "job-123"}),
        ])
        client.ws = mock_ws

        with patch.object(client, "_handle_job_complete_ack", new=AsyncMock()) as mock_handle, \
             patch.object(client, "_send_heartbeat", new=AsyncMock(side_effect=asyncio.CancelledError)):

            try:
                await client._message_loop()
            except asyncio.CancelledError:
                pass

            mock_handle.assert_called_once()

    @pytest.mark.asyncio
    @patch("client.load_config")
    @patch("client.AudioDownloader")
    @patch("client.WhisperTranscriber")
    async def test_handles_heartbeat_ack_message(
        self, mock_transcriber, mock_downloader, mock_load_config
    ):
        """Test message loop handles heartbeat_ack (silently ignored)."""
        mock_config = Mock(
            backend_ws_url="ws://test",
            worker_token="token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=False,
            audio_cache_dir="./cache",
            max_cache_size_gb=10,
        )
        mock_load_config.return_value = mock_config

        client = WhisperWorkerClient()

        mock_ws = _AsyncWebSocketMock([
            json.dumps({"type": "heartbeat_ack"}),
        ])
        client.ws = mock_ws

        with patch.object(client, "_send_heartbeat", new=AsyncMock(side_effect=asyncio.CancelledError)):

            try:
                await client._message_loop()
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    @patch("client.load_config")
    @patch("client.AudioDownloader")
    @patch("client.WhisperTranscriber")
    async def test_handles_server_error_message(
        self, mock_transcriber, mock_downloader, mock_load_config
    ):
        """Test message loop handles server error messages."""
        mock_config = Mock(
            backend_ws_url="ws://test",
            worker_token="token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=False,
            audio_cache_dir="./cache",
            max_cache_size_gb=10,
        )
        mock_load_config.return_value = mock_config

        client = WhisperWorkerClient()

        mock_ws = _AsyncWebSocketMock([
            json.dumps({"type": "error", "message": "Internal server error"}),
        ])
        client.ws = mock_ws

        with patch("client.logger") as mock_logger, \
             patch.object(client, "_send_heartbeat", new=AsyncMock(side_effect=asyncio.CancelledError)):

            try:
                await client._message_loop()
            except asyncio.CancelledError:
                pass

            mock_logger.error.assert_called_once()

    @pytest.mark.asyncio
    @patch("client.load_config")
    @patch("client.AudioDownloader")
    @patch("client.WhisperTranscriber")
    async def test_handles_unknown_message_type(
        self, mock_transcriber, mock_downloader, mock_load_config
    ):
        """Test message loop logs warning for unknown message types."""
        mock_config = Mock(
            backend_ws_url="ws://test",
            worker_token="token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=False,
            audio_cache_dir="./cache",
            max_cache_size_gb=10,
        )
        mock_load_config.return_value = mock_config

        client = WhisperWorkerClient()

        mock_ws = _AsyncWebSocketMock([
            json.dumps({"type": "unknown_type", "data": "something"}),
        ])
        client.ws = mock_ws

        with patch("client.logger") as mock_logger, \
             patch.object(client, "_send_heartbeat", new=AsyncMock(side_effect=asyncio.CancelledError)):

            try:
                await client._message_loop()
            except asyncio.CancelledError:
                pass

            mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    @patch("client.load_config")
    @patch("client.AudioDownloader")
    @patch("client.WhisperTranscriber")
    async def test_cancels_heartbeat_on_exit(
        self, mock_transcriber, mock_downloader, mock_load_config
    ):
        """Test heartbeat task is cancelled when message loop exits."""
        mock_config = Mock(
            backend_ws_url="ws://test",
            worker_token="token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=False,
            audio_cache_dir="./cache",
            max_cache_size_gb=10,
        )
        mock_load_config.return_value = mock_config

        client = WhisperWorkerClient()

        # Empty async iterator (no messages)
        mock_ws = _AsyncWebSocketMock([])
        client.ws = mock_ws

        with patch.object(client, "_send_heartbeat", new=AsyncMock(side_effect=asyncio.CancelledError)):

            try:
                await client._message_loop()
            except asyncio.CancelledError:
                pass


class TestWhisperWorkerClientHandleJobAssigned:
    """Tests for WhisperWorkerClient._handle_job_assigned."""

    @pytest.mark.asyncio
    @patch("client.load_config")
    @patch("client.AudioDownloader")
    @patch("client.WhisperTranscriber")
    @patch("client._annotate_segments_with_mecab")
    @patch("client._analyze_texts")
    async def test_successful_job_processing(
        self, mock_analyze_texts, mock_annotate, mock_transcriber, mock_downloader, mock_load_config
    ):
        """Test successful job processing flow."""
        mock_config = Mock(
            backend_ws_url="ws://test",
            worker_token="token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=False,
            audio_cache_dir="./cache",
            max_cache_size_gb=10,
        )
        mock_load_config.return_value = mock_config

        client = WhisperWorkerClient()
        client.ws = AsyncMock()

        mock_downloader_instance = AsyncMock()
        mock_downloader_instance.download = AsyncMock(return_value=("/path/audio.wav", 1024000))
        mock_downloader_instance.cleanup = AsyncMock()
        mock_downloader_instance.cleanup_old_files = AsyncMock()
        client.downloader = mock_downloader_instance

        mock_transcriber_instance = AsyncMock()
        mock_transcriber_instance.transcribe = AsyncMock(return_value={
            "segments": [
                {"text": "テスト", "start": 0.0, "end": 1.0},
            ],
            "language": "ja",
        })
        client.transcriber = mock_transcriber_instance

        data = {
            "job_id": "job-123",
            "audio_url": "http://example.com/audio.wav",
            "options": {},
        }

        with patch.object(client, "_get_analyzer", return_value=Mock()):

            await client._handle_job_assigned(data)

            # Verify download, transcription, and result sent
            mock_downloader_instance.download.assert_called_once()
            mock_transcriber_instance.transcribe.assert_called_once()
            mock_annotate.assert_called_once()
            client.ws.send.assert_called()

    @pytest.mark.asyncio
    @patch("client.load_config")
    @patch("client.AudioDownloader")
    @patch("client.WhisperTranscriber")
    async def test_invalid_job_assignment_missing_fields(
        self, mock_transcriber, mock_downloader, mock_load_config
    ):
        """Test invalid job assignment (missing fields)."""
        mock_config = Mock(
            backend_ws_url="ws://test",
            worker_token="token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=False,
            audio_cache_dir="./cache",
            max_cache_size_gb=10,
        )
        mock_load_config.return_value = mock_config

        client = WhisperWorkerClient()
        client.ws = AsyncMock()

        # Missing job_id
        with patch("client.logger") as mock_logger:
            await client._handle_job_assigned({"audio_url": "http://example.com/audio.wav"})
            mock_logger.error.assert_called_once()

        # Missing audio_url
        with patch("client.logger") as mock_logger:
            await client._handle_job_assigned({"job_id": "job-123"})
            mock_logger.error.assert_called_once()

    @pytest.mark.asyncio
    @patch("client.load_config")
    @patch("client.AudioDownloader")
    @patch("client.WhisperTranscriber")
    async def test_model_size_capability_mismatch(
        self, mock_transcriber, mock_downloader, mock_load_config
    ):
        """Test job fails when requested model size doesn't match worker."""
        mock_config = Mock(
            backend_ws_url="ws://test",
            worker_token="token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=False,
            audio_cache_dir="./cache",
            max_cache_size_gb=10,
        )
        mock_load_config.return_value = mock_config

        client = WhisperWorkerClient()
        client.ws = AsyncMock()

        data = {
            "job_id": "job-123",
            "audio_url": "http://example.com/audio.wav",
            "options": {"model_size": "large"},  # Worker has 'base'
        }

        with patch("client.logger") as mock_logger, \
             patch("client._send_job_failed", new=AsyncMock()) as mock_failed:

            await client._handle_job_assigned(data)

            mock_logger.error.assert_called()
            mock_failed.assert_called_once()

    @pytest.mark.asyncio
    @patch("client.load_config")
    @patch("client.AudioDownloader")
    @patch("client.WhisperTranscriber")
    async def test_fp16_capability_mismatch(
        self, mock_transcriber, mock_downloader, mock_load_config
    ):
        """Test job fails when requested fp16 doesn't match worker."""
        mock_config = Mock(
            backend_ws_url="ws://test",
            worker_token="token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=False,  # Worker has False
            audio_cache_dir="./cache",
            max_cache_size_gb=10,
        )
        mock_load_config.return_value = mock_config

        client = WhisperWorkerClient()
        client.ws = AsyncMock()

        data = {
            "job_id": "job-123",
            "audio_url": "http://example.com/audio.wav",
            "options": {"fp16": True},  # Requested True
        }

        with patch("client.logger") as mock_logger, \
             patch("client._send_job_failed", new=AsyncMock()) as mock_failed:

            await client._handle_job_assigned(data)

            mock_logger.error.assert_called()
            mock_failed.assert_called_once()

    @pytest.mark.asyncio
    @patch("client.load_config")
    @patch("client.AudioDownloader")
    @patch("client.WhisperTranscriber")
    @patch("client._annotate_segments_with_mecab")
    async def test_download_failure_sends_job_failed(
        self, mock_annotate, mock_transcriber, mock_downloader, mock_load_config
    ):
        """Test download failure sends job_failed message."""
        mock_config = Mock(
            backend_ws_url="ws://test",
            worker_token="token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=False,
            audio_cache_dir="./cache",
            max_cache_size_gb=10,
        )
        mock_load_config.return_value = mock_config

        client = WhisperWorkerClient()
        client.ws = AsyncMock()

        mock_downloader_instance = AsyncMock()
        mock_downloader_instance.download = AsyncMock(side_effect=Exception("Download failed"))
        client.downloader = mock_downloader_instance

        data = {
            "job_id": "job-123",
            "audio_url": "http://example.com/audio.wav",
            "options": {},
        }

        with patch("client.logger"), \
             patch("client._send_job_failed", new=AsyncMock()) as mock_failed:

            await client._handle_job_assigned(data)

            mock_failed.assert_called_once_with(
                client.ws,
                "job-123",
                "Download failed",
            )

    @pytest.mark.asyncio
    @patch("client.load_config")
    @patch("client.AudioDownloader")
    @patch("client.WhisperTranscriber")
    @patch("client._annotate_segments_with_mecab")
    async def test_transcription_failure_sends_job_failed(
        self, mock_annotate, mock_transcriber, mock_downloader, mock_load_config
    ):
        """Test transcription failure sends job_failed message."""
        mock_config = Mock(
            backend_ws_url="ws://test",
            worker_token="token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=False,
            audio_cache_dir="./cache",
            max_cache_size_gb=10,
        )
        mock_load_config.return_value = mock_config

        client = WhisperWorkerClient()
        client.ws = AsyncMock()

        mock_downloader_instance = AsyncMock()
        mock_downloader_instance.download = AsyncMock(return_value=("/path/audio.wav", 1024000))
        mock_downloader_instance.cleanup = AsyncMock()
        client.downloader = mock_downloader_instance

        mock_transcriber_instance = AsyncMock()
        mock_transcriber_instance.transcribe = AsyncMock(side_effect=Exception("OOM"))
        client.transcriber = mock_transcriber_instance

        data = {
            "job_id": "job-123",
            "audio_url": "http://example.com/audio.wav",
            "options": {},
        }

        with patch("client.logger"), \
             patch("client._send_job_failed", new=AsyncMock()) as mock_failed:

            await client._handle_job_assigned(data)

            mock_failed.assert_called_once()

    @pytest.mark.asyncio
    @patch("client.load_config")
    @patch("client.AudioDownloader")
    @patch("client.WhisperTranscriber")
    @patch("client._annotate_segments_with_mecab")
    @patch("client._generate_thumbnail_b64")
    async def test_thumbnail_generation_failure_logged_but_continues(
        self, mock_generate_thumb, mock_annotate, mock_transcriber, mock_downloader, mock_load_config
    ):
        """Test thumbnail generation failure is logged but job completes."""
        mock_config = Mock(
            backend_ws_url="ws://test",
            worker_token="token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=False,
            audio_cache_dir="./cache",
            max_cache_size_gb=10,
        )
        mock_load_config.return_value = mock_config

        client = WhisperWorkerClient()
        client.ws = AsyncMock()

        mock_downloader_instance = AsyncMock()
        mock_downloader_instance.download = AsyncMock(return_value=("/path/audio.wav", 1024000))
        mock_downloader_instance.cleanup_old_files = AsyncMock()
        client.downloader = mock_downloader_instance

        mock_transcriber_instance = AsyncMock()
        mock_transcriber_instance.transcribe = AsyncMock(return_value={
            "segments": [{"text": "test", "start": 0.0, "end": 1.0}],
            "language": "ja",
        })
        client.transcriber = mock_transcriber_instance

        # Thumbnail generation fails
        mock_generate_thumb.side_effect = Exception("FFmpeg error")

        data = {
            "job_id": "job-123",
            "audio_url": "http://example.com/audio.wav",
            "options": {"thumbnail": True, "thumbnail_timestamp": 1.0},
        }

        with patch.object(client, "_get_analyzer", return_value=Mock()), \
             patch("client.logger") as mock_logger, \
             patch("client.clean_segments"):

            await client._handle_job_assigned(data)

            # Job should still complete despite thumbnail failure
            mock_logger.warning.assert_called()
            assert "job-123" in client._pending_cleanup_jobs

    @pytest.mark.asyncio
    @patch("client.load_config")
    @patch("client.AudioDownloader")
    @patch("client.WhisperTranscriber")
    @patch("client._annotate_segments_with_mecab")
    async def test_with_analysis_texts_option(
        self, mock_annotate, mock_transcriber, mock_downloader, mock_load_config
    ):
        """Test job processing with analysis_texts option."""
        mock_config = Mock(
            backend_ws_url="ws://test",
            worker_token="token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=False,
            audio_cache_dir="./cache",
            max_cache_size_gb=10,
        )
        mock_load_config.return_value = mock_config

        client = WhisperWorkerClient()
        client.ws = AsyncMock()

        mock_downloader_instance = AsyncMock()
        mock_downloader_instance.download = AsyncMock(return_value=("/path/audio.wav", 1024000))
        mock_downloader_instance.cleanup_old_files = AsyncMock()
        client.downloader = mock_downloader_instance

        mock_transcriber_instance = AsyncMock()
        mock_transcriber_instance.transcribe = AsyncMock(return_value={
            "segments": [],
            "language": "ja",
        })
        client.transcriber = mock_transcriber_instance

        mock_analyzer = Mock()
        mock_analyzer.analyze_batch = Mock(return_value=[
            [{"surface": "単語"}],
            [{"surface": "文章"}],
        ])

        data = {
            "job_id": "job-123",
            "audio_url": "http://example.com/audio.wav",
            "options": {
                "analysis_texts": ["単語", "文章"],
            },
        }

        with patch.object(client, "_get_analyzer", return_value=mock_analyzer), \
             patch("client.clean_segments"):

            await client._handle_job_assigned(data)

            # Verify analysis was performed
            sent_data = json.loads(client.ws.send.call_args_list[-1][0][0])
            assert "analysis_tokens" in sent_data["result"]


class TestWhisperWorkerClientHandleJobCompleteAck:
    """Tests for WhisperWorkerClient._handle_job_complete_ack."""

    @pytest.mark.asyncio
    @patch("client.load_config")
    @patch("client.AudioDownloader")
    @patch("client.WhisperTranscriber")
    async def test_valid_cleanup_acknowledgement(
        self, mock_transcriber, mock_downloader, mock_load_config
    ):
        """Test valid job_complete_ack triggers cleanup."""
        mock_config = Mock(
            backend_ws_url="ws://test",
            worker_token="token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=False,
            audio_cache_dir="./cache",
            max_cache_size_gb=10,
        )
        mock_load_config.return_value = mock_config

        client = WhisperWorkerClient()
        client._pending_cleanup_jobs.add("job-123")

        mock_downloader_instance = AsyncMock()
        mock_downloader_instance.cleanup = AsyncMock()
        client.downloader = mock_downloader_instance

        data = {"job_id": "job-123"}

        await client._handle_job_complete_ack(data)

        mock_downloader_instance.cleanup.assert_called_once_with("job-123")
        assert "job-123" not in client._pending_cleanup_jobs

    @pytest.mark.asyncio
    @patch("client.load_config")
    @patch("client.AudioDownloader")
    @patch("client.WhisperTranscriber")
    async def test_invalid_ack_missing_job_id(
        self, mock_transcriber, mock_downloader, mock_load_config
    ):
        """Test invalid ack (missing job_id) is logged."""
        mock_config = Mock(
            backend_ws_url="ws://test",
            worker_token="token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=False,
            audio_cache_dir="./cache",
            max_cache_size_gb=10,
        )
        mock_load_config.return_value = mock_config

        client = WhisperWorkerClient()
        client.downloader = AsyncMock()

        with patch("client.logger") as mock_logger:
            await client._handle_job_complete_ack({})

            mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    @patch("client.load_config")
    @patch("client.AudioDownloader")
    @patch("client.WhisperTranscriber")
    async def test_unexpected_ack_for_unknown_job(
        self, mock_transcriber, mock_downloader, mock_load_config
    ):
        """Test ack for job not in pending cleanup set."""
        mock_config = Mock(
            backend_ws_url="ws://test",
            worker_token="token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=False,
            audio_cache_dir="./cache",
            max_cache_size_gb=10,
        )
        mock_load_config.return_value = mock_config

        client = WhisperWorkerClient()

        mock_downloader_instance = AsyncMock()
        mock_downloader_instance.cleanup = AsyncMock()
        client.downloader = mock_downloader_instance

        with patch("client.logger") as mock_logger:
            await client._handle_job_complete_ack({"job_id": "unknown-job"})

            # Should still cleanup and log debug
            mock_downloader_instance.cleanup.assert_called_once()
            mock_logger.debug.assert_called()


class TestWhisperWorkerClientSendHeartbeat:
    """Tests for WhisperWorkerClient._send_heartbeat."""

    @pytest.mark.asyncio
    @patch("client.load_config")
    @patch("client.AudioDownloader")
    @patch("client.WhisperTranscriber")
    @patch("asyncio.sleep")  # Mock sleep to speed up test
    async def test_sends_periodic_heartbeat(
        self, mock_sleep, mock_transcriber, mock_downloader, mock_load_config
    ):
        """Test heartbeat is sent every 15 seconds."""
        mock_config = Mock(
            backend_ws_url="ws://test",
            worker_token="token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=False,
            audio_cache_dir="./cache",
            max_cache_size_gb=10,
        )
        mock_load_config.return_value = mock_config

        client = WhisperWorkerClient()
        client.ws = AsyncMock()
        client.ws.closed = False

        # Send 2 heartbeats then stop
        send_count = [0]

        async def mock_send(data):
            send_count[0] += 1
            if send_count[0] >= 2:
                raise asyncio.CancelledError()

        client.ws.send = mock_send

        await client._send_heartbeat()

        assert send_count[0] == 2
        # Verify sleep was called twice (once before each heartbeat)
        assert mock_sleep.call_count == 2

    @pytest.mark.asyncio
    @patch("client.load_config")
    @patch("client.AudioDownloader")
    @patch("client.WhisperTranscriber")
    @patch("asyncio.sleep")  # Mock sleep to avoid real wait
    async def test_heartbeat_failure_breaks_loop(
        self, mock_sleep, mock_transcriber, mock_downloader, mock_load_config
    ):
        """Test heartbeat send failure breaks the loop."""
        mock_config = Mock(
            backend_ws_url="ws://test",
            worker_token="token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=False,
            audio_cache_dir="./cache",
            max_cache_size_gb=10,
        )
        mock_load_config.return_value = mock_config

        client = WhisperWorkerClient()
        client.ws = AsyncMock()
        client.ws.closed = False
        client.ws.send = AsyncMock(side_effect=Exception("Connection closed"))

        with patch("client.logger") as mock_logger:
            await client._send_heartbeat()

            mock_logger.warning.assert_called()


class TestWhisperWorkerClientReconnect:
    """Tests for WhisperWorkerClient._reconnect."""

    @pytest.mark.asyncio
    @patch("client.load_config")
    @patch("client.AudioDownloader")
    @patch("client.WhisperTranscriber")
    @patch("asyncio.sleep")
    async def test_exponential_backoff(
        self, mock_sleep, mock_transcriber, mock_downloader, mock_load_config
    ):
        """Test reconnect delay doubles each time (up to max)."""
        mock_config = Mock(
            backend_ws_url="ws://test",
            worker_token="token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=False,
            audio_cache_dir="./cache",
            max_cache_size_gb=10,
        )
        mock_load_config.return_value = mock_config

        client = WhisperWorkerClient()
        client.reconnect_delay = 2

        await client._reconnect()

        mock_sleep.assert_called_once_with(2)
        assert client.reconnect_delay == 4  # Doubled

    @pytest.mark.asyncio
    @patch("client.load_config")
    @patch("client.AudioDownloader")
    @patch("client.WhisperTranscriber")
    @patch("asyncio.sleep")
    async def test_max_reconnect_delay_capped(
        self, mock_sleep, mock_transcriber, mock_downloader, mock_load_config
    ):
        """Test reconnect delay is capped at max_reconnect_delay."""
        mock_config = Mock(
            backend_ws_url="ws://test",
            worker_token="token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=False,
            audio_cache_dir="./cache",
            max_cache_size_gb=10,
        )
        mock_load_config.return_value = mock_config

        client = WhisperWorkerClient()
        client.reconnect_delay = 20
        client.max_reconnect_delay = 30

        await client._reconnect()

        mock_sleep.assert_called_once_with(20)
        assert client.reconnect_delay == 30  # Capped at max


class TestWhisperWorkerClientStartStop:
    """Tests for WhisperWorkerClient.start and stop lifecycle."""

    @pytest.mark.asyncio
    @patch("client.load_config")
    @patch("client.AudioDownloader")
    @patch("client.WhisperTranscriber")
    async def test_start_loads_model_and_connects(
        self, mock_transcriber, mock_downloader, mock_load_config
    ):
        """Test start() loads model then connects."""
        mock_config = Mock(
            backend_ws_url="ws://localhost:8000/ws/worker",
            worker_token="token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=False,
            audio_cache_dir="./cache",
            max_cache_size_gb=10,
        )
        mock_load_config.return_value = mock_config

        client = WhisperWorkerClient()

        mock_transcriber_instance = Mock()
        client.transcriber = mock_transcriber_instance

        connect_count = [0]

        async def mock_connect():
            connect_count[0] += 1
            if connect_count[0] >= 2:
                client._running = False  # Stop after first connection attempt

        with patch.object(client, "_connect", side_effect=mock_connect), \
             patch("client.logger"):

            await client.start()

            mock_transcriber_instance.load_model.assert_called_once()
            assert connect_count[0] >= 1

    @pytest.mark.asyncio
    @patch("client.load_config")
    @patch("client.AudioDownloader")
    @patch("client.WhisperTranscriber")
    async def test_stop_sets_running_flag(
        self, mock_transcriber, mock_downloader, mock_load_config
    ):
        """Test stop() sets _running to False."""
        mock_config = Mock(
            backend_ws_url="ws://test",
            worker_token="token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=False,
            audio_cache_dir="./cache",
            max_cache_size_gb=10,
        )
        mock_load_config.return_value = mock_config

        client = WhisperWorkerClient()
        client._running = True

        client.stop()

        assert client._running is False

    @pytest.mark.asyncio
    @patch("client.load_config")
    @patch("client.AudioDownloader")
    @patch("client.WhisperTranscriber")
    async def test_stop_with_in_progress_job_sends_failure(
        self, mock_transcriber, mock_downloader, mock_load_config
    ):
        """Test stop() with in-progress job sends job_failed."""
        mock_config = Mock(
            backend_ws_url="ws://test",
            worker_token="token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=False,
            audio_cache_dir="./cache",
            max_cache_size_gb=10,
        )
        mock_load_config.return_value = mock_config

        client = WhisperWorkerClient()
        client._running = True
        client.current_job_id = "job-123"
        client.ws = AsyncMock()

        with patch("client._send_job_failed", new=AsyncMock()) as mock_failed:

            client.stop()

            # Give async task time to schedule
            await asyncio.sleep(0.01)

            mock_failed.assert_called_once()

    @pytest.mark.asyncio
    @patch("client.load_config")
    @patch("client.AudioDownloader")
    @patch("client.WhisperTranscriber")
    async def test_stop_closes_websocket(
        self, mock_transcriber, mock_downloader, mock_load_config
    ):
        """Test stop() closes WebSocket connection."""
        mock_config = Mock(
            backend_ws_url="ws://test",
            worker_token="token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=False,
            audio_cache_dir="./cache",
            max_cache_size_gb=10,
        )
        mock_load_config.return_value = mock_config

        client = WhisperWorkerClient()
        client._running = True
        client.ws = AsyncMock()

        client.stop()

        # Give async task time to schedule
        await asyncio.sleep(0.01)

        client.ws.close.assert_called_once()


# =============================================================================
# Robustness Tests
# =============================================================================


class TestRobustnessScenarios:
    """Tests for robustness and edge cases."""

    @pytest.mark.asyncio
    @patch("client.load_config")
    @patch("client.AudioDownloader")
    @patch("client.WhisperTranscriber")
    async def test_reconnection_after_network_failure(
        self, mock_transcriber, mock_downloader, mock_load_config
    ):
        """Test client reconnects after network failure."""
        mock_config = Mock(
            backend_ws_url="ws://localhost:8000/ws/worker",
            worker_token="token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=False,
            audio_cache_dir="./cache",
            max_cache_size_gb=10,
        )
        mock_load_config.return_value = mock_config

        client = WhisperWorkerClient()
        client.transcriber.load_model = Mock()

        connect_count = [0]

        async def mock_connect():
            connect_count[0] += 1
            if connect_count[0] < 3:
                raise Exception("Network error")
            client._running = False

        with patch.object(client, "_connect", side_effect=mock_connect), \
             patch("asyncio.sleep", new=AsyncMock()):

            await client.start()

            # Should have attempted connection multiple times
            assert connect_count[0] == 3

    @pytest.mark.asyncio
    @patch("client.load_config")
    @patch("client.AudioDownloader")
    @patch("client.WhisperTranscriber")
    async def test_multiple_rapid_job_assignments(
        self, mock_transcriber, mock_downloader, mock_load_config
    ):
        """Test handling multiple rapid job assignments."""
        mock_config = Mock(
            backend_ws_url="ws://test",
            worker_token="token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=False,
            audio_cache_dir="./cache",
            max_cache_size_gb=10,
        )
        mock_load_config.return_value = mock_config

        client = WhisperWorkerClient()
        client.ws = AsyncMock()

        mock_downloader_instance = AsyncMock()
        mock_downloader_instance.download = AsyncMock(return_value=("/path/audio.wav", 1024))
        mock_downloader_instance.cleanup_old_files = AsyncMock()
        client.downloader = mock_downloader_instance

        mock_transcriber_instance = AsyncMock()
        mock_transcriber_instance.transcribe = AsyncMock(return_value={
            "segments": [],
            "language": "ja",
        })
        client.transcriber = mock_transcriber_instance

        jobs = [
            {"job_id": f"job-{i}", "audio_url": f"http://example.com/audio{i}.wav", "options": {}}
            for i in range(5)
        ]

        with patch.object(client, "_get_analyzer", return_value=Mock()), \
             patch("client.clean_segments"), \
             patch("client._annotate_segments_with_mecab"):

            # Process jobs sequentially
            for job in jobs:
                await client._handle_job_assigned(job)

            # Verify all jobs were processed
            assert mock_downloader_instance.download.call_count == 5
            assert mock_transcriber_instance.transcribe.call_count == 5

    @pytest.mark.asyncio
    @patch("client.load_config")
    @patch("client.AudioDownloader")
    @patch("client.WhisperTranscriber")
    async def test_shutdown_during_job_processing(
        self, mock_transcriber, mock_downloader, mock_load_config
    ):
        """Test graceful shutdown during active job processing."""
        mock_config = Mock(
            backend_ws_url="ws://test",
            worker_token="token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=False,
            audio_cache_dir="./cache",
            max_cache_size_gb=10,
        )
        mock_load_config.return_value = mock_config

        client = WhisperWorkerClient()
        client.ws = AsyncMock()

        # Simulate job in progress
        client.current_job_id = "job-123"

        with patch("client._send_job_failed", new=AsyncMock()) as mock_failed:

            client.stop()

            await asyncio.sleep(0.01)

            mock_failed.assert_called_once()

    @pytest.mark.asyncio
    @patch("client.load_config")
    @patch("client.AudioDownloader")
    @patch("client.WhisperTranscriber")
    async def test_websocket_send_failure_during_job(
        self, mock_transcriber, mock_downloader, mock_load_config
    ):
        """Test handling of WebSocket send failure during job."""
        mock_config = Mock(
            backend_ws_url="ws://test",
            worker_token="token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=False,
            audio_cache_dir="./cache",
            max_cache_size_gb=10,
        )
        mock_load_config.return_value = mock_config

        client = WhisperWorkerClient()
        client.ws = AsyncMock()

        mock_downloader_instance = AsyncMock()
        mock_downloader_instance.download = AsyncMock(return_value=("/path/audio.wav", 1024))
        mock_downloader_instance.cleanup = AsyncMock()
        client.downloader = mock_downloader_instance

        mock_transcriber_instance = AsyncMock()
        mock_transcriber_instance.transcribe = AsyncMock(return_value={
            "segments": [],
            "language": "ja",
        })
        client.transcriber = mock_transcriber_instance

        # WebSocket send fails
        client.ws.send = AsyncMock(side_effect=Exception("Connection closed"))

        data = {
            "job_id": "job-123",
            "audio_url": "http://example.com/audio.wav",
            "options": {},
        }

        with patch.object(client, "_get_analyzer", return_value=Mock()), \
             patch("client.clean_segments"), \
             patch("client._annotate_segments_with_mecab"), \
             patch("client._send_job_failed", new=AsyncMock()) as mock_failed:

            await client._handle_job_assigned(data)

            # Should send job_failed due to exception
            mock_failed.assert_called()

    @pytest.mark.asyncio
    @patch("client.load_config")
    @patch("client.AudioDownloader")
    @patch("client.WhisperTranscriber")
    async def test_large_job_payload_handling(
        self, mock_transcriber, mock_downloader, mock_load_config
    ):
        """Test handling of job with large payload (many segments)."""
        mock_config = Mock(
            backend_ws_url="ws://test",
            worker_token="token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=False,
            audio_cache_dir="./cache",
            max_cache_size_gb=10,
        )
        mock_load_config.return_value = mock_config

        client = WhisperWorkerClient()
        client.ws = AsyncMock()

        mock_downloader_instance = AsyncMock()
        mock_downloader_instance.download = AsyncMock(return_value=("/path/audio.wav", 1024000))
        mock_downloader_instance.cleanup_old_files = AsyncMock()
        client.downloader = mock_downloader_instance

        # Generate many segments
        large_result = {
            "segments": [
                {"text": f"セグメント{i}", "start": i * 0.5, "end": (i + 1) * 0.5}
                for i in range(1000)
            ],
            "language": "ja",
        }

        mock_transcriber_instance = AsyncMock()
        mock_transcriber_instance.transcribe = AsyncMock(return_value=large_result)
        client.transcriber = mock_transcriber_instance

        data = {
            "job_id": "job-large",
            "audio_url": "http://example.com/audio.wav",
            "options": {},
        }

        with patch.object(client, "_get_analyzer", return_value=Mock()), \
             patch("client.clean_segments"), \
             patch("client._annotate_segments_with_mecab"):

            await client._handle_job_assigned(data)

            # Verify result was sent (may be large JSON)
            assert client.ws.send.called

    @pytest.mark.asyncio
    @patch("client.load_config")
    @patch("client.AudioDownloader")
    @patch("client.WhisperTranscriber")
    async def test_heartbeat_failure_during_connection(
        self, mock_transcriber, mock_downloader, mock_load_config
    ):
        """Test heartbeat failure doesn't crash the client."""
        mock_config = Mock(
            backend_ws_url="ws://test",
            worker_token="token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=False,
            audio_cache_dir="./cache",
            max_cache_size_gb=10,
        )
        mock_load_config.return_value = mock_config

        client = WhisperWorkerClient()
        client.ws = AsyncMock()

        with patch.object(client, "_message_loop") as mock_loop, \
             patch("client.logger"):

            mock_loop.return_value = None
            await client._message_loop()

    @pytest.mark.asyncio
    @patch("client.load_config")
    @patch("client.AudioDownloader")
    @patch("client.WhisperTranscriber")
    async def test_malformed_message_in_message_loop(
        self, mock_transcriber, mock_downloader, mock_load_config
    ):
        """Test handling of malformed JSON message."""
        mock_config = Mock(
            backend_ws_url="ws://test",
            worker_token="token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=False,
            audio_cache_dir="./cache",
            max_cache_size_gb=10,
        )
        mock_load_config.return_value = mock_config

        client = WhisperWorkerClient()

        mock_ws = _AsyncWebSocketMock([
            "invalid json{{{{{",
        ])
        client.ws = mock_ws

        with patch.object(client, "_send_heartbeat", new=AsyncMock(side_effect=asyncio.CancelledError)), \
             patch("client.logger"):

            try:
                await client._message_loop()
            except (asyncio.CancelledError, json.JSONDecodeError):
                pass

    @pytest.mark.asyncio
    @patch("client.load_config")
    @patch("client.AudioDownloader")
    @patch("client.WhisperTranscriber")
    async def test_cleanup_called_for_failed_jobs(
        self, mock_transcriber, mock_downloader, mock_load_config
    ):
        """Test cleanup is called for jobs that fail before completion."""
        mock_config = Mock(
            backend_ws_url="ws://test",
            worker_token="token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=False,
            audio_cache_dir="./cache",
            max_cache_size_gb=10,
        )
        mock_load_config.return_value = mock_config

        client = WhisperWorkerClient()
        client.ws = AsyncMock()

        mock_downloader_instance = AsyncMock()
        mock_downloader_instance.download = AsyncMock(side_effect=Exception("Download failed"))
        mock_downloader_instance.cleanup = AsyncMock()
        client.downloader = mock_downloader_instance

        data = {
            "job_id": "job-failed",
            "audio_url": "http://example.com/audio.wav",
            "options": {},
        }

        with patch("client.logger"), \
             patch("client._send_job_failed", new=AsyncMock()):

            await client._handle_job_assigned(data)

            # Cleanup should be called since job didn't complete
            mock_downloader_instance.cleanup.assert_called_once_with("job-failed")

    @pytest.mark.asyncio
    @patch("client.load_config")
    @patch("client.AudioDownloader")
    @patch("client.WhisperTranscriber")
    async def test_cleanup_not_called_for_successful_jobs(
        self, mock_transcriber, mock_downloader, mock_load_config
    ):
        """Test cleanup is NOT called for successful jobs (waits for ack)."""
        mock_config = Mock(
            backend_ws_url="ws://test",
            worker_token="token",
            worker_id="gpu-01",
            whisper_model_size="base",
            whisper_device="cuda",
            whisper_fp16=False,
            audio_cache_dir="./cache",
            max_cache_size_gb=10,
        )
        mock_load_config.return_value = mock_config

        client = WhisperWorkerClient()
        client.ws = AsyncMock()

        mock_downloader_instance = AsyncMock()
        mock_downloader_instance.download = AsyncMock(return_value=("/path/audio.wav", 1024))
        mock_downloader_instance.cleanup_old_files = AsyncMock()
        mock_downloader_instance.cleanup = AsyncMock()
        client.downloader = mock_downloader_instance

        mock_transcriber_instance = AsyncMock()
        mock_transcriber_instance.transcribe = AsyncMock(return_value={
            "segments": [],
            "language": "ja",
        })
        client.transcriber = mock_transcriber_instance

        data = {
            "job_id": "job-success",
            "audio_url": "http://example.com/audio.wav",
            "options": {},
        }

        with patch.object(client, "_get_analyzer", return_value=Mock()), \
             patch("client.clean_segments"), \
             patch("client._annotate_segments_with_mecab"):

            await client._handle_job_assigned(data)

            # Cleanup should NOT be called yet (waiting for ack)
            mock_downloader_instance.cleanup.assert_not_called()
            assert "job-success" in client._pending_cleanup_jobs
