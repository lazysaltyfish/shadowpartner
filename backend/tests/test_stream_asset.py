from __future__ import annotations

import asyncio
import io
import tempfile
import uuid
from collections.abc import Generator
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from db import get_session
from db.crud import get_or_create_guest_user
from db.models import Asset, AssetType
from main import create_app


@pytest.fixture(scope="function")
def client() -> Generator[TestClient, None, None]:
    app = create_app()
    test_client = TestClient(app)

    def override_get_session():
        from db.engine import SessionLocal

        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_session] = override_get_session

    yield test_client

    app.dependency_overrides.clear()


@pytest.fixture
def storage_dir() -> Generator[tempfile.TemporaryDirectory[str], None, None]:
    """Create a temporary storage directory and set up storage service."""
    tmpdir = tempfile.TemporaryDirectory()

    with patch("services_registry.get_settings") as mock_settings:
        settings_mock = Mock()
        settings_mock.storage_root_dir = tmpdir.name
        settings_mock.whisper_device = None
        settings_mock.whisper_fp16 = False
        settings_mock.whisper_model_size = "base"
        mock_settings.return_value = settings_mock

        # Reinitialize storage service with temp directory
        import services_registry

        services_registry.storage = services_registry.LocalStorage(root_dir=tmpdir.name)

    yield tmpdir

    # Cleanup
    import services_registry

    services_registry.storage = services_registry.LocalStorage()


@pytest.fixture
def test_asset_with_file(
    client: TestClient, storage_dir: tempfile.TemporaryDirectory
) -> tuple[uuid.UUID, str]:
    """Create an asset with an actual file in storage."""
    with get_session() as db:
        user = get_or_create_guest_user(db, "127.0.0.1")
        user_id = user.id

    # Create a test file content
    test_content = b"Test video file content " * 100  # ~2KB file
    file_obj = io.BytesIO(test_content)

    # Save to storage using the storage service
    import services_registry

    storage = services_registry.storage
    storage_path = await_storage_save(storage, file_obj, "upload_testfile1234")

    # Create asset record
    with get_session() as db:
        asset = Asset(
            type=AssetType.UPLOAD,
            identifier="testfile1234",
            storage_path=storage_path,
            meta={"original_ext": ".mp4", "duration": 120.0},
            created_by=user_id,
        )
        db.add(asset)
        db.commit()
        db.refresh(asset)
        asset_id = asset.id

    return asset_id, storage_path


def await_storage_save(storage, file_obj, path: str) -> str:
    """Helper to run async storage.save in sync context."""

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(storage.save(file_obj, path))
    finally:
        loop.close()


@pytest.fixture
def test_asset_with_thumbnail(
    client: TestClient, storage_dir: tempfile.TemporaryDirectory
) -> tuple[uuid.UUID, str, bytes]:
    """Create an upload asset with a thumbnail stored in storage."""
    with get_session() as db:
        user = get_or_create_guest_user(db, "127.0.0.1")
        user_id = user.id

    thumb_content = b"Test thumbnail content " * 20
    thumb_obj = io.BytesIO(thumb_content)

    import services_registry

    storage = services_registry.storage
    thumbnail_path = await_storage_save(storage, thumb_obj, "upload_thumb_test_123_thumb.jpg")

    with get_session() as db:
        asset = Asset(
            type=AssetType.UPLOAD,
            identifier="thumb_test_123",
            storage_path="upload_video_stub_123",
            meta={"thumbnail_path": thumbnail_path, "original_ext": ".mp4"},
            created_by=user_id,
        )
        db.add(asset)
        db.commit()
        db.refresh(asset)
        asset_id = asset.id

    return asset_id, thumbnail_path, thumb_content


# ==================== Full File Streaming Tests ====================


def test_stream_full_file(client: TestClient, test_asset_with_file: tuple[uuid.UUID, str]):
    """Test streaming full file without Range header."""
    asset_id, _ = test_asset_with_file

    response = client.get(f"/api/assets/{asset_id}/stream")

    assert response.status_code == 200
    assert response.headers["accept-ranges"] == "bytes"
    assert "content-length" in response.headers
    assert "content-type" in response.headers
    # Should be video/mp4 based on original_ext
    assert "video" in response.headers["content-type"].lower()

    # Verify content is returned
    content = response.content
    assert len(content) > 0
    assert content == b"Test video file content " * 100


# ==================== Thumbnail Tests ====================


def test_get_thumbnail_success(
    client: TestClient, test_asset_with_thumbnail: tuple[uuid.UUID, str, bytes]
):
    asset_id, _, thumb_content = test_asset_with_thumbnail

    response = client.get(f"/api/assets/{asset_id}/thumbnail")

    assert response.status_code == 200
    assert "image" in response.headers["content-type"].lower()
    assert response.headers.get("content-length") == str(len(thumb_content))
    assert response.content == thumb_content


