"""Tests for services_registry worker temp directory management."""

from __future__ import annotations

import asyncio
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


@contextmanager
def _mock_services_registry():
    settings = SimpleNamespace(
        storage_root_dir="/tmp/storage",
        worker_api_tokens="{}",
        worker_heartbeat_interval=15,
        worker_heartbeat_timeout=30,
        worker_job_timeout=600,
        backend_base_url="http://localhost:8000",
        temp_file_ttl=3600,
    )

    with patch("services_registry.settings", settings):
        with patch("services_registry.logger"):
            with patch("services_registry.VideoDownloader"):
                with patch("services_registry.Aligner"):
                    with patch("services_registry.Translator"):
                        with patch("services_registry.SubtitleLinearizer"):
                            with patch("services_registry.VocabularyAnalyzer"):
                                with patch("services_registry.LocalStorage"):
                                    yield


class TestWorkerTempDir:
    """Test worker temp directory initialization and cleanup."""

    def test_init_services_creates_temp_dir(self):
        """Test that init_services creates worker temp directory."""
        import services_registry

        # Reset the module state
        services_registry.worker_temp_dir = ""
        services_registry.worker_instance_id = ""

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("tempfile.gettempdir", return_value=tmpdir):
                with _mock_services_registry():
                    services_registry.init_services()

            # Verify temp directory was created
            assert services_registry.worker_temp_dir != ""
            assert services_registry.worker_instance_id != ""
            assert os.path.exists(services_registry.worker_temp_dir)

            # Cleanup
            if os.path.exists(services_registry.worker_temp_dir):
                import shutil

                shutil.rmtree(services_registry.worker_temp_dir)

    def test_init_services_temp_dir_unique_per_instance(self):
        """Test that each instance gets a unique temp directory."""
        import services_registry

        # Reset the module state
        services_registry.worker_temp_dir = ""
        services_registry.worker_instance_id = ""

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("tempfile.gettempdir", return_value=tmpdir):
                with _mock_services_registry():
                    services_registry.init_services()
                    first_temp_dir = services_registry.worker_temp_dir
                    first_instance_id = services_registry.worker_instance_id

                    # Reset and init again
                    services_registry.worker_temp_dir = ""
                    services_registry.worker_instance_id = ""
                    services_registry.init_services()
                    second_temp_dir = services_registry.worker_temp_dir
                    second_instance_id = services_registry.worker_instance_id

        # Verify different instances get different temp directories
        assert first_temp_dir != second_temp_dir
        assert first_instance_id != second_instance_id

        # Cleanup
        for temp_dir in [first_temp_dir, second_temp_dir]:
            if os.path.exists(temp_dir):
                import shutil

                shutil.rmtree(temp_dir)

    def test_cleanup_worker_temp_dir_success(self):
        """Test successful cleanup of worker temp directory."""
        import services_registry

        # Create a temporary directory
        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = os.path.join(tmpdir, "test_worker_dir")
            os.makedirs(test_dir)

            # Create a test file in the directory
            test_file = os.path.join(test_dir, "test.txt")
            with open(test_file, "w") as f:
                f.write("test")

            # Set the worker temp dir
            services_registry.worker_temp_dir = test_dir

            # Call cleanup
            services_registry.cleanup_worker_temp_dir()

            # Verify directory was deleted
            assert not os.path.exists(test_dir)

    def test_cleanup_worker_temp_dir_nonexistent(self):
        """Test cleanup when directory doesn't exist."""
        import services_registry

        # Set to a non-existent directory
        services_registry.worker_temp_dir = "/nonexistent/dir/that/does/not/exist"

        # Should not raise exception
        services_registry.cleanup_worker_temp_dir()

    def test_cleanup_worker_temp_dir_permission_error(self):
        """Test cleanup when permission error occurs."""
        import services_registry

        # Create a temporary directory
        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = os.path.join(tmpdir, "test_worker_dir")
            os.makedirs(test_dir)

            # Set the worker temp dir
            services_registry.worker_temp_dir = test_dir

            # Mock shutil.rmtree to raise permission error
            with patch("shutil.rmtree", side_effect=PermissionError("Permission denied")):
                # Should not raise exception
                services_registry.cleanup_worker_temp_dir()

            # Cleanup
            import shutil

            shutil.rmtree(test_dir, ignore_errors=True)

    def test_cleanup_worker_temp_dir_with_files(self):
        """Test cleanup when directory contains files."""
        import services_registry

        # Create a temporary directory with files
        with tempfile.TemporaryDirectory() as tmpdir:
            test_dir = os.path.join(tmpdir, "test_worker_dir")
            os.makedirs(test_dir)

            # Create multiple files
            for i in range(3):
                test_file = os.path.join(test_dir, f"test_{i}.mp3")
                with open(test_file, "w") as f:
                    f.write(f"test content {i}")

            # Set the worker temp dir
            services_registry.worker_temp_dir = test_dir

            # Call cleanup
            services_registry.cleanup_worker_temp_dir()

            # Verify directory and files were deleted
            assert not os.path.exists(test_dir)

    def test_worker_temp_dir_path_format(self):
        """Test that worker temp directory path is correctly formatted."""
        import services_registry

        # Reset the module state
        services_registry.worker_temp_dir = ""
        services_registry.worker_instance_id = ""

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("tempfile.gettempdir", return_value=tmpdir):
                with _mock_services_registry():
                    services_registry.init_services()
                    # Verify path format
                    expected_prefix = os.path.join(tmpdir, "shadowpartner_worker_")
                    assert services_registry.worker_temp_dir.startswith(expected_prefix)
                    assert len(services_registry.worker_instance_id) == 8  # 8 hex chars

                    # Cleanup
                    if os.path.exists(services_registry.worker_temp_dir):
                        import shutil

                        shutil.rmtree(services_registry.worker_temp_dir)


