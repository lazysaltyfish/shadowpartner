from __future__ import annotations

import uuid
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from db import get_session, init_db
from db.crud import get_or_create_guest_user
from db.models import Asset, AssetType, SubtitleSource, SubtitleTrack, SubtitleTrackType
from main import create_app


@pytest.fixture(scope="function")
def client():
    """Create a test client with a fresh database for each test."""
    app = create_app()
    client = TestClient(app)

    # Initialize database
    init_db()

    # Override the get_session dependency to use test database
    def override_get_session():
        from db.engine import SessionLocal

        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_session] = override_get_session

    yield client

    # Clean up
    app.dependency_overrides.clear()


@pytest.fixture
def admin_client(client):
    """Create a client with admin session."""
    # Mock admin credentials to bypass env var check
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
    """Create a test user with assets. Returns user_id (UUID) to avoid detached session issues."""
    # Use unique identifiers per test run to avoid UNIQUE constraint violations
    unique_suffix = str(uuid.uuid4())[:8]
    with get_session() as db:
        user = get_or_create_guest_user(db, "127.0.0.1")
        user.username = f"test_user_{unique_suffix}"
        db.commit()
        db.refresh(user)
        user_id = user.id  # Capture ID before session closes

        # Create some assets
        for i in range(3):
            asset = Asset(
                type=AssetType.UPLOAD,
                identifier=f"test_hash_{unique_suffix}_{i}",
                storage_path=f"/tmp/test_{unique_suffix}_{i}.mp4",
                created_by=user_id,
            )
            db.add(asset)
            db.flush()

            # Create subtitle tracks
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
        response = client.post(
            "/api/admin/login", json={"username": "admin", "password": "wrong"}
        )

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
