"""Tests for internal API endpoints (temp-file access)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient

from main import create_app


async def _iter_bytes(payload: bytes):
    yield payload


@pytest.fixture(scope="function")
def client():
    """Create a test client with rate limiting disabled."""
    app = create_app(rate_limit_enabled_override=False)
    client = TestClient(app)
    yield client


@pytest.fixture
def mock_storage():
    """Create a mock storage service."""
    mock = Mock()
    mock.exists = AsyncMock()
    mock.iter_file = Mock()
    mock.get_full_path = AsyncMock(return_value="/test/storage")
    return mock


@pytest.fixture
def mock_storage_bridge():
    """Create a mock storage bridge."""
    bridge = Mock()
    bridge.validate_signature = Mock()
    bridge.generate_signature = Mock(return_value="test_sig_123")
    bridge.revoke_signature = Mock()
    return bridge


@pytest.fixture
def temp_worker_dir():
    """Create a temporary worker directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


class TestGetTempFileEndpoint:
    """Test /api/internal/temp-file endpoint."""

    def test_temp_file_invalid_signature(self, client, mock_storage_bridge):
        """Test accessing temp file with invalid signature."""
        mock_storage_bridge.validate_signature.return_value = False

        with patch("services_registry.storage_bridge", mock_storage_bridge):
            response = client.get(
                "/api/internal/temp-file",
                params={"path": "test.mp3", "sig": "invalid_signature"},
            )
        assert response.status_code == 403
        assert "Invalid or expired signature" in response.json()["detail"]

    def test_temp_file_storage_file_success(self, client, mock_storage, mock_storage_bridge):
        """Test accessing a storage file successfully."""
        # Mock the storage bridge validation
        mock_storage_bridge.validate_signature.return_value = True

        mock_storage.exists.return_value = True
        mock_storage.iter_file.return_value = _iter_bytes(b"test audio data")

        with patch("services_registry.storage", mock_storage):
            with patch("services_registry.storage_bridge", mock_storage_bridge):
                response = client.get(
                    "/api/internal/temp-file",
                    params={"path": "storage/test_file.mp3", "sig": "valid_sig"},
                )

        assert response.status_code == 200
        assert response.content == b"test audio data"
        assert response.headers["content-type"] == "audio/mpeg"
        mock_storage.iter_file.assert_called_once_with("test_file.mp3")

    def test_temp_file_storage_file_not_found(self, client, mock_storage, mock_storage_bridge):
        """Test accessing a storage file that doesn't exist."""
        mock_storage_bridge.validate_signature.return_value = True
        mock_storage.exists.return_value = False

        with patch("services_registry.storage", mock_storage):
            with patch("services_registry.storage_bridge", mock_storage_bridge):
                response = client.get(
                    "/api/internal/temp-file",
                    params={"path": "storage/missing.mp3", "sig": "valid_sig"},
                )

        assert response.status_code == 404
        assert "File not found in storage" in response.json()["detail"]

    def test_temp_file_storage_file_error(self, client, mock_storage, mock_storage_bridge):
        """Test accessing a storage file with error."""
        mock_storage_bridge.validate_signature.return_value = True
        mock_storage.exists.side_effect = Exception("Storage error")

        with patch("services_registry.storage", mock_storage):
            with patch("services_registry.storage_bridge", mock_storage_bridge):
                response = client.get(
                    "/api/internal/temp-file",
                    params={"path": "storage/error.mp3", "sig": "valid_sig"},
                )

        assert response.status_code == 500
        assert "Error reading file metadata" in response.json()["detail"]

    def test_temp_file_worker_temp_success(self, client, mock_storage_bridge, temp_worker_dir):
        """Test accessing a worker temp file successfully."""
        # Create a test file in temp directory
        test_file = Path(temp_worker_dir) / "test_audio.mp3"
        test_file.write_bytes(b"test audio data")

        mock_storage_bridge.validate_signature.return_value = True

        with patch("services_registry.storage_bridge", mock_storage_bridge):
            with patch("routers.internal._get_worker_temp_dir", return_value=temp_worker_dir):
                response = client.get(
                    "/api/internal/temp-file",
                    params={"path": str(test_file), "sig": "valid_sig"},
                )

        assert response.status_code == 200
        assert response.content == b"test audio data"
        assert response.headers["content-type"] == "audio/mpeg"

    def test_temp_file_worker_temp_wav(self, client, mock_storage_bridge, temp_worker_dir):
        """Test accessing a worker temp WAV file."""
        test_file = Path(temp_worker_dir) / "test_audio.wav"
        test_file.write_bytes(b"test wav data")

        mock_storage_bridge.validate_signature.return_value = True

        with patch("services_registry.storage_bridge", mock_storage_bridge):
            with patch("routers.internal._get_worker_temp_dir", return_value=temp_worker_dir):
                response = client.get(
                    "/api/internal/temp-file",
                    params={"path": str(test_file), "sig": "valid_sig"},
                )

        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/wav"

    def test_temp_file_worker_temp_m4a(self, client, mock_storage_bridge, temp_worker_dir):
        """Test accessing a worker temp M4A file."""
        test_file = Path(temp_worker_dir) / "test_audio.m4a"
        test_file.write_bytes(b"test m4a data")

        mock_storage_bridge.validate_signature.return_value = True

        with patch("services_registry.storage_bridge", mock_storage_bridge):
            with patch("routers.internal._get_worker_temp_dir", return_value=temp_worker_dir):
                response = client.get(
                    "/api/internal/temp-file",
                    params={"path": str(test_file), "sig": "valid_sig"},
                )

        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/mp4"

    def test_temp_file_worker_temp_mp4(self, client, mock_storage_bridge, temp_worker_dir):
        """Test accessing a worker temp MP4 file."""
        test_file = Path(temp_worker_dir) / "test_video.mp4"
        test_file.write_bytes(b"test mp4 data")

        mock_storage_bridge.validate_signature.return_value = True

        with patch("services_registry.storage_bridge", mock_storage_bridge):
            with patch("routers.internal._get_worker_temp_dir", return_value=temp_worker_dir):
                response = client.get(
                    "/api/internal/temp-file",
                    params={"path": str(test_file), "sig": "valid_sig"},
                )

        assert response.status_code == 200
        assert response.headers["content-type"] == "video/mp4"

    def test_temp_file_worker_temp_unknown_extension(
        self, client, mock_storage_bridge, temp_worker_dir
    ):
        """Test accessing a worker temp file with unknown extension."""
        test_file = Path(temp_worker_dir) / "test_audio.xyz"
        test_file.write_bytes(b"test data")

        mock_storage_bridge.validate_signature.return_value = True

        with patch("services_registry.storage_bridge", mock_storage_bridge):
            with patch("routers.internal._get_worker_temp_dir", return_value=temp_worker_dir):
                response = client.get(
                    "/api/internal/temp-file",
                    params={"path": str(test_file), "sig": "valid_sig"},
                )

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/octet-stream"

    def test_temp_file_worker_temp_not_found(self, client, mock_storage_bridge, temp_worker_dir):
        """Test accessing a worker temp file that doesn't exist."""
        mock_storage_bridge.validate_signature.return_value = True

        with patch("services_registry.storage_bridge", mock_storage_bridge):
            with patch("routers.internal._get_worker_temp_dir", return_value=temp_worker_dir):
                response = client.get(
                    "/api/internal/temp-file",
                    params={"path": str(Path(temp_worker_dir) / "missing.mp3"), "sig": "valid_sig"},
                )

        assert response.status_code == 404
        assert "File not found" in response.json()["detail"]

    def test_temp_file_worker_temp_outside_temp_dir(
        self, client, mock_storage_bridge, temp_worker_dir
    ):
        """Test accessing a file outside the temp directory (security check)."""
        mock_storage_bridge.validate_signature.return_value = True

        # Try to access a file outside the temp directory
        outside_file = "/etc/passwd"

        with patch("services_registry.storage_bridge", mock_storage_bridge):
            with patch("routers.internal._get_worker_temp_dir", return_value=temp_worker_dir):
                response = client.get(
                    "/api/internal/temp-file",
                    params={"path": outside_file, "sig": "valid_sig"},
                )

        assert response.status_code == 403
        assert "Access denied" in response.json()["detail"]

    def test_temp_file_worker_temp_permission_error(
        self, client, mock_storage_bridge, temp_worker_dir
    ):
        """Test accessing a worker temp file with permission error."""
        test_file = Path(temp_worker_dir) / "test_audio.mp3"
        test_file.write_bytes(b"test audio data")

        mock_storage_bridge.validate_signature.return_value = True

        # Mock aiofiles.open to raise permission error
        with patch(
            "routers.internal.aiofiles.open",
            side_effect=PermissionError("Permission denied"),
        ):
            with patch("services_registry.storage_bridge", mock_storage_bridge):
                with patch("routers.internal._get_worker_temp_dir", return_value=temp_worker_dir):
                    response = client.get(
                        "/api/internal/temp-file",
                        params={"path": str(test_file), "sig": "valid_sig"},
                    )

        assert response.status_code == 500
        assert "Error reading file" in response.json()["detail"]

    def test_temp_file_worker_temp_directory_not_initialized(self, client, mock_storage_bridge):
        """Test accessing temp file when worker temp directory is not initialized."""
        mock_storage_bridge.validate_signature.return_value = True

        with patch("services_registry.storage_bridge", mock_storage_bridge):
            with patch(
                "routers.internal._get_worker_temp_dir",
                side_effect=RuntimeError("Services not initialized"),
            ):
                response = client.get(
                    "/api/internal/temp-file",
                    params={"path": str(Path("test.mp3").resolve()), "sig": "valid_sig"},
                )

        assert response.status_code == 500
        assert "Error reading file" in response.json()["detail"]


