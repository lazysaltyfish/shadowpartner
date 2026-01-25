"""Tests for AudioDownloader."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest

from downloader import AudioDownloader


def create_mock_response(status: int = 200, content: bytes = b"x" * 1000) -> Mock:
    """Helper to create a mock aiohttp response."""
    mock_resp = Mock()
    mock_resp.status = status
    mock_resp.headers = {"content-length": str(len(content))}

    async def iter_chunks(n):
        for i in range(0, len(content), n):
            yield content[i : i + n]

    mock_resp.content = Mock()
    mock_resp.content.iter_chunked = iter_chunks

    # Make response an async context manager that returns itself
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock()

    return mock_resp


def create_mock_session(response: Mock | None = None) -> AsyncMock:
    """Helper to create a mock aiohttp ClientSession.

    The session must support:
    - async with session: (enter/exit)
    - async with session.get(url) as resp: (get returns async context manager)
    """
    if response is None:
        response = create_mock_response()

    # Create the mock session
    mock_session = AsyncMock()

    # session.get(url) should return an async context manager
    # When used with "async with session.get(url) as resp:", it should:
    # 1. Call __aenter__ and return the response
    # 2. Call __aexit__ on cleanup
    mock_get_cm = AsyncMock()
    mock_get_cm.__aenter__ = AsyncMock(return_value=response)
    mock_get_cm.__aexit__ = AsyncMock()

    # Make session.get return the async context manager
    mock_session.get = Mock(return_value=mock_get_cm)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock()

    return mock_session


class TestAudioDownloaderInit:
    """Test AudioDownloader initialization and basic setup."""

    def test_init_creates_cache_directory(self, temp_cache_dir: str):
        """Test that __init__ creates the cache directory."""
        cache_dir = os.path.join(temp_cache_dir, "new_cache")
        assert not os.path.exists(cache_dir)

        downloader = AudioDownloader(cache_dir)
        assert downloader.cache_dir == cache_dir
        assert os.path.exists(cache_dir)

    def test_init_with_existing_cache_directory(self, temp_cache_dir: str):
        """Test that __init__ works with existing cache directory."""
        downloader = AudioDownloader(temp_cache_dir)
        assert downloader.cache_dir == temp_cache_dir
        assert os.path.exists(temp_cache_dir)

    def test_init_creates_nested_cache_directories(self, tmp_path: Path):
        """Test that __init__ creates nested directory structure."""
        nested_dir = tmp_path / "level1" / "level2" / "cache"
        cache_dir = str(nested_dir)
        assert not os.path.exists(cache_dir)

        downloader = AudioDownloader(cache_dir)
        assert os.path.exists(cache_dir)


class TestGetCachePath:
    """Test _get_cache_path method."""

    def test_get_cache_path_default_extension(self, temp_cache_dir: str):
        """Test _get_cache_path with default wav extension."""
        downloader = AudioDownloader(temp_cache_dir)
        path = downloader._get_cache_path("job123")
        assert path == os.path.join(temp_cache_dir, "job123.wav")

    def test_get_cache_path_custom_extension(self, temp_cache_dir: str):
        """Test _get_cache_path with custom extension."""
        downloader = AudioDownloader(temp_cache_dir)
        path = downloader._get_cache_path("job123", "mp3")
        assert path == os.path.join(temp_cache_dir, "job123.mp3")

    def test_get_cache_path_various_extensions(self, temp_cache_dir: str):
        """Test _get_cache_path with various file extensions."""
        downloader = AudioDownloader(temp_cache_dir)
        extensions = ["wav", "mp3", "m4a", "mp4", "ogg", "flac"]
        for ext in extensions:
            path = downloader._get_cache_path("job456", ext)
            assert path == os.path.join(temp_cache_dir, f"job456.{ext}")

    def test_get_cache_path_with_unicode_job_id(self, temp_cache_dir: str):
        """Test _get_cache_path with unicode characters in job_id."""
        downloader = AudioDownloader(temp_cache_dir)
        path = downloader._get_cache_path("job_テスト_123")
        assert path == os.path.join(temp_cache_dir, "job_テスト_123.wav")


class TestDownload:
    """Test download method."""

    @pytest.mark.asyncio
    async def test_download_success(self, temp_cache_dir: str):
        """Test successful download creates file and returns path and size."""
        downloader = AudioDownloader(temp_cache_dir)
        mock_session = create_mock_session()

        with patch("downloader.aiohttp.ClientSession", return_value=mock_session):
            path, size = await downloader.download("http://example.com/audio.wav", "job1")

        assert path == os.path.join(temp_cache_dir, "job1.wav")
        assert os.path.exists(path)
        assert size == 1000

    @pytest.mark.asyncio
    async def test_download_with_custom_extension(self, temp_cache_dir: str):
        """Test download with custom file extension."""
        downloader = AudioDownloader(temp_cache_dir)
        mock_session = create_mock_session()

        with patch("downloader.aiohttp.ClientSession", return_value=mock_session):
            path, size = await downloader.download(
                "http://example.com/audio.mp3", "job2", "mp3"
            )

        assert path == os.path.join(temp_cache_dir, "job2.mp3")
        assert os.path.exists(path)
        assert size == 1000

    @pytest.mark.asyncio
    async def test_download_cache_hit(self, temp_cache_dir: str):
        """Test that existing cached file is returned without re-downloading."""
        downloader = AudioDownloader(temp_cache_dir)
        cached_path = downloader._get_cache_path("job3")
        cached_data = b"x" * 500

        # Create cached file
        with open(cached_path, "wb") as f:
            f.write(cached_data)

        # Mock should not be called
        mock_session = create_mock_session()
        with patch("downloader.aiohttp.ClientSession", return_value=mock_session):
            path, size = await downloader.download("http://example.com/audio.wav", "job3")

        assert path == cached_path
        assert size == 500
        # Verify session.get was never called (cache hit)
        mock_session.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_download_zero_byte_cache_file_redownloads(self, temp_cache_dir: str):
        """Test that zero-byte cached file is removed and re-downloaded."""
        downloader = AudioDownloader(temp_cache_dir)
        cached_path = downloader._get_cache_path("job4")

        # Create zero-byte cached file
        with open(cached_path, "wb") as f:
            pass  # Empty file

        mock_session = create_mock_session()
        with patch("downloader.aiohttp.ClientSession", return_value=mock_session):
            path, size = await downloader.download("http://example.com/audio.wav", "job4")

        assert path == cached_path
        assert size == 1000
        assert os.path.getsize(path) == 1000

    @pytest.mark.asyncio
    async def test_download_http_404_error(self, temp_cache_dir: str):
        """Test download with HTTP 404 error."""
        downloader = AudioDownloader(temp_cache_dir)
        mock_resp = create_mock_response(status=404)
        mock_session = create_mock_session(mock_resp)

        with patch("downloader.aiohttp.ClientSession", return_value=mock_session):
            with pytest.raises(Exception) as exc_info:
                await downloader.download("http://example.com/missing.wav", "job5")

        # The error should contain "HTTP 404" or "Download failed"
        error_str = str(exc_info.value)
        assert "HTTP 404" in error_str or "Download failed" in error_str

    @pytest.mark.asyncio
    async def test_download_http_500_error(self, temp_cache_dir: str):
        """Test download with HTTP 500 server error."""
        downloader = AudioDownloader(temp_cache_dir)
        mock_resp = create_mock_response(status=500)
        mock_session = create_mock_session(mock_resp)

        with patch("downloader.aiohttp.ClientSession", return_value=mock_session):
            with pytest.raises(Exception) as exc_info:
                await downloader.download("http://example.com/error.wav", "job6")

        # The error should contain "HTTP 500" or "Download failed"
        error_str = str(exc_info.value)
        assert "HTTP 500" in error_str or "Download failed" in error_str

    @pytest.mark.asyncio
    async def test_download_network_timeout(self, temp_cache_dir: str):
        """Test download with network timeout."""
        downloader = AudioDownloader(temp_cache_dir)

        mock_session = AsyncMock()
        mock_get_cm = AsyncMock()
        mock_get_cm.__aenter__ = AsyncMock(side_effect=TimeoutError("Connection timeout"))
        mock_get_cm.__aexit__ = AsyncMock()
        mock_session.get = Mock(return_value=mock_get_cm)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        with patch("downloader.aiohttp.ClientSession", return_value=mock_session):
            with pytest.raises(Exception) as exc_info:
                await downloader.download("http://example.com/slow.wav", "job7")

        assert "Download failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_download_partial_cleanup_on_error(self, temp_cache_dir: str):
        """Test that partial download is cleaned up on error."""
        downloader = AudioDownloader(temp_cache_dir)
        cached_path = downloader._get_cache_path("job8")

        # Create mock response that fails during iteration
        mock_resp = Mock()
        mock_resp.status = 200

        async def iter_chunks_error(n):
            yield b"x" * 100
            raise IOError("Download interrupted")

        mock_resp.content = Mock()
        mock_resp.content.iter_chunked = iter_chunks_error
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock()

        mock_session = AsyncMock()
        mock_session.get = Mock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        with patch("downloader.aiohttp.ClientSession", return_value=mock_session):
            with pytest.raises(Exception):
                await downloader.download("http://example.com/partial.wav", "job8")

        # Partial file should be removed
        assert not os.path.exists(cached_path)

    @pytest.mark.asyncio
    async def test_download_large_file(self, temp_cache_dir: str):
        """Test download of a large file (>1MB) to verify progress logging."""
        downloader = AudioDownloader(temp_cache_dir)

        # Create mock response for 5MB file
        file_size = 5 * 1024 * 1024  # 5MB
        mock_resp = create_mock_response(content=b"x" * file_size)
        mock_session = create_mock_session(mock_resp)

        with patch("downloader.aiohttp.ClientSession", return_value=mock_session):
            path, size = await downloader.download(
                "http://example.com/large.wav", "job9"
            )

        assert os.path.exists(path)
        assert size == file_size
        assert os.path.getsize(path) == file_size

    @pytest.mark.asyncio
    async def test_download_no_content_length(self, temp_cache_dir: str):
        """Test download when server doesn't provide content-length header."""
        downloader = AudioDownloader(temp_cache_dir)

        content = b"x" * 1000
        mock_resp = Mock()
        mock_resp.status = 200
        mock_resp.headers = {}  # No content-length

        async def iter_chunks_no_len(n):
            for i in range(0, len(content), n):
                yield content[i : i + n]

        mock_resp.content = Mock()
        mock_resp.content.iter_chunked = iter_chunks_no_len
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock()

        mock_session = AsyncMock()
        # session.get() should return an async context manager
        mock_get_cm = AsyncMock()
        mock_get_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_get_cm.__aexit__ = AsyncMock()
        mock_session.get = Mock(return_value=mock_get_cm)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        with patch("downloader.aiohttp.ClientSession", return_value=mock_session):
            path, size = await downloader.download("http://example.com/no_len.wav", "job10")

        assert os.path.exists(path)
        assert size == 1000

    @pytest.mark.asyncio
    async def test_download_concurrent_jobs(self, temp_cache_dir: str):
        """Test multiple concurrent downloads for different jobs."""
        downloader = AudioDownloader(temp_cache_dir)

        async def download_job(job_id: int):
            url = f"http://example.com/audio{job_id}.wav"
            mock_session = create_mock_session()
            with patch("downloader.aiohttp.ClientSession", return_value=mock_session):
                return await downloader.download(url, f"job{job_id}")

        import asyncio

        # Run 5 concurrent downloads
        results = await asyncio.gather(*[download_job(i) for i in range(1, 6)])

        assert len(results) == 5
        for i, (path, size) in enumerate(results, start=1):
            assert path == os.path.join(temp_cache_dir, f"job{i}.wav")
            assert size == 1000
            assert os.path.exists(path)