class TestWorkerTempDirModuleLevel:
    """Test module-level worker temp directory functions."""

    def test_get_worker_temp_dir_from_services(self):
        """Test getting worker temp directory from services registry."""
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

    def test_get_worker_temp_dir_from_internal_api(self):
        """Test getting worker temp directory from internal API."""
        from routers.internal import _get_worker_temp_dir

        with patch("services_registry.worker_temp_dir", "/test/temp/dir"):
            result = _get_worker_temp_dir()
            assert result == "/test/temp/dir"

    def test_get_worker_temp_dir_internal_api_not_initialized(self):
        """Test getting worker temp directory from internal API when not initialized."""
        from routers.internal import _get_worker_temp_dir

        with patch("services_registry.worker_temp_dir", ""):
            with pytest.raises(RuntimeError, match="Services not initialized"):
                _get_worker_temp_dir()


class TestWorkerTempDirIntegration:
    """Integration tests for worker temp directory."""

    @pytest.mark.asyncio
    async def test_prepare_file_uses_worker_temp_dir(self):
        """Test that _prepare_file_for_worker uses worker temp directory."""
        import tempfile

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

        # Verify file was copied to worker temp directory
        assert is_temp is True
        assert tmpdir in worker_path
        assert "test_task" in worker_path

        # Cleanup
        if os.path.exists(worker_path):
            os.remove(worker_path)

    @pytest.mark.asyncio
    async def test_cleanup_worker_file_removes_from_temp_dir(self):
        """Test that _cleanup_worker_file removes files from temp directory."""
        import tempfile

        from processing import _cleanup_worker_file

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a test file in temp directory
            test_file = Path(tmpdir) / "test_audio.mp3"
            test_file.write_bytes(b"test audio data")

            await _cleanup_worker_file(str(test_file), is_temporary=True)

            # Verify file was deleted
            assert not test_file.exists()

    @pytest.mark.asyncio
    async def test_cleanup_worker_file_preserves_storage_files(self):
        """Test that _cleanup_worker_file preserves storage files."""
        from processing import _cleanup_worker_file

        storage_path = "abc/test_file.mp3"

        await _cleanup_worker_file(storage_path, is_temporary=False)


class TestWorkerTempDirConcurrency:
    """Test worker temp directory with concurrent operations."""

    @pytest.mark.asyncio
    async def test_concurrent_prepare_files(self):
        """Test concurrent file preparation uses unique temp files."""
        import tempfile

        from processing import _prepare_file_for_worker

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            test_files = []
            for i in range(3):
                test_file = Path(tmpdir) / f"test_audio_{i}.mp3"
                test_file.write_bytes(b"test audio data")
                test_files.append(str(test_file))

            with patch("processing.services.worker_temp_dir", tmpdir):
                with patch("processing.services.storage", None):
                    # Prepare files concurrently
                    tasks = [
                        _prepare_file_for_worker(file_path, f"task_{i}")
                        for i, file_path in enumerate(test_files)
                    ]
                    results = await asyncio.gather(*tasks)

            # Verify each file got a unique temp path
            worker_paths = [r[0] for r in results]
            assert len(set(worker_paths)) == 3  # All unique

            # Cleanup
            for path in worker_paths:
                if os.path.exists(path):
                    os.remove(path)