class TestGetWorkerTempDir:
    """Test _get_worker_temp_dir helper function."""

    def test_get_worker_temp_dir_success(self):
        """Test getting worker temp directory when initialized."""
        with patch("services_registry.worker_temp_dir", "/test/temp/dir"):
            from routers.internal import _get_worker_temp_dir

            result = _get_worker_temp_dir()
            assert result == "/test/temp/dir"

    def test_get_worker_temp_dir_not_initialized(self):
        """Test getting worker temp directory when not initialized."""
        with patch("services_registry.worker_temp_dir", ""):
            from routers.internal import _get_worker_temp_dir

            with pytest.raises(RuntimeError, match="Services not initialized"):
                _get_worker_temp_dir()


class TestContentTypeDetection:
    """Test content type detection for different file extensions."""

    def test_content_type_mp3(self, client, mock_storage_bridge, temp_worker_dir):
        """Test MP3 content type."""
        test_file = Path(temp_worker_dir) / "audio.mp3"
        test_file.write_bytes(b"test")

        mock_storage_bridge.validate_signature.return_value = True

        with patch("services_registry.storage_bridge", mock_storage_bridge):
            with patch("routers.internal._get_worker_temp_dir", return_value=temp_worker_dir):
                response = client.get(
                    "/api/internal/temp-file",
                    params={"path": str(test_file), "sig": "valid_sig"},
                )

        assert response.headers["content-type"] == "audio/mpeg"

    def test_content_type_wav(self, client, mock_storage_bridge, temp_worker_dir):
        """Test WAV content type."""
        test_file = Path(temp_worker_dir) / "audio.wav"
        test_file.write_bytes(b"test")

        mock_storage_bridge.validate_signature.return_value = True

        with patch("services_registry.storage_bridge", mock_storage_bridge):
            with patch("routers.internal._get_worker_temp_dir", return_value=temp_worker_dir):
                response = client.get(
                    "/api/internal/temp-file",
                    params={"path": str(test_file), "sig": "valid_sig"},
                )

        assert response.headers["content-type"] == "audio/wav"

    def test_content_type_m4a(self, client, mock_storage_bridge, temp_worker_dir):
        """Test M4A content type."""
        test_file = Path(temp_worker_dir) / "audio.m4a"
        test_file.write_bytes(b"test")

        mock_storage_bridge.validate_signature.return_value = True

        with patch("services_registry.storage_bridge", mock_storage_bridge):
            with patch("routers.internal._get_worker_temp_dir", return_value=temp_worker_dir):
                response = client.get(
                    "/api/internal/temp-file",
                    params={"path": str(test_file), "sig": "valid_sig"},
                )

        assert response.headers["content-type"] == "audio/mp4"

    def test_content_type_mp4(self, client, mock_storage_bridge, temp_worker_dir):
        """Test MP4 content type."""
        test_file = Path(temp_worker_dir) / "video.mp4"
        test_file.write_bytes(b"test")

        mock_storage_bridge.validate_signature.return_value = True

        with patch("services_registry.storage_bridge", mock_storage_bridge):
            with patch("routers.internal._get_worker_temp_dir", return_value=temp_worker_dir):
                response = client.get(
                    "/api/internal/temp-file",
                    params={"path": str(test_file), "sig": "valid_sig"},
                )

        assert response.headers["content-type"] == "video/mp4"

    def test_content_type_unknown(self, client, mock_storage_bridge, temp_worker_dir):
        """Test unknown file extension content type."""
        test_file = Path(temp_worker_dir) / "audio.xyz"
        test_file.write_bytes(b"test")

        mock_storage_bridge.validate_signature.return_value = True

        with patch("services_registry.storage_bridge", mock_storage_bridge):
            with patch("routers.internal._get_worker_temp_dir", return_value=temp_worker_dir):
                response = client.get(
                    "/api/internal/temp-file",
                    params={"path": str(test_file), "sig": "valid_sig"},
                )

        assert response.headers["content-type"] == "application/octet-stream"