def test_get_thumbnail_missing_meta(client: TestClient, storage_dir: tempfile.TemporaryDirectory):
    with get_session() as db:
        user = get_or_create_guest_user(db, "127.0.0.1")
        asset = Asset(
            type=AssetType.UPLOAD,
            identifier="thumb_missing_meta",
            storage_path="upload_video_missing_meta",
            meta=None,
            created_by=user.id,
        )
        db.add(asset)
        db.commit()
        asset_id = asset.id

    response = client.get(f"/api/assets/{asset_id}/thumbnail")
    assert response.status_code == 404


def test_get_thumbnail_missing_file(client: TestClient, storage_dir: tempfile.TemporaryDirectory):
    with get_session() as db:
        user = get_or_create_guest_user(db, "127.0.0.1")
        asset = Asset(
            type=AssetType.UPLOAD,
            identifier="thumb_missing_file",
            storage_path="upload_video_missing_file",
            meta={"thumbnail_path": "upload_missing_thumb.jpg"},
            created_by=user.id,
        )
        db.add(asset)
        db.commit()
        asset_id = asset.id

    response = client.get(f"/api/assets/{asset_id}/thumbnail")
    assert response.status_code == 404


def test_get_thumbnail_non_upload(client: TestClient):
    with get_session() as db:
        user = get_or_create_guest_user(db, "127.0.0.1")
        asset = Asset(
            type=AssetType.YOUTUBE,
            identifier="yt_thumb_test",
            storage_path=None,
            meta={"thumbnail_path": "upload_irrelevant_thumb.jpg"},
            created_by=user.id,
        )
        db.add(asset)
        db.commit()
        asset_id = asset.id

    response = client.get(f"/api/assets/{asset_id}/thumbnail")
    assert response.status_code == 404


def test_stream_full_file_mp3(client: TestClient, storage_dir: tempfile.TemporaryDirectory):
    """Test streaming MP3 file gets correct MIME type."""
    test_content = b"Test audio content " * 50
    file_obj = io.BytesIO(test_content)

    import services_registry

    storage = services_registry.storage
    storage_path = await_storage_save(storage, file_obj, "upload_mp3file123")

    with get_session() as db:
        user = get_or_create_guest_user(db, "127.0.0.1")
        asset = Asset(
            type=AssetType.UPLOAD,
            identifier="mp3file123",
            storage_path=storage_path,
            meta={"original_ext": ".mp3", "duration": 60.0},
            created_by=user.id,
        )
        db.add(asset)
        db.commit()
        asset_id = asset.id

    response = client.get(f"/api/assets/{asset_id}/stream")

    assert response.status_code == 200
    assert "audio" in response.headers["content-type"].lower()
    assert response.content == test_content


def test_stream_full_file_m4a(client: TestClient, storage_dir: tempfile.TemporaryDirectory):
    """Test streaming M4A file gets correct MIME type (audio/mp4)."""
    test_content = b"Test M4A content " * 50
    file_obj = io.BytesIO(test_content)

    import services_registry

    storage = services_registry.storage
    storage_path = await_storage_save(storage, file_obj, "upload_m4afile456")

    with get_session() as db:
        user = get_or_create_guest_user(db, "127.0.0.1")
        asset = Asset(
            type=AssetType.UPLOAD,
            identifier="m4afile456",
            storage_path=storage_path,
            meta={"original_ext": ".m4a", "duration": 90.0},
            created_by=user.id,
        )
        db.add(asset)
        db.commit()
        asset_id = asset.id

    response = client.get(f"/api/assets/{asset_id}/stream")

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mp4"
    assert response.content == test_content


def test_stream_default_mime_type(client: TestClient, storage_dir: tempfile.TemporaryDirectory):
    """Test streaming file without original_ext defaults to octet-stream."""
    test_content = b"Unknown file content " * 30
    file_obj = io.BytesIO(test_content)

    import services_registry

    storage = services_registry.storage
    storage_path = await_storage_save(storage, file_obj, "upload_unknown789")

    with get_session() as db:
        user = get_or_create_guest_user(db, "127.0.0.1")
        asset = Asset(
            type=AssetType.UPLOAD,
            identifier="unknown789",
            storage_path=storage_path,
            meta=None,  # No original_ext
            created_by=user.id,
        )
        db.add(asset)
        db.commit()
        asset_id = asset.id

    response = client.get(f"/api/assets/{asset_id}/stream")

    assert response.status_code == 200
    # Defaults to application/octet-stream or mimetypes guess
    assert "content-type" in response.headers


# ==================== Range Request Tests ====================


