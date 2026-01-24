"""Tests for processing with worker retry logic and error handling."""

from __future__ import annotations

import asyncio
import base64
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest


class TestTranscribeWithWorker:
    """Test transcribe_with_worker function with retry logic."""

    @pytest.mark.asyncio
    async def test_transcribe_with_worker_no_manager(self):
        """Test transcribe_with_worker when worker manager is not available."""
        from processing import transcribe_with_worker

        with patch("processing.services.worker_manager", None):
            with pytest.raises(RuntimeError, match="Worker manager not available"):
                await transcribe_with_worker(
                    task_id="test_task",
                    file_path="/path/to/audio.mp3",
                )

    @pytest.mark.asyncio
    async def test_transcribe_with_worker_success_first_attempt(self):
        """Test successful transcription on first attempt."""
        from processing import transcribe_with_worker

        # Mock services
        mock_worker_manager = Mock()
        mock_worker_manager.submit_transcribe_job = AsyncMock(
            return_value={"segments": [], "language": "ja"}
        )
        mock_worker_manager.has_active_worker = Mock(return_value=True)

        mock_storage_bridge = Mock()
        mock_storage_bridge.generate_presigned_url = Mock(
            return_value="http://example.com/audio.mp3"
        )
        mock_storage_bridge.revoke_signature = Mock()

        mock_storage = Mock()
        mock_storage.get_full_path = AsyncMock(return_value="/test/storage")

        with patch("processing.services.worker_manager", mock_worker_manager):
            with patch("processing.services.storage_bridge", mock_storage_bridge):
                with patch("processing.services.storage", mock_storage):
                    with patch("processing._prepare_file_for_worker") as mock_prepare:
                        mock_prepare.return_value = ("/path/to/audio.mp3", False)

                        result = await transcribe_with_worker(
                            task_id="test_task",
                            file_path="/path/to/audio.mp3",
                        )

        assert result == {"segments": [], "language": "ja"}
        mock_worker_manager.submit_transcribe_job.assert_called_once()
        mock_storage_bridge.revoke_signature.assert_called_once()

    @pytest.mark.asyncio
    async def test_transcribe_with_worker_retry_on_timeout(self):
        """Test retry on timeout error."""
        from processing import transcribe_with_worker

        # Mock services
        mock_worker_manager = Mock()
        # First call times out, second succeeds
        mock_worker_manager.submit_transcribe_job = AsyncMock(
            side_effect=[asyncio.TimeoutError(), {"segments": [], "language": "ja"}]
        )
        mock_worker_manager.has_active_worker = Mock(return_value=True)

        mock_storage_bridge = Mock()
        mock_storage_bridge.generate_presigned_url = Mock(
            return_value="http://example.com/audio.mp3"
        )
        mock_storage_bridge.revoke_signature = Mock()

        mock_storage = Mock()
        mock_storage.get_full_path = AsyncMock(return_value="/test/storage")

        with patch("processing.services.worker_manager", mock_worker_manager):
            with patch("processing.services.storage_bridge", mock_storage_bridge):
                with patch("processing.services.storage", mock_storage):
                    with patch("processing._prepare_file_for_worker") as mock_prepare:
                        mock_prepare.return_value = ("/path/to/audio.mp3", False)

                        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                            result = await transcribe_with_worker(
                                task_id="test_task",
                                file_path="/path/to/audio.mp3",
                            )

        assert result == {"segments": [], "language": "ja"}
        assert mock_worker_manager.submit_transcribe_job.call_count == 2
        mock_sleep.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_transcribe_with_worker_retry_on_runtime_error(self):
        """Test retry on runtime error (not 'No workers available')."""
        from processing import transcribe_with_worker

        # Mock services
        mock_worker_manager = Mock()
        # First call fails with runtime error, second succeeds
        mock_worker_manager.submit_transcribe_job = AsyncMock(
            side_effect=[RuntimeError("Some error"), {"segments": [], "language": "ja"}]
        )
        mock_worker_manager.has_active_worker = Mock(return_value=True)

        mock_storage_bridge = Mock()
        mock_storage_bridge.generate_presigned_url = Mock(
            return_value="http://example.com/audio.mp3"
        )
        mock_storage_bridge.revoke_signature = Mock()

        mock_storage = Mock()
        mock_storage.get_full_path = AsyncMock(return_value="/test/storage")

        with patch("processing.services.worker_manager", mock_worker_manager):
            with patch("processing.services.storage_bridge", mock_storage_bridge):
                with patch("processing.services.storage", mock_storage):
                    with patch("processing._prepare_file_for_worker") as mock_prepare:
                        mock_prepare.return_value = ("/path/to/audio.mp3", False)

                        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                            result = await transcribe_with_worker(
                                task_id="test_task",
                                file_path="/path/to/audio.mp3",
                            )

        assert result == {"segments": [], "language": "ja"}
        assert mock_worker_manager.submit_transcribe_job.call_count == 2
        mock_sleep.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_transcribe_with_worker_no_workers_available(self):
        """Test error when no workers are available."""
        from processing import transcribe_with_worker

        # Mock services
        mock_worker_manager = Mock()
        mock_worker_manager.has_active_worker = Mock(return_value=False)

        mock_storage_bridge = Mock()
        mock_storage_bridge.generate_presigned_url = Mock(
            return_value="http://example.com/audio.mp3"
        )
        mock_storage_bridge.revoke_signature = Mock()

        mock_storage = Mock()
        mock_storage.get_full_path = AsyncMock(return_value="/test/storage")

        with patch("processing.services.worker_manager", mock_worker_manager):
            with patch("processing.services.storage_bridge", mock_storage_bridge):
                with patch("processing.services.storage", mock_storage):
                    with patch("processing._prepare_file_for_worker") as mock_prepare:
                        mock_prepare.return_value = ("/path/to/audio.mp3", False)

                        with pytest.raises(RuntimeError, match="No workers available"):
                            await transcribe_with_worker(
                                task_id="test_task",
                                file_path="/path/to/audio.mp3",
                            )

        mock_worker_manager.submit_transcribe_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_transcribe_with_worker_all_retries_failed(self):
        """Test when all retry attempts fail."""
        from processing import transcribe_with_worker

        # Mock services
        mock_worker_manager = Mock()
        # All retries fail
        mock_worker_manager.submit_transcribe_job = AsyncMock(
            side_effect=RuntimeError("Transcription failed")
        )
        mock_worker_manager.has_active_worker = Mock(return_value=True)

        mock_storage_bridge = Mock()
        mock_storage_bridge.generate_presigned_url = Mock(
            return_value="http://example.com/audio.mp3"
        )
        mock_storage_bridge.revoke_signature = Mock()

        mock_storage = Mock()
        mock_storage.get_full_path = AsyncMock(return_value="/test/storage")

        with patch("processing.services.worker_manager", mock_worker_manager):
            with patch("processing.services.storage_bridge", mock_storage_bridge):
                with patch("processing.services.storage", mock_storage):
                    with patch("processing._prepare_file_for_worker") as mock_prepare:
                        mock_prepare.return_value = ("/path/to/audio.mp3", False)

                        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                            with pytest.raises(RuntimeError, match="transcription failed"):
                                await transcribe_with_worker(
                                    task_id="test_task",
                                    file_path="/path/to/audio.mp3",
                                )

        assert mock_worker_manager.submit_transcribe_job.call_count == 2  # Default is 2 attempts
        assert mock_sleep.call_count == 1  # Sleep between attempts

    @pytest.mark.asyncio
    async def test_transcribe_with_worker_custom_retry_attempts(self):
        """Test with custom retry attempts setting."""
        from processing import transcribe_with_worker

        # Mock services
        mock_worker_manager = Mock()
        # All retries fail
        mock_worker_manager.submit_transcribe_job = AsyncMock(
            side_effect=RuntimeError("Transcription failed")
        )
        mock_worker_manager.has_active_worker = Mock(return_value=True)

        mock_storage_bridge = Mock()
        mock_storage_bridge.generate_presigned_url = Mock(
            return_value="http://example.com/audio.mp3"
        )
        mock_storage_bridge.revoke_signature = Mock()

        mock_storage = Mock()
        mock_storage.get_full_path = AsyncMock(return_value="/test/storage")

        # Mock settings to return custom retry attempts
        mock_settings = Mock()
        mock_settings.worker_transcribe_retry_attempts = 3
        mock_settings.temp_file_ttl = 3600
        mock_settings.worker_job_timeout = 600

        with patch("processing.services.worker_manager", mock_worker_manager):
            with patch("processing.services.storage_bridge", mock_storage_bridge):
                with patch("processing.services.storage", mock_storage):
                    with patch("processing._prepare_file_for_worker") as mock_prepare:
                        mock_prepare.return_value = ("/path/to/audio.mp3", False)
                        with patch("processing.get_settings", return_value=mock_settings):
                            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                                with pytest.raises(RuntimeError, match="transcription failed"):
                                    await transcribe_with_worker(
                                        task_id="test_task",
                                        file_path="/path/to/audio.mp3",
                                    )

        assert mock_worker_manager.submit_transcribe_job.call_count == 3
        assert mock_sleep.call_count == 2  # Sleep between attempts

    @pytest.mark.asyncio
    async def test_transcribe_with_worker_exception_during_cleanup(self):
        """Test when cleanup fails after all retries."""
        from processing import transcribe_with_worker

        # Mock services
        mock_worker_manager = Mock()
        mock_worker_manager.submit_transcribe_job = AsyncMock(
            side_effect=RuntimeError("Transcription failed")
        )
        mock_worker_manager.has_active_worker = Mock(return_value=True)

        mock_storage_bridge = Mock()
        mock_storage_bridge.generate_presigned_url = Mock(
            return_value="http://example.com/audio.mp3"
        )
        mock_storage_bridge.revoke_signature = Mock()

        mock_storage = Mock()
        mock_storage.get_full_path = AsyncMock(return_value="/test/storage")

        with patch("processing.services.worker_manager", mock_worker_manager):
            with patch("processing.services.storage_bridge", mock_storage_bridge):
                with patch("processing.services.storage", mock_storage):
                    with patch("processing._prepare_file_for_worker") as mock_prepare:
                        # is_temporary=True
                        mock_prepare.return_value = ("/path/to/audio.mp3", True)
                        with patch("processing._cleanup_worker_file") as mock_cleanup:
                            mock_cleanup.side_effect = Exception("Cleanup failed")

                            with patch("asyncio.sleep", new_callable=AsyncMock):
                                with pytest.raises(RuntimeError, match="transcription failed"):
                                    await transcribe_with_worker(
                                        task_id="test_task",
                                        file_path="/path/to/audio.mp3",
                                    )

        mock_cleanup.assert_called_once()


