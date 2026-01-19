from __future__ import annotations

import uuid
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from db import get_session
from db.crud import get_or_create_guest_user
from db.models import Asset, AssetType, SubtitleSource, SubtitleTrack, SubtitleTrackType
from main import create_app


@pytest.fixture(scope="function")
def client():
    app = create_app()
    client = TestClient(app)

    def override_get_session():
        from db.engine import SessionLocal

        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_session] = override_get_session

    yield client

    app.dependency_overrides.clear()


@pytest.fixture
def admin_client(client):
    with patch(
        "session_manager.get_settings",
        return_value=Mock(admin_username="test_admin", admin_password="test_pass"),
    ):
        response = client.post(
            "/api/admin/login", json={"username": "test_admin", "password": "test_pass"}
        )
        assert response.status_code == 200, f"Admin login failed: {response.json()}"
        data = response.json()
        client.headers = {"X-Admin-Session-Id": data["session_id"]}

    return client


@pytest.fixture
def test_user(client):
    unique_suffix = str(uuid.uuid4())[:8]
    with get_session() as db:
        user = get_or_create_guest_user(db, "127.0.0.1")
        user.username = f"test_user_{unique_suffix}"
        db.commit()
        db.refresh(user)
        user_id = user.id

        for i in range(3):
            asset = Asset(
                type=AssetType.UPLOAD,
                identifier=f"test_hash_{unique_suffix}_{i}",
                storage_path=f"/tmp/test_{unique_suffix}_{i}.mp4",
                created_by=user_id,
            )
            db.add(asset)
            db.flush()

            for j in range(2):
                track = SubtitleTrack(
                    asset_id=asset.id,
                    track_type=SubtitleTrackType.PROCESSED,
                    source=SubtitleSource.AI_GENERATED,
                    language="ja",
                    content={"test": "data"},
                    is_default=(j == 0),
                )
                db.add(track)

        db.commit()
        return user_id


# ==================== Admin Authentication Tests ====================


def test_admin_login_success(client):
    """Test admin login with valid credentials."""
    with patch(
        "session_manager.get_settings",
        return_value=Mock(admin_username="admin", admin_password="admin123"),
    ):
        response = client.post(
            "/api/admin/login", json={"username": "admin", "password": "admin123"}
        )

    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    assert "expires_at" in data
    assert isinstance(data["session_id"], str)
    assert isinstance(data["expires_at"], int)


def test_admin_login_invalid_credentials(client):
    """Test admin login with invalid credentials."""
    with patch(
        "session_manager.get_settings",
        return_value=Mock(admin_username="admin", admin_password="admin123"),
    ):
        response = client.post("/api/admin/login", json={"username": "admin", "password": "wrong"})

    assert response.status_code == 401
    assert "Invalid admin credentials" in response.json()["detail"]


def test_admin_login_missing_env(client, monkeypatch):
    """Test admin login when env vars not set."""
    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)

    response = client.post("/api/admin/login", json={"username": "admin", "password": "admin"})

    assert response.status_code == 401


def test_admin_logout(admin_client):
    """Test admin logout."""
    response = admin_client.post("/api/admin/logout")

    assert response.status_code == 200
    assert "Logged out successfully" in response.json()["message"]


def test_admin_logout_invalid_session(client):
    """Test logout with invalid session."""
    response = client.post("/api/admin/logout", headers={"X-Admin-Session-Id": "invalid_session"})

    assert response.status_code == 404


# ==================== User Management Tests ====================


def test_list_users_as_admin(admin_client, test_user):
    """Test listing users as admin."""
    response = admin_client.get("/api/admin/users")

    assert response.status_code == 200
    users = response.json()
    assert isinstance(users, list)
    assert len(users) > 0
    # Check user structure
    user = users[0]
    assert "id" in user
    assert "username" in user
    assert "created_at" in user
    assert "assets_count" in user


def test_list_users_unauthorized(client):
    """Test listing users without admin session."""
    response = client.get("/api/admin/users")

    assert response.status_code == 401
    assert "Admin session required" in response.json()["detail"]


def test_list_users_pagination(admin_client, test_user):
    """Test user list pagination."""
    response = admin_client.get("/api/admin/users?limit=1&offset=0")

    assert response.status_code == 200
    users = response.json()
    assert len(users) <= 1