def test_stream_range_request_start_only(
    client: TestClient, test_asset_with_file: tuple[uuid.UUID, str]
):
    """Test Range request with start byte only."""
    asset_id, _ = test_asset_with_file

    response = client.get(f"/api/assets/{asset_id}/stream", headers={"Range": "bytes=100-"})

    assert response.status_code == 206  # Partial Content
    assert response.headers["accept-ranges"] == "bytes"
    assert "content-range" in response.headers
    assert "content-length" in response.headers

    # Verify Content-Range format: bytes start-end/total
    content_range = response.headers["content-range"]
    assert content_range.startswith("bytes 100-")
    assert "/2400" in content_range  # Total size is 2400 bytes (24 * 100)

    # Content should be from byte 100 onwards
    expected_content = (b"Test video file content " * 100)[100:]
    assert response.content == expected_content


def test_stream_range_request_start_and_end(
    client: TestClient, test_asset_with_file: tuple[uuid.UUID, str]
):
    """Test Range request with start and end bytes."""
    asset_id, _ = test_asset_with_file

    response = client.get(f"/api/assets/{asset_id}/stream", headers={"Range": "bytes=100-199"})

    assert response.status_code == 206
    assert response.headers["content-range"].startswith("bytes 100-199/")

    # Content length should be 100 bytes
    assert int(response.headers["content-length"]) == 100

    # Content should be bytes 100-199 (100 bytes total)
    expected_content = (b"Test video file content " * 100)[100:200]
    assert response.content == expected_content
    assert len(response.content) == 100


def test_stream_range_request_first_byte(
    client: TestClient, test_asset_with_file: tuple[uuid.UUID, str]
):
    """Test Range request for first byte only."""
    asset_id, _ = test_asset_with_file

    response = client.get(f"/api/assets/{asset_id}/stream", headers={"Range": "bytes=0-0"})

    assert response.status_code == 206
    assert response.headers["content-range"].startswith("bytes 0-0/")
    assert int(response.headers["content-length"]) == 1
    assert response.content == b"T"


def test_stream_range_request_last_byte(
    client: TestClient, test_asset_with_file: tuple[uuid.UUID, str]
):
    """Test Range request for last byte only."""
    asset_id, _ = test_asset_with_file

    response = client.get(f"/api/assets/{asset_id}/stream", headers={"Range": "bytes=2399-2399"})

    assert response.status_code == 206
    assert response.headers["content-range"] == "bytes 2399-2399/2400"
    assert int(response.headers["content-length"]) == 1


def test_stream_range_entire_file(client: TestClient, test_asset_with_file: tuple[uuid.UUID, str]):
    """Test Range request for entire file (0 to end)."""
    asset_id, _ = test_asset_with_file

    response = client.get(f"/api/assets/{asset_id}/stream", headers={"Range": "bytes=0-"})

    assert response.status_code == 206
    assert response.headers["content-range"] == "bytes 0-2399/2400"
    assert response.content == b"Test video file content " * 100


# ==================== Error Handling Tests ====================


def test_stream_invalid_asset_id(client: TestClient):
    """Test streaming with invalid asset ID format."""
    response = client.get("/api/assets/not-a-uuid/stream")

    assert response.status_code == 400
    assert "Invalid asset ID format" in response.json()["detail"]


def test_stream_asset_not_found(client: TestClient):
    """Test streaming non-existent asset."""
    fake_id = uuid.uuid4()
    response = client.get(f"/api/assets/{fake_id}/stream")

    assert response.status_code == 404
    assert "Asset not found" in response.json()["detail"]


def test_stream_youtube_asset(client: TestClient, storage_dir: tempfile.TemporaryDirectory):
    """Test that YouTube assets return 400 (only upload type allowed)."""
    with get_session() as db:
        user = get_or_create_guest_user(db, "127.0.0.1")
        asset = Asset(
            type=AssetType.YOUTUBE,
            identifier="dQw4w9WgXcQ",
            storage_path=None,
            meta={"title": "Test YouTube Video"},
            created_by=user.id,
        )
        db.add(asset)
        db.commit()
        asset_id = asset.id

    response = client.get(f"/api/assets/{asset_id}/stream")

    assert response.status_code == 400
    assert "Streaming only available for uploaded files" in response.json()["detail"]


def test_stream_asset_no_storage_path(client: TestClient, storage_dir: tempfile.TemporaryDirectory):
    """Test asset without storage path returns 404."""
    with get_session() as db:
        user = get_or_create_guest_user(db, "127.0.0.1")
        asset = Asset(
            type=AssetType.UPLOAD,
            identifier="nofile123",
            storage_path=None,  # No storage path
            meta=None,
            created_by=user.id,
        )
        db.add(asset)
        db.commit()
        asset_id = asset.id

    response = client.get(f"/api/assets/{asset_id}/stream")

    assert response.status_code == 404
    assert "File not found" in response.json()["detail"]