class TestPrepareFileForWorker:
    """Test _prepare_file_for_worker function."""

    @pytest.mark.asyncio
    async def test_prepare_file_storage_path(self):
        """Test preparing a file that's already in storage."""
        from processing import _prepare_file_for_worker

        # Mock services
        mock_storage = Mock()
        mock_storage.root_dir = Path("/test/storage")
        mock_storage.exists = AsyncMock(return_value=True)

        with patch("processing.services.storage", mock_storage):
            with patch("processing.services.worker_temp_dir", "/tmp/test"):
                worker_path, is_temp = await _prepare_file_for_worker(
                    file_path="/test/storage/abc/test_file.mp3",
                    task_id="test_task",
                )

        assert worker_path == "test_file.mp3"
        assert is_temp is False

    @pytest.mark.asyncio
    async def test_prepare_file_storage_path_not_exists(self):
        """Test preparing a file that's in storage path but doesn't exist."""
        from processing import _prepare_file_for_worker

        # Mock services
        mock_storage = Mock()
        mock_storage.root_dir = Path("/test/storage")
        mock_storage.exists = AsyncMock(return_value=False)

        with patch("processing.services.storage", mock_storage):
            with patch("processing.services.worker_temp_dir", "/tmp/test"):
                with patch("shutil.copy2"):
                    worker_path, is_temp = await _prepare_file_for_worker(
                        file_path="/test/storage/abc/test_file.mp3",
                        task_id="test_task",
                    )

        # Should fall back to temp copy
        assert is_temp is True
        assert "test_task" in worker_path

    @pytest.mark.asyncio
    async def test_prepare_file_temp_file(self):
        """Test preparing a temp file."""
        from processing import _prepare_file_for_worker

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a test file
            test_file = Path(tmpdir) / "test_audio.mp3"
            test_file.write_bytes(b"test audio data")

            with patch("processing.services.worker_temp_dir", tmpdir):
                with patch("processing.services.storage", None):
                    worker_path, is_temp = await _prepare_file_for_worker(
                        file_path=str(test_file),
                        task_id="test_task",
                    )

        assert is_temp is True
        assert "test_task" in worker_path
        assert worker_path.endswith(".mp3")

    @pytest.mark.asyncio
    async def test_prepare_file_temp_file_no_extension(self):
        """Test preparing a temp file without extension."""
        from processing import _prepare_file_for_worker

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a test file without extension
            test_file = Path(tmpdir) / "test_audio"
            test_file.write_bytes(b"test audio data")

            with patch("processing.services.worker_temp_dir", tmpdir):
                with patch("processing.services.storage", None):
                    worker_path, is_temp = await _prepare_file_for_worker(
                        file_path=str(test_file),
                        task_id="test_task",
                    )

        assert is_temp is True
        assert "test_task" in worker_path
        assert worker_path.endswith(".wav")  # Default extension