def test_delete_user_success(admin_client, test_user):
    """Test deleting a user."""
    response = admin_client.delete(f"/api/admin/users/{test_user}")

    assert response.status_code == 200
    assert "deleted successfully" in response.json()["message"]


def test_delete_user_not_found(admin_client):
    """Test deleting a non-existent user."""
    fake_id = uuid.uuid4()
    response = admin_client.delete(f"/api/admin/users/{fake_id}")

    assert response.status_code == 404
    assert "User not found" in response.json()["detail"]


def test_delete_user_invalid_id(admin_client):
    """Test deleting user with invalid ID format."""
    response = admin_client.delete("/api/admin/users/invalid-uuid")

    assert response.status_code == 400
    assert "Invalid user ID format" in response.json()["detail"]


def test_delete_user_cascades_to_assets(admin_client, test_user):
    """Test that deleting a user also deletes their assets."""
    # Delete user
    admin_client.delete(f"/api/admin/users/{test_user}")

    # Verify assets are deleted
    with get_session() as db:
        remaining_assets = db.query(Asset).filter(Asset.created_by == test_user).all()
        assert len(remaining_assets) == 0


# ==================== Asset Management Tests ====================


def test_list_assets_as_admin(admin_client, test_user):
    """Test listing assets as admin."""
    response = admin_client.get("/api/admin/assets")

    assert response.status_code == 200
    assets = response.json()
    assert isinstance(assets, list)
    assert len(assets) > 0
    # Check asset structure
    asset = assets[0]
    assert "id" in asset
    assert "type" in asset
    assert "identifier" in asset
    assert "storage_path" in asset
    assert "created_by" in asset
    assert "created_at" in asset
    assert "subtitle_tracks_count" in asset


def test_list_assets_unauthorized(client):
    """Test listing assets without admin session."""
    response = client.get("/api/admin/assets")

    assert response.status_code == 401


def test_list_assets_pagination(admin_client, test_user):
    """Test asset list pagination."""
    response = admin_client.get("/api/admin/assets?limit=2&offset=0")

    assert response.status_code == 200
    assets = response.json()
    assert len(assets) <= 2


def test_delete_asset_success(admin_client, test_user):
    """Test deleting an asset."""
    with get_session() as db:
        asset = db.query(Asset).filter(Asset.created_by == test_user).first()
        asset_id = asset.id

    response = admin_client.delete(f"/api/admin/assets/{asset_id}")

    assert response.status_code == 200
    assert "deleted successfully" in response.json()["message"]


def test_delete_asset_not_found(admin_client):
    """Test deleting a non-existent asset."""
    fake_id = uuid.uuid4()
    response = admin_client.delete(f"/api/admin/assets/{fake_id}")

    assert response.status_code == 404


def test_delete_asset_cascades_to_tracks(admin_client, test_user):
    """Test that deleting an asset also deletes subtitle tracks."""
    with get_session() as db:
        asset = db.query(Asset).filter(Asset.created_by == test_user).first()
        track_count_before = len(asset.subtitle_tracks)
        asset_id = asset.id

    assert track_count_before > 0

    # Delete asset
    admin_client.delete(f"/api/admin/assets/{asset_id}")

    # Verify tracks are deleted
    with get_session() as db:
        remaining_tracks = db.query(SubtitleTrack).filter(SubtitleTrack.asset_id == asset_id).all()
        assert len(remaining_tracks) == 0


# ==================== Subtitle Track Management Tests ====================


def test_list_subtitle_tracks_as_admin(admin_client, test_user):
    """Test listing subtitle tracks as admin."""
    response = admin_client.get("/api/admin/subtitle-tracks")

    assert response.status_code == 200
    tracks = response.json()
    assert isinstance(tracks, list)
    assert len(tracks) > 0
    # Check track structure
    track = tracks[0]
    assert "id" in track
    assert "asset_id" in track
    assert "track_type" in track
    assert "source" in track
    assert "language" in track
    assert "is_default" in track
    assert "created_at" in track


def test_list_subtitle_tracks_unauthorized(client):
    """Test listing subtitle tracks without admin session."""
    response = client.get("/api/admin/subtitle-tracks")

    assert response.status_code == 401


def test_list_subtitle_tracks_pagination(admin_client, test_user):
    """Test subtitle track list pagination."""
    response = admin_client.get("/api/admin/subtitle-tracks?limit=5&offset=0")

    assert response.status_code == 200
    tracks = response.json()
    assert len(tracks) <= 5