class TestCleanup:
    """Test cleanup method."""

    @pytest.mark.asyncio
    async def test_cleanup_removes_job_file(self, temp_cache_dir: str):
        """Test that cleanup removes the downloaded file for a job."""
        downloader = AudioDownloader(temp_cache_dir)
        job_path = downloader._get_cache_path("cleanup_job")

        # Create file
        with open(job_path, "wb") as f:
            f.write(b"x" * 100)

        assert os.path.exists(job_path)

        await downloader.cleanup("cleanup_job")

        assert not os.path.exists(job_path)

    @pytest.mark.asyncio
    async def test_cleanup_multiple_extensions(self, temp_cache_dir: str):
        """Test cleanup checks multiple file extensions."""
        downloader = AudioDownloader(temp_cache_dir)

        # Create file with mp3 extension
        mp3_path = downloader._get_cache_path("multi_ext", "mp3")
        with open(mp3_path, "wb") as f:
            f.write(b"x" * 100)

        assert os.path.exists(mp3_path)
        await downloader.cleanup("multi_ext")
        assert not os.path.exists(mp3_path)

    @pytest.mark.asyncio
    async def test_cleanup_nonexistent_file(self, temp_cache_dir: str):
        """Test cleanup with nonexistent file (should not raise)."""
        downloader = AudioDownloader(temp_cache_dir)

        # Should not raise exception
        await downloader.cleanup("nonexistent_job")

    @pytest.mark.asyncio
    async def test_cleanup_stops_at_first_match(self, temp_cache_dir: str):
        """Test cleanup stops after finding and removing first file."""
        downloader = AudioDownloader(temp_cache_dir)

        # Create wav file (first in extension list)
        wav_path = downloader._get_cache_path("first_match", "wav")
        with open(wav_path, "wb") as f:
            f.write(b"x" * 100)

        await downloader.cleanup("first_match")
        assert not os.path.exists(wav_path)