class TestCleanupWorkerFile:
    """Test _cleanup_worker_file function."""

    @pytest.mark.asyncio
    async def test_cleanup_temp_file(self):
        """Test cleaning up a temp file."""
        from processing import _cleanup_worker_file

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a test file
            test_file = Path(tmpdir) / "test_audio.mp3"
            test_file.write_bytes(b"test audio data")

            await _cleanup_worker_file(str(test_file), is_temporary=True)

            # File should be deleted
            assert not test_file.exists()

    @pytest.mark.asyncio
    async def test_cleanup_storage_file(self):
        """Test cleaning up a storage file (should not delete)."""
        from processing import _cleanup_worker_file

        # Mock storage file path
        storage_path = "abc/test_file.mp3"

        await _cleanup_worker_file(storage_path, is_temporary=False)

    @pytest.mark.asyncio
    async def test_cleanup_nonexistent_file(self):
        """Test cleaning up a non-existent file."""
        from processing import _cleanup_worker_file

        # Should not raise exception
        await _cleanup_worker_file("/nonexistent/file.mp3", is_temporary=True)


class TestWorkerTempDir:
    """Test _get_worker_temp_dir function."""

    def test_get_worker_temp_dir_success(self):
        """Test getting worker temp directory when initialized."""
        from processing import _get_worker_temp_dir

        with patch("processing.services.worker_temp_dir", "/test/temp/dir"):
            result = _get_worker_temp_dir()
            assert result == "/test/temp/dir"

    def test_get_worker_temp_dir_not_initialized(self):
        """Test getting worker temp directory when not initialized."""
        from processing import _get_worker_temp_dir

        with patch("processing.services.worker_temp_dir", ""):
            with pytest.raises(RuntimeError, match="Services not initialized"):
                _get_worker_temp_dir()