def test_delete_subtitle_track_success(admin_client, test_user):
    """Test deleting a subtitle track."""
    with get_session() as db:
        asset = db.query(Asset).filter(Asset.created_by == test_user).first()
        track = db.query(SubtitleTrack).filter(SubtitleTrack.asset_id == asset.id).first()
        track_id = track.id

    response = admin_client.delete(f"/api/admin/subtitle-tracks/{track_id}")

    assert response.status_code == 200
    assert "deleted successfully" in response.json()["message"]


def test_delete_subtitle_track_not_found(admin_client):
    """Test deleting a non-existent subtitle track."""
    fake_id = uuid.uuid4()
    response = admin_client.delete(f"/api/admin/subtitle-tracks/{fake_id}")

    assert response.status_code == 404


def test_delete_subtitle_track_invalid_id(admin_client):
    """Test deleting track with invalid ID format."""
    response = admin_client.delete("/api/admin/subtitle-tracks/invalid-uuid")

    assert response.status_code == 400
    assert "Invalid track ID format" in response.json()["detail"]


# ==================== Session Management Tests ====================


def test_expired_admin_session(client):
    """Test that expired admin sessions are rejected."""
    # Login and get session with mocked credentials
    with patch(
        "session_manager.get_settings",
        return_value=Mock(admin_username="admin", admin_password="admin123"),
    ):
        response = client.post(
            "/api/admin/login", json={"username": "admin", "password": "admin123"}
        )
    assert response.status_code == 200
    data = response.json()
    session_id = data["session_id"]

    # Try to use session immediately (should work)
    response = client.get("/api/admin/users", headers={"X-Admin-Session-Id": session_id})
    assert response.status_code == 200

    # Mock expired session by deleting from state
    import state

    if session_id in state.admin_sessions:
        del state.admin_sessions[session_id]

    # Try to use expired session (should fail)
    response = client.get("/api/admin/users", headers={"X-Admin-Session-Id": session_id})
    assert response.status_code == 401
    assert "Invalid or expired admin session" in response.json()["detail"]


def test_missing_admin_session_header(client):
    """Test requests without admin session header."""
    response = client.get("/api/admin/users")

    assert response.status_code == 401
    assert "Admin session required" in response.json()["detail"]


# ==================== Asset Metadata Tests ====================


def test_get_asset_meta_success(admin_client, test_user):
    """Test getting asset metadata as admin."""
    with get_session() as db:
        asset = db.query(Asset).filter(Asset.created_by == test_user).first()
        asset.meta = {"title": "Test Title", "description": "Test Description"}
        db.commit()
        asset_id = asset.id

    response = admin_client.get(f"/api/admin/assets/{asset_id}/meta")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(asset_id)
    assert data["title"] == "Test Title"
    assert data["description"] == "Test Description"
    assert "type" in data
    assert "identifier" in data
    assert "is_admin_upload" in data


def test_get_asset_meta_not_found(admin_client):
    """Test getting metadata for non-existent asset."""
    fake_id = uuid.uuid4()
    response = admin_client.get(f"/api/admin/assets/{fake_id}/meta")

    assert response.status_code == 404
    assert "Asset not found" in response.json()["detail"]


def test_get_asset_meta_invalid_id(admin_client):
    """Test getting metadata with invalid ID format."""
    response = admin_client.get("/api/admin/assets/invalid-uuid/meta")

    assert response.status_code == 400
    assert "Invalid asset ID format" in response.json()["detail"]


def test_get_asset_meta_unauthorized(client, test_user):
    """Test getting metadata without admin session."""
    with get_session() as db:
        asset = db.query(Asset).filter(Asset.created_by == test_user).first()
        asset_id = asset.id

    response = client.get(f"/api/admin/assets/{asset_id}/meta")

    assert response.status_code == 401


