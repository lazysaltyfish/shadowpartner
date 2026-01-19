from __future__ import annotations

import uuid
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from db import get_session
from main import create_app


@pytest.fixture(scope="function")
def client():
    app = create_app(rate_limit_enabled_override=False)
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


def test_get_playlists_is_public(client):
    """GET /api/playlists is public and does not require admin auth."""
    response = client.get("/api/playlists")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data


def test_create_playlist_requires_admin(client):
    response = client.post("/api/playlists", json={"title": "Test"})
    assert response.status_code == 401


def test_get_playlist_by_id_is_public(client, test_playlist):
    """GET /api/playlists/{id} is public and does not require admin auth."""
    response = client.get(f"/api/playlists/{test_playlist.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(test_playlist.id)


def test_get_playlist_items_is_public(client, test_playlist):
    """GET /api/playlists/{id}/items is public and does not require admin auth."""
    response = client.get(f"/api/playlists/{test_playlist.id}/items")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data


def test_get_playlist_context_is_public(client, test_playlist_with_items):
    """GET /api/playlists/{id}/context is public and does not require admin auth."""
    # First get items to find an asset_id
    response = client.get(f"/api/playlists/{test_playlist_with_items.id}/items")
    asset_id = response.json()["items"][0]["asset_id"]

    response = client.get(
        f"/api/playlists/{test_playlist_with_items.id}/context?asset_id={asset_id}"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["playlist_id"] == str(test_playlist_with_items.id)


def test_update_playlist_requires_admin(client, test_playlist):
    """PUT /api/playlists/{id} requires admin auth."""
    response = client.put(f"/api/playlists/{test_playlist.id}", json={"title": "Updated"})
    assert response.status_code == 401


def test_delete_playlist_requires_admin(client, test_playlist):
    """DELETE /api/playlists/{id} requires admin auth."""
    response = client.delete(f"/api/playlists/{test_playlist.id}")
    assert response.status_code == 401


def test_add_playlist_item_requires_admin(client, test_playlist, test_assets):
    """POST /api/playlists/{id}/items requires admin auth."""
    payload = {"asset_id": str(test_assets[0])}
    response = client.post(f"/api/playlists/{test_playlist.id}/items", json=payload)
    assert response.status_code == 401


def test_set_playlist_item_position_requires_admin(client, test_playlist_with_items):
    """PUT /api/playlists/{id}/items/{asset_id} requires admin auth."""
    # Get items via public endpoint
    response = client.get(f"/api/playlists/{test_playlist_with_items.id}/items")
    asset_id = response.json()["items"][0]["asset_id"]

    response = client.put(
        f"/api/playlists/{test_playlist_with_items.id}/items/{asset_id}",
        json={"position": 1},
    )
    assert response.status_code == 401


def test_delete_playlist_item_requires_admin(client, test_playlist_with_items):
    """DELETE /api/playlists/{id}/items/{asset_id} requires admin auth."""
    # Get items via public endpoint
    response = client.get(f"/api/playlists/{test_playlist_with_items.id}/items")
    asset_id = response.json()["items"][0]["asset_id"]

    response = client.delete(f"/api/playlists/{test_playlist_with_items.id}/items/{asset_id}")
    assert response.status_code == 401


def test_get_playlists_empty(admin_client):
    response = admin_client.get("/api/playlists")
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0


def test_get_playlists_with_data(admin_client, test_playlist):
    response = admin_client.get("/api/playlists")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["title"] == "Test Playlist"


def test_get_playlist_by_id(admin_client, test_playlist):
    response = admin_client.get(f"/api/playlists/{test_playlist.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(test_playlist.id)
    assert data["title"] == "Test Playlist"
    assert data["items"] == []


def test_get_playlist_not_found(admin_client):
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = admin_client.get(f"/api/playlists/{fake_id}")
    assert response.status_code == 404


def test_create_playlist_success(admin_client):
    payload = {"title": "New Playlist", "description": "New description"}
    response = admin_client.post("/api/playlists", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "New Playlist"
    assert data["description"] == "New description"


def test_create_playlist_empty_title_fails(admin_client):
    response = admin_client.post("/api/playlists", json={"title": " "})
    assert response.status_code == 400


def test_update_playlist_success(admin_client, test_playlist):
    payload = {"title": "Updated Title", "description": "Updated description"}
    response = admin_client.put(f"/api/playlists/{test_playlist.id}", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Updated Title"


def test_delete_playlist_success(admin_client, test_playlist):
    response = admin_client.delete(f"/api/playlists/{test_playlist.id}")
    assert response.status_code == 200

    response = admin_client.get(f"/api/playlists/{test_playlist.id}")
    assert response.status_code == 404


def test_get_playlist_items(admin_client, test_playlist_with_items):
    response = admin_client.get(f"/api/playlists/{test_playlist_with_items.id}/items")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert len(data["items"]) == 3


def test_add_item_to_playlist(admin_client, test_playlist, test_assets):
    payload = {"asset_id": str(test_assets[0])}
    response = admin_client.post(f"/api/playlists/{test_playlist.id}/items", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["position"] == 0


def test_add_item_with_position_clamped(admin_client, test_playlist, test_assets):
    payload = {"asset_id": str(test_assets[0]), "position": 5}
    response = admin_client.post(f"/api/playlists/{test_playlist.id}/items", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["position"] == 0


def test_add_duplicate_item_returns_409(admin_client, test_playlist, test_assets):
    payload = {"asset_id": str(test_assets[0])}
    response = admin_client.post(f"/api/playlists/{test_playlist.id}/items", json=payload)
    assert response.status_code == 200

    response = admin_client.post(f"/api/playlists/{test_playlist.id}/items", json=payload)
    assert response.status_code == 409


def test_set_item_position(admin_client, test_playlist_with_items):
    response = admin_client.get(f"/api/playlists/{test_playlist_with_items.id}/items")
    items = response.json()["items"]
    asset_id = items[2]["asset_id"]

    payload = {"position": 0}
    response = admin_client.put(
        f"/api/playlists/{test_playlist_with_items.id}/items/{asset_id}", json=payload
    )
    assert response.status_code == 200

    response = admin_client.get(f"/api/playlists/{test_playlist_with_items.id}/items")
    items = response.json()["items"]
    assert items[0]["asset_id"] == asset_id


def test_remove_item_from_playlist(admin_client, test_playlist_with_items):
    response = admin_client.get(f"/api/playlists/{test_playlist_with_items.id}/items")
    asset_id = response.json()["items"][0]["asset_id"]

    response = admin_client.delete(f"/api/playlists/{test_playlist_with_items.id}/items/{asset_id}")
    assert response.status_code == 200

    response = admin_client.get(f"/api/playlists/{test_playlist_with_items.id}/items")
    items = response.json()["items"]
    assert len(items) == 2


def test_get_playlist_context(admin_client, test_playlist_with_items):
    response = admin_client.get(f"/api/playlists/{test_playlist_with_items.id}/items")
    asset_id = response.json()["items"][0]["asset_id"]

    response = admin_client.get(
        f"/api/playlists/{test_playlist_with_items.id}/context?asset_id={asset_id}"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["playlist_id"] == str(test_playlist_with_items.id)
    assert data["current_position"] == 0
    assert len(data["items"]) == 3


def test_get_playlist_context_asset_not_in_playlist(admin_client, test_playlist):
    fake_asset_id = str(uuid.uuid4())
    response = admin_client.get(
        f"/api/playlists/{test_playlist.id}/context?asset_id={fake_asset_id}"
    )
    assert response.status_code == 404


def test_search_assets_by_title(admin_client, test_assets):
    response = admin_client.get("/api/assets/search?q=Test Video")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 3


def test_search_assets_empty_query(admin_client, test_assets):
    response = admin_client.get("/api/assets/search?q=")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 3


def test_search_assets_no_results(admin_client):
    response = admin_client.get("/api/assets/search?q=nonexistent_playlist_asset")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