class TestSaveWorkerThumbnail:
    """Test _save_worker_thumbnail helper."""

    @pytest.mark.asyncio
    async def test_save_worker_thumbnail_success(self):
        from processing import _save_worker_thumbnail

        mock_storage = Mock()
        mock_storage.save = AsyncMock(return_value="upload_thumb.jpg")

        payload = base64.b64encode(b"thumb-bytes").decode("ascii")
        result = await _save_worker_thumbnail(
            task_id="task-1",
            storage=mock_storage,
            video_id="upload_abc123",
            thumbnail_b64=payload,
        )

        assert result == "upload_abc123_thumb.jpg"
        args, _ = mock_storage.save.call_args
        assert args[1] == "upload_abc123_thumb.jpg"

    @pytest.mark.asyncio
    async def test_save_worker_thumbnail_invalid_payload(self):
        from processing import _save_worker_thumbnail

        mock_storage = Mock()
        mock_storage.save = AsyncMock(return_value="upload_thumb.jpg")

        result = await _save_worker_thumbnail(
            task_id="task-1",
            storage=mock_storage,
            video_id="upload_abc123",
            thumbnail_b64="not-base64",
        )

        assert result is None
        mock_storage.save.assert_not_called()


class TestTranscribeWithWorkerSettings:
    """Test transcribe_with_worker with different settings."""

    @pytest.mark.asyncio
    async def test_transcribe_with_worker_zero_retries(self):
        """Test with zero retry attempts (immediate error)."""
        from processing import transcribe_with_worker

        # Mock services
        mock_worker_manager = Mock()
        mock_worker_manager.submit_transcribe_job = AsyncMock(
            side_effect=RuntimeError("Transcription failed")
        )
        mock_worker_manager.has_active_worker = Mock(return_value=True)

        mock_storage_bridge = Mock()
        mock_storage_bridge.generate_presigned_url = Mock(
            return_value="http://example.com/audio.mp3"
        )
        mock_storage_bridge.revoke_signature = Mock()
        mock_storage = Mock()
        mock_storage.get_full_path = AsyncMock(return_value="/test/storage")

        # Mock settings to return 0 retry attempts
        mock_settings = Mock()
        mock_settings.worker_transcribe_retry_attempts = 0
        mock_settings.temp_file_ttl = 3600
        mock_settings.worker_job_timeout = 600

        with patch("processing.services.worker_manager", mock_worker_manager):
            with patch("processing.services.storage_bridge", mock_storage_bridge):
                with patch("processing.services.storage", mock_storage):
                    with patch("processing._prepare_file_for_worker") as mock_prepare:
                        mock_prepare.return_value = ("/path/to/audio.mp3", False)
                        with patch("processing.get_settings", return_value=mock_settings):
                            with pytest.raises(RuntimeError, match="retries disabled"):
                                await transcribe_with_worker(
                                    task_id="test_task",
                                    file_path="/path/to/audio.mp3",
                                )

        mock_worker_manager.submit_transcribe_job.assert_not_called()


def test_build_analysis_texts_from_metadata():
    """Test building analysis texts from deduplicated subtitle metadata."""
    from processing import _build_analysis_texts

    merged_text = "ABCDEF"
    char_metadata = [
        {"seg_idx": 0, "seg_start": 0.0, "seg_end": 1.0},
        {"seg_idx": 0, "seg_start": 0.0, "seg_end": 1.0},
        {"seg_idx": 1, "seg_start": 1.0, "seg_end": 2.0},
        {"seg_idx": 1, "seg_start": 1.0, "seg_end": 2.0},
        {"seg_idx": 2, "seg_start": 2.0, "seg_end": 3.0},
        {"seg_idx": 2, "seg_start": 2.0, "seg_end": 3.0},
    ]

    assert _build_analysis_texts(merged_text, char_metadata) == ["AB", "CD", "EF"]