def test_update_asset_meta_success(admin_client, test_user):
    """Test updating asset metadata as admin."""
    with get_session() as db:
        asset = db.query(Asset).filter(Asset.created_by == test_user).first()
        asset_id = asset.id

    response = admin_client.patch(
        f"/api/admin/assets/{asset_id}/meta",
        json={"title": "New Title", "description": "New Description"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "New Title"
    assert data["description"] == "New Description"

    # Verify in database
    with get_session() as db:
        asset = db.query(Asset).filter(Asset.id == asset_id).first()
        assert asset.meta["title"] == "New Title"
        assert asset.meta["description"] == "New Description"


def test_update_asset_meta_partial(admin_client, test_user):
    """Test partial update of asset metadata."""
    with get_session() as db:
        asset = db.query(Asset).filter(Asset.created_by == test_user).first()
        asset.meta = {"title": "Original Title", "description": "Original Description"}
        db.commit()
        asset_id = asset.id

    # Update only title
    response = admin_client.patch(
        f"/api/admin/assets/{asset_id}/meta",
        json={"title": "Updated Title"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Updated Title"
    # Description should be preserved
    assert data["description"] == "Original Description"


def test_update_asset_meta_not_found(admin_client):
    """Test updating metadata for non-existent asset."""
    fake_id = uuid.uuid4()
    response = admin_client.patch(
        f"/api/admin/assets/{fake_id}/meta",
        json={"title": "New Title"},
    )

    assert response.status_code == 404
    assert "Asset not found" in response.json()["detail"]


def test_update_asset_meta_invalid_id(admin_client):
    """Test updating metadata with invalid ID format."""
    response = admin_client.patch(
        "/api/admin/assets/invalid-uuid/meta",
        json={"title": "New Title"},
    )

    assert response.status_code == 400
    assert "Invalid asset ID format" in response.json()["detail"]


def test_update_asset_meta_no_fields(admin_client, test_user):
    """Test updating metadata with no fields."""
    with get_session() as db:
        asset = db.query(Asset).filter(Asset.created_by == test_user).first()
        asset_id = asset.id

    response = admin_client.patch(
        f"/api/admin/assets/{asset_id}/meta",
        json={},
    )

    assert response.status_code == 400
    assert "No fields to update" in response.json()["detail"]


def test_update_asset_meta_unauthorized(client, test_user):
    """Test updating metadata without admin session."""
    with get_session() as db:
        asset = db.query(Asset).filter(Asset.created_by == test_user).first()
        asset_id = asset.id

    response = client.patch(
        f"/api/admin/assets/{asset_id}/meta",
        json={"title": "New Title"},
    )

    assert response.status_code == 401


# ==================== Admin Upload Flag Tests ====================


def test_is_admin_upload_flag_default(admin_client, test_user):
    """Test that is_admin_upload defaults to False."""
    with get_session() as db:
        asset = db.query(Asset).filter(Asset.created_by == test_user).first()
        asset_id = asset.id

    response = admin_client.get(f"/api/admin/assets/{asset_id}/meta")

    assert response.status_code == 200
    data = response.json()
    assert data["is_admin_upload"] is False


def test_is_admin_upload_flag_set(admin_client, test_user):
    """Test that is_admin_upload can be set to True."""
    with get_session() as db:
        asset = db.query(Asset).filter(Asset.created_by == test_user).first()
        asset.is_admin_upload = True
        db.commit()
        asset_id = asset.id

    response = admin_client.get(f"/api/admin/assets/{asset_id}/meta")

    assert response.status_code == 200
    data = response.json()
    assert data["is_admin_upload"] is True


def test_list_assets_includes_is_admin_upload(admin_client, test_user):
    """Test that asset list includes is_admin_upload field."""
    response = admin_client.get("/api/admin/assets")

    assert response.status_code == 200
    assets = response.json()
    assert len(assets) > 0
    # Check that is_admin_upload is in the response
    asset = assets[0]
    assert "is_admin_upload" in asset


def test_list_assets_includes_title(admin_client, test_user):
    """Test that admin asset list includes title field with correct priority."""
    meta_title = "Admin Meta Title"

    with get_session() as db:
        asset = db.query(Asset).filter(Asset.created_by == test_user).first()
        asset.meta = {"title": meta_title}
        db.commit()
        asset_id = asset.id

    response = admin_client.get("/api/admin/assets")

    assert response.status_code == 200
    assets = response.json()
    assert len(assets) > 0
    # Find the asset we modified
    asset_item = next((a for a in assets if a["id"] == str(asset_id)), None)
    assert asset_item is not None
    assert "title" in asset_item
    assert asset_item["title"] == meta_title


# ==================== Title Priority Tests ====================


def test_asset_meta_title_takes_priority_over_track_content(client, test_user):
    """Test that asset.meta title takes priority over track.content title."""
    original_title = "Original Track Title"
    meta_title = "Updated Meta Title"

    with get_session() as db:
        # Create asset with meta title
        asset = db.query(Asset).filter(Asset.created_by == test_user).first()
        asset.meta = {"title": meta_title}
        db.commit()
        asset_id = asset.id

        # Update the track content to have a different title
        track = db.query(SubtitleTrack).filter(SubtitleTrack.asset_id == asset_id).first()
        if track:
            content = track.content or {}
            content["title"] = original_title
            track.content = content
            db.commit()

    # Test single asset endpoint - should return meta title
    response = client.get(f"/api/assets/{asset_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == meta_title

    # Test list endpoint - should also return meta title
    response = client.get("/api/assets/list")
    assert response.status_code == 200
    items = response.json()["items"]
    asset_item = next((item for item in items if item["id"] == str(asset_id)), None)
    if asset_item:
        assert asset_item["title"] == meta_title


def test_asset_falls_back_to_track_content_title(client, test_user):
    """Test that asset falls back to track.content title when meta title is empty."""
    track_title = "Track Content Title"

    with get_session() as db:
        # Create asset without meta title
        asset = db.query(Asset).filter(Asset.created_by == test_user).first()
        asset.meta = {}  # No title in meta
        db.commit()
        asset_id = asset.id

        # Set track content title
        track = db.query(SubtitleTrack).filter(SubtitleTrack.asset_id == asset_id).first()
        if track:
            content = dict(track.content) if track.content else {}
            content["title"] = track_title
            track.content = content
            db.add(track)  # Mark as modified
            db.commit()

    # Test single asset endpoint - should return track content title
    response = client.get(f"/api/assets/{asset_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == track_title


def test_asset_list_includes_upload_thumbnail(client, test_user):
    with get_session() as db:
        asset = db.query(Asset).filter(Asset.created_by == test_user).first()
        asset.meta = {"thumbnail_path": "upload_thumb_meta_123.jpg"}
        db.commit()
        asset_id = asset.id

    response = client.get("/api/assets/list")
    assert response.status_code == 200
    items = response.json()["items"]
    asset_item = next((item for item in items if item["id"] == str(asset_id)), None)
    assert asset_item is not None
    assert asset_item["thumbnail"] == f"http://testserver/api/assets/{asset_id}/thumbnail"


# ==================== Storage File Deletion Tests ====================


def test_delete_asset_deletes_storage_file(admin_client, test_user):
    """Test that deleting an asset also deletes the storage file using storage abstraction."""
    import asyncio
    import io

    import services_registry

    # Initialize storage service if not already initialized
    if services_registry.storage is None:
        import lifecycle

        asyncio.run(lifecycle.startup_event())

    # Create a test file in storage
    test_content = b"Test storage file content " * 50
    file_obj = io.BytesIO(test_content)
    thumb_content = b"Test thumbnail content " * 20
    thumb_obj = io.BytesIO(thumb_content)

    storage = services_registry.storage
    # Save file to storage
    storage_path = asyncio.run(storage.save(file_obj, "upload_storage_test_123"))
    thumbnail_path = asyncio.run(storage.save(thumb_obj, "upload_storage_test_123_thumb.jpg"))

    # Create asset with storage path
    with get_session() as db:
        asset = Asset(
            type=AssetType.UPLOAD,
            identifier="storage_test_123",
            storage_path=storage_path,
            meta={"original_ext": ".mp4", "thumbnail_path": thumbnail_path},
            created_by=test_user,
        )
        db.add(asset)
        db.commit()
        asset_id = asset.id

    # Verify file exists before deletion
    exists_before = asyncio.run(storage.exists(storage_path))
    assert exists_before is True
    thumb_exists_before = asyncio.run(storage.exists(thumbnail_path))
    assert thumb_exists_before is True

    # Delete asset via admin API
    response = admin_client.delete(f"/api/admin/assets/{asset_id}")
    assert response.status_code == 200

    # Verify storage file was deleted
    exists_after = asyncio.run(storage.exists(storage_path))
    assert exists_after is False
    thumb_exists_after = asyncio.run(storage.exists(thumbnail_path))
    assert thumb_exists_after is False


def test_delete_user_deletes_all_storage_files(admin_client):
    """Test that deleting a user also deletes all their storage files using storage abstraction."""
    import asyncio
    import io

    import services_registry

    # Initialize storage service if not already initialized
    if services_registry.storage is None:
        import lifecycle

        asyncio.run(lifecycle.startup_event())

    storage = services_registry.storage

    # Create a test user with multiple assets
    unique_suffix = str(uuid.uuid4())[:8]
    with get_session() as db:
        user = get_or_create_guest_user(db, "127.0.0.1")
        user.username = f"storage_test_user_{unique_suffix}"
        db.commit()
        db.refresh(user)
        user_id = user.id

        # Create 3 assets with storage files
        storage_paths = []
        for i in range(3):
            test_content = f"Test content {i} ".encode() * 50
            file_obj = io.BytesIO(test_content)
            storage_path = asyncio.run(
                storage.save(file_obj, f"upload_storage_user_{unique_suffix}_{i}")
            )
            storage_paths.append(storage_path)

            asset = Asset(
                type=AssetType.UPLOAD,
                identifier=f"storage_user_{unique_suffix}_{i}",
                storage_path=storage_path,
                meta={"original_ext": ".mp4"},
                created_by=user_id,
            )
            db.add(asset)
        db.commit()

    # Verify all files exist before deletion
    for storage_path in storage_paths:
        exists = asyncio.run(storage.exists(storage_path))
        assert exists is True, f"File should exist before deletion: {storage_path}"

    # Delete user via admin API
    response = admin_client.delete(f"/api/admin/users/{user_id}")
    assert response.status_code == 200

    # Verify all storage files were deleted
    for storage_path in storage_paths:
        exists = asyncio.run(storage.exists(storage_path))
        assert exists is False, f"File should be deleted: {storage_path}"


def test_delete_asset_with_missing_storage_file(admin_client, test_user):
    """Test deleting asset when storage file is already missing (should not fail)."""
    import asyncio

    import services_registry

    # Initialize storage service if not already initialized
    if services_registry.storage is None:
        import lifecycle

        asyncio.run(lifecycle.startup_event())

    # Create asset with a storage path that doesn't exist
    with get_session() as db:
        asset = Asset(
            type=AssetType.UPLOAD,
            identifier="missing_file_asset",
            storage_path="upload_nonexistent_file_xyz",
            meta={"original_ext": ".mp4"},
            created_by=test_user,
        )
        db.add(asset)
        db.commit()
        asset_id = asset.id

    # Delete asset should succeed even if file doesn't exist
    response = admin_client.delete(f"/api/admin/assets/{asset_id}")
    assert response.status_code == 200
    assert "deleted successfully" in response.json()["message"]


def test_delete_user_with_some_missing_storage_files(admin_client):
    """Test deleting user when some storage files are missing (should not fail)."""
    import asyncio
    import io

    import services_registry

    # Initialize storage service if not already initialized
    if services_registry.storage is None:
        import lifecycle

        asyncio.run(lifecycle.startup_event())

    storage = services_registry.storage

    # Create a test user with mixed storage files
    unique_suffix = str(uuid.uuid4())[:8]
    with get_session() as db:
        user = get_or_create_guest_user(db, "127.0.0.1")
        user.username = f"partial_storage_user_{unique_suffix}"
        db.commit()
        db.refresh(user)
        user_id = user.id

        # Asset 1: with actual file
        test_content = b"Existing file content " * 50
        file_obj = io.BytesIO(test_content)
        storage_path_1 = asyncio.run(storage.save(file_obj, f"upload_partial_{unique_suffix}_1"))
        asset_1 = Asset(
            type=AssetType.UPLOAD,
            identifier=f"partial_{unique_suffix}_1",
            storage_path=storage_path_1,
            meta={"original_ext": ".mp4"},
            created_by=user_id,
        )
        db.add(asset_1)

        # Asset 2: without actual file (storage path only)
        asset_2 = Asset(
            type=AssetType.UPLOAD,
            identifier=f"partial_{unique_suffix}_2",
            storage_path="upload_nonexistent_partial_xyz",
            meta={"original_ext": ".mp4"},
            created_by=user_id,
        )
        db.add(asset_2)

        db.commit()

    # Delete user should succeed even with missing files
    response = admin_client.delete(f"/api/admin/users/{user_id}")
    assert response.status_code == 200
    assert "deleted successfully" in response.json()["message"]

    # Existing file should be deleted
    exists_after = asyncio.run(storage.exists(storage_path_1))
    assert exists_after is False