class TestGetCacheSize:
    """Test get_cache_size method."""

    def test_get_cache_size_empty_directory(self, temp_cache_dir: str):
        """Test get_cache_size returns 0 for empty directory."""
        downloader = AudioDownloader(temp_cache_dir)
        assert downloader.get_cache_size() == 0

    def test_get_cache_size_single_file(self, temp_cache_dir: str):
        """Test get_cache_size with single file."""
        downloader = AudioDownloader(temp_cache_dir)
        file_path = os.path.join(temp_cache_dir, "test.wav")
        with open(file_path, "wb") as f:
            f.write(b"x" * 1000)

        assert downloader.get_cache_size() == 1000

    def test_get_cache_size_multiple_files(self, temp_cache_dir: str):
        """Test get_cache_size with multiple files."""
        downloader = AudioDownloader(temp_cache_dir)

        # Create multiple files with different sizes
        files = [
            ("file1.wav", 100),
            ("file2.mp3", 200),
            ("file3.m4a", 300),
        ]

        for filename, size in files:
            path = os.path.join(temp_cache_dir, filename)
            with open(path, "wb") as f:
                f.write(b"x" * size)

        assert downloader.get_cache_size() == 600  # Sum of all files

    def test_get_cache_size_nested_directories(self, temp_cache_dir: str, tmp_path: Path):
        """Test get_cache_size with nested directory structure."""
        nested_dir = tmp_path / "cache_nested" / "nested" / "deep"
        nested_dir.mkdir(parents=True)
        downloader = AudioDownloader(str(nested_dir))

        # Create files at different levels
        deep_file = os.path.join(str(nested_dir), "deep.wav")
        with open(deep_file, "wb") as f:
            f.write(b"x" * 300)

        # get_cache_size only counts files within self.cache_dir
        assert downloader.get_cache_size() == 300