class TestStoragePathDetection:
    """Test detection of storage paths vs temp paths."""

    def test_storage_path_with_slash(self, client, mock_storage, mock_storage_bridge):
        """Test storage path detection with slash in path."""
        mock_storage_bridge.validate_signature.return_value = True
        mock_storage.exists.return_value = True
        mock_storage.iter_file.return_value = _iter_bytes(b"test data")

        with patch("services_registry.storage", mock_storage):
            with patch("services_registry.storage_bridge", mock_storage_bridge):
                response = client.get(
                    "/api/internal/temp-file",
                    params={"path": "storage/test.mp3", "sig": "valid_sig"},
                )

        assert response.status_code == 200
        mock_storage.iter_file.assert_called_once_with("test.mp3")

    def test_storage_path_without_slash(self, client, mock_storage, mock_storage_bridge):
        """Test storage path detection without slash (single segment)."""
        mock_storage_bridge.validate_signature.return_value = True
        mock_storage.exists.return_value = True
        mock_storage.iter_file.return_value = _iter_bytes(b"test data")

        with patch("services_registry.storage", mock_storage):
            with patch("services_registry.storage_bridge", mock_storage_bridge):
                response = client.get(
                    "/api/internal/temp-file",
                    params={"path": "test.mp3", "sig": "valid_sig"},
                )

        assert response.status_code == 200
        mock_storage.iter_file.assert_called_once_with("test.mp3")

    def test_temp_path_with_slash(self, client, mock_storage_bridge, temp_worker_dir):
        """Test temp path detection with slash (absolute path)."""
        test_file = Path(temp_worker_dir) / "test.mp3"
        test_file.write_bytes(b"test data")

        mock_storage_bridge.validate_signature.return_value = True

        with patch("services_registry.storage_bridge", mock_storage_bridge):
            with patch("routers.internal._get_worker_temp_dir", return_value=temp_worker_dir):
                response = client.get(
                    "/api/internal/temp-file",
                    params={"path": str(test_file), "sig": "valid_sig"},
                )

        assert response.status_code == 200
        assert response.content == b"test data"