def test_stream_file_not_in_storage(client: TestClient, storage_dir: tempfile.TemporaryDirectory):
    """Test when storage_path exists but file not in storage."""
    with get_session() as db:
        user = get_or_create_guest_user(db, "127.0.0.1")
        asset = Asset(
            type=AssetType.UPLOAD,
            identifier="missing123",
            storage_path="upload_missingfile123",  # File doesn't exist
            meta={"original_ext": ".mp4"},
            created_by=user.id,
        )
        db.add(asset)
        db.commit()
        asset_id = asset.id

    response = client.get(f"/api/assets/{asset_id}/stream")

    assert response.status_code == 404
    assert "File not found in storage" in response.json()["detail"]


def test_stream_range_not_satisfiable(
    client: TestClient, test_asset_with_file: tuple[uuid.UUID, str]
):
    """Test Range request with start >= file size returns 416."""
    asset_id, _ = test_asset_with_file

    response = client.get(f"/api/assets/{asset_id}/stream", headers={"Range": "bytes=99999-"})

    assert response.status_code == 416
    assert "Range not satisfiable" in response.json()["detail"]


def test_stream_invalid_range_format(
    client: TestClient, test_asset_with_file: tuple[uuid.UUID, str]
):
    """Test invalid Range format is ignored (returns full file)."""
    asset_id, _ = test_asset_with_file

    # Invalid range format - should return full file
    response = client.get(f"/api/assets/{asset_id}/stream", headers={"Range": "invalid"})

    # Should return full file (200, not 206)
    assert response.status_code == 200
    assert response.content == b"Test video file content " * 100


# ==================== Edge Cases ====================


def test_stream_empty_file(client: TestClient, storage_dir: tempfile.TemporaryDirectory):
    """Test streaming an empty file."""
    test_content = b""
    file_obj = io.BytesIO(test_content)

    import services_registry

    storage = services_registry.storage
    storage_path = await_storage_save(storage, file_obj, "upload_empty999")

    with get_session() as db:
        user = get_or_create_guest_user(db, "127.0.0.1")
        asset = Asset(
            type=AssetType.UPLOAD,
            identifier="empty999",
            storage_path=storage_path,
            meta={"original_ext": ".mp4"},
            created_by=user.id,
        )
        db.add(asset)
        db.commit()
        asset_id = asset.id

    response = client.get(f"/api/assets/{asset_id}/stream")

    assert response.status_code == 200
    assert response.content == b""
    assert response.headers["content-length"] == "0"


def test_stream_large_file_chunked(client: TestClient, storage_dir: tempfile.TemporaryDirectory):
    """Test streaming a larger file to verify chunked iteration."""
    # Create 25KB file (larger than default 8KB chunk size)
    test_content = b"x" * 25000
    file_obj = io.BytesIO(test_content)

    import services_registry

    storage = services_registry.storage
    storage_path = await_storage_save(storage, file_obj, "upload_largefile888")

    with get_session() as db:
        user = get_or_create_guest_user(db, "127.0.0.1")
        asset = Asset(
            type=AssetType.UPLOAD,
            identifier="largefile888",
            storage_path=storage_path,
            meta={"original_ext": ".mp4"},
            created_by=user.id,
        )
        db.add(asset)
        db.commit()
        asset_id = asset.id

    response = client.get(f"/api/assets/{asset_id}/stream")

    assert response.status_code == 200
    assert len(response.content) == 25000
    assert response.content == test_content


def test_stream_range_large_file(client: TestClient, storage_dir: tempfile.TemporaryDirectory):
    """Test Range request on large file crosses chunk boundaries."""
    test_content = b"0123456789" * 2000  # 20KB file
    file_obj = io.BytesIO(test_content)

    import services_registry

    storage = services_registry.storage
    storage_path = await_storage_save(storage, file_obj, "upload_rangelarge777")

    with get_session() as db:
        user = get_or_create_guest_user(db, "127.0.0.1")
        asset = Asset(
            type=AssetType.UPLOAD,
            identifier="rangelarge777",
            storage_path=storage_path,
            meta={"original_ext": ".mp4"},
            created_by=user.id,
        )
        db.add(asset)
        db.commit()
        asset_id = asset.id

    # Range that crosses default 8KB chunk boundary
    response = client.get(f"/api/assets/{asset_id}/stream", headers={"Range": "bytes=5000-15000"})

    assert response.status_code == 206
    assert int(response.headers["content-length"]) == 10001  # 15000 - 5000 + 1
    assert response.content == test_content[5000:15001]