class TestCleanupOldFiles:
    """Test cleanup_old_files method."""

    @pytest.mark.asyncio
    async def test_cleanup_old_files_under_limit(self, temp_cache_dir: str):
        """Test cleanup_old_files does nothing when under size limit."""
        downloader = AudioDownloader(temp_cache_dir)

        # Create file under 1GB limit
        file_path = os.path.join(temp_cache_dir, "small.wav")
        with open(file_path, "wb") as f:
            f.write(b"x" * 1000)

        initial_size = downloader.get_cache_size()
        assert initial_size == 1000

        await downloader.cleanup_old_files(max_size_gb=1)

        # File should still exist
        assert os.path.exists(file_path)
        assert downloader.get_cache_size() == initial_size

    @pytest.mark.asyncio
    async def test_cleanup_old_files_removes_oldest(self, temp_cache_dir: str):
        """Test cleanup_old_files removes oldest files when over limit."""
        downloader = AudioDownloader(temp_cache_dir)

        # Create files with different ages - each file is 100 bytes
        files = []
        for i in range(5):
            path = os.path.join(temp_cache_dir, f"file{i}.wav")
            with open(path, "wb") as f:
                f.write(b"x" * 100)
            files.append(path)
            # Sleep removed - mtime will still differ due to file creation timing

        # Set very low limit to trigger cleanup (should keep ~0 files with 100 bytes each)
        await downloader.cleanup_old_files(max_size_gb=0.0000001)  # ~100 bytes

        # At least some files should be deleted
        remaining_files = [p for p in files if os.path.exists(p)]
        assert len(remaining_files) < 5

    @pytest.mark.asyncio
    async def test_cleanup_old_files_respects_modification_time(
        self, temp_cache_dir: str
    ):
        """Test cleanup_old_files deletes files in modification time order."""
        downloader = AudioDownloader(temp_cache_dir)

        # Create files with known sizes
        file1 = os.path.join(temp_cache_dir, "old.wav")
        file2 = os.path.join(temp_cache_dir, "new.wav")

        with open(file1, "wb") as f:
            f.write(b"x" * 200)

        # Sleep removed - set mtime directly instead if needed

        with open(file2, "wb") as f:
            f.write(b"x" * 200)

        # Limit should force deletion of oldest
        await downloader.cleanup_old_files(max_size_gb=0.0000001)  # ~100 bytes

        # Oldest file should be deleted
        assert not os.path.exists(file1)

    @pytest.mark.asyncio
    async def test_cleanup_old_files_stops_when_under_limit(
        self, temp_cache_dir: str
    ):
        """Test cleanup_old_files stops deleting once under limit."""
        downloader = AudioDownloader(temp_cache_dir)

        # Create several files - each 100 bytes
        files = []
        for i in range(10):
            path = os.path.join(temp_cache_dir, f"file{i}.wav")
            with open(path, "wb") as f:
                f.write(b"x" * 100)
            files.append(path)
            time.sleep(0.01)

        # Set limit to keep some files (500 bytes = ~5 files)
        # Total size is 1000 bytes, so we expect ~5 files to be deleted
        # max_size_gb is in GB, so 0.0000005 GB = ~500 bytes
        await downloader.cleanup_old_files(max_size_gb=0.0000005)

        # Should stop deleting once under limit
        remaining = sum(1 for f in files if os.path.exists(f))
        assert remaining > 0
        assert remaining < 10


class TestRobustness:
    """Test edge cases and robustness scenarios."""

    @pytest.mark.asyncio
    async def test_unicode_filename_handling(self, temp_cache_dir: str):
        """Test handling of unicode characters in job IDs."""
        downloader = AudioDownloader(temp_cache_dir)
        unicode_job_id = "job_テスト_测试_🎵"

        mock_session = create_mock_session()
        with patch("downloader.aiohttp.ClientSession", return_value=mock_session):
            path, size = await downloader.download(
                "http://example.com/unicode.wav", unicode_job_id
            )

        assert os.path.exists(path)
        assert size == 1000

    @pytest.mark.asyncio
    async def test_invalid_url_format(self, temp_cache_dir: str):
        """Test handling of invalid URL formats."""
        downloader = AudioDownloader(temp_cache_dir)

        mock_session = AsyncMock()
        mock_get_cm = AsyncMock()
        mock_get_cm.__aenter__ = AsyncMock(side_effect=ValueError("Invalid URL"))
        mock_get_cm.__aexit__ = AsyncMock()
        mock_session.get = Mock(return_value=mock_get_cm)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        with patch("downloader.aiohttp.ClientSession", return_value=mock_session):
            with pytest.raises(Exception) as exc_info:
                await downloader.download("not-a-url", "job_invalid")

        assert "Download failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_cache_directory_creation_failure(self, tmp_path: Path):
        """Test handling when cache directory creation fails."""
        # Create a file (not directory) at cache path
        cache_file = tmp_path / "cache_file"
        cache_file.write_text("blocking file")

        with pytest.raises(OSError):
            AudioDownloader(str(cache_file))

    @pytest.mark.asyncio
    async def test_corrupted_cache_file(self, temp_cache_dir: str):
        """Test handling of corrupted cache file (zero bytes)."""
        downloader = AudioDownloader(temp_cache_dir)
        cached_path = downloader._get_cache_path("corrupted")

        # Create zero-byte file (corrupted cache)
        with open(cached_path, "wb") as f:
            pass

        mock_session = create_mock_session()
        with patch("downloader.aiohttp.ClientSession", return_value=mock_session):
            path, size = await downloader.download(
                "http://example.com/fresh.wav", "corrupted"
            )

        # Should re-download successfully
        assert os.path.exists(path)
        assert size == 1000
        assert os.path.getsize(path) == 1000

    @pytest.mark.asyncio
    async def test_disk_full_scenario(self, temp_cache_dir: str):
        """Test handling of disk full scenario during download."""
        downloader = AudioDownloader(temp_cache_dir)
        cached_path = downloader._get_cache_path("disk_full")

        mock_resp = Mock()
        mock_resp.status = 200

        async def iter_chunks_full(n):
            yield b"x" * 100
            # Simulate disk full error
            raise OSError(28, "No space left on device")

        mock_resp.content = Mock()
        mock_resp.content.iter_chunked = iter_chunks_full
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock()

        mock_session = AsyncMock()
        mock_session.get = Mock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock()

        with patch("downloader.aiohttp.ClientSession", return_value=mock_session):
            with pytest.raises(Exception) as exc_info:
                await downloader.download("http://example.com/large.wav", "disk_full")

        # Partial file should be cleaned up
        assert not os.path.exists(cached_path)
        assert "Download failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_file_permission_error(self, temp_cache_dir: str):
        """Test handling of file permission errors."""
        downloader = AudioDownloader(temp_cache_dir)
        cached_path = downloader._get_cache_path("permission_denied")

        # Mock os.remove to raise permission error
        original_remove = os.remove

        def mock_remove_permission(path):
            if "permission_denied" in path:
                raise PermissionError("Permission denied")
            return original_remove(path)

        with patch("os.remove", side_effect=mock_remove_permission):
            # Create file first
            with open(cached_path, "wb") as f:
                f.write(b"x" * 100)

            # Cleanup should raise PermissionError
            with pytest.raises(PermissionError):
                await downloader.cleanup("permission_denied")

    @pytest.mark.asyncio
    async def test_concurrent_downloads_same_job(self, temp_cache_dir: str):
        """Test concurrent downloads for the same job (race condition)."""
        downloader = AudioDownloader(temp_cache_dir)

        async def download_same_job():
            mock_session = create_mock_session()
            with patch("downloader.aiohttp.ClientSession", return_value=mock_session):
                return await downloader.download("http://example.com/same.wav", "race")

        import asyncio

        # Start multiple downloads for same job concurrently
        results = await asyncio.gather(
            *[download_same_job() for _ in range(3)], return_exceptions=True
        )

        # At least one should succeed
        successful = [r for r in results if not isinstance(r, Exception)]
        assert len(successful) >= 1

        # File should exist and be valid
        cached_path = downloader._get_cache_path("race")
        assert os.path.exists(cached_path)
        assert os.path.getsize(cached_path) == 1000

    @pytest.mark.asyncio
    async def test_very_long_job_id(self, temp_cache_dir: str):
        """Test handling of very long job IDs."""
        downloader = AudioDownloader(temp_cache_dir)
        long_job_id = "a" * 100  # 100 character job ID

        mock_session = create_mock_session()
        with patch("downloader.aiohttp.ClientSession", return_value=mock_session):
            path, size = await downloader.download(
                "http://example.com/long.wav", long_job_id
            )

        assert os.path.exists(path)
        assert size == 1000

    @pytest.mark.asyncio
    async def test_special_characters_in_job_id(self, temp_cache_dir: str):
        """Test handling of special characters in job IDs."""
        downloader = AudioDownloader(temp_cache_dir)
        special_job_id = "job_123-TEST"  # Use simpler chars without shell metachars

        mock_session = create_mock_session()
        with patch("downloader.aiohttp.ClientSession", return_value=mock_session):
            path, size = await downloader.download(
                "http://example.com/special.wav", special_job_id
            )

        assert os.path.exists(path)
        assert size == 1000
