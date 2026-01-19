"""Tests for public/auth endpoint authentication behavior.

This module tests critical security behaviors:
1. /api/session should work WITHOUT authentication (public endpoint)
2. /api/process should REQUIRE authentication (401 without X-Session-Id)
3. /api/upload/* endpoints should REQUIRE authentication

These are regression tests to prevent accidental security changes
when refactoring router dependencies.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from main import create_app


@pytest.fixture(scope="function")
def client():
    app = create_app(rate_limit_enabled_override=False)
    client = TestClient(app)
    yield client


class TestSessionEndpoint:
    """Tests for /api/session endpoint (public, no auth required)."""

    def test_create_session_no_auth_required(self, client: TestClient):
        """Test that /api/session works without any authentication headers."""
        response = client.post("/api/session")
        assert response.status_code == 200, (
            f"/api/session should be accessible without auth. "
            f"Got {response.status_code}: {response.json()}"
        )

        data = response.json()
        assert "session_id" in data
        assert "expires_at" in data
        assert isinstance(data["session_id"], str)
        assert isinstance(data["expires_at"], int)

    def test_create_session_returns_valid_session_id(self, client: TestClient):
        """Test that /api/session returns a usable session ID."""
        response = client.post("/api/session")
        assert response.status_code == 200
        data = response.json()
        session_id = data["session_id"]

        # Verify the session ID is a valid UUID format
        import uuid

        try:
            uuid.UUID(session_id)
        except ValueError:
            pytest.fail(f"session_id '{session_id}' is not a valid UUID")


class TestProcessEndpointAuth:
    """Tests for /api/process endpoint authentication (auth required)."""

    def test_process_requires_auth(self, client: TestClient):
        """Test that /api/process returns 401 without X-Session-Id header."""
        response = client.post(
            "/api/process", json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}
        )
        assert response.status_code == 401, (
            f"/api/process should require authentication. "
            f"Got {response.status_code}: {response.json()}"
        )

    def test_process_works_with_valid_session(self, client: TestClient):
        """Test that /api/process works with a valid X-Session-Id."""
        # First, create a session
        session_response = client.post("/api/session")
        assert session_response.status_code == 200
        session_id = session_response.json()["session_id"]

        # Now use that session to call /api/process
        # Note: This will fail with a download error (no network/yt-dlp),
        # but should pass authentication
        process_response = client.post(
            "/api/process",
            json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            headers={"X-Session-Id": session_id},
        )
        # Should get 200 (task created) or a download error, but NOT 401
        assert process_response.status_code != 401, (
            f"/api/process should work with valid session. "
            f"Got {process_response.status_code}: {process_response.json()}"
        )
        assert process_response.status_code in (200, 500), (
            f"Unexpected status code: {process_response.status_code}"
        )

        if process_response.status_code == 200:
            data = process_response.json()
            assert "task_id" in data

    def test_process_rejects_invalid_session(self, client: TestClient):
        """Test that /api/process rejects invalid X-Session-Id."""
        response = client.post(
            "/api/process",
            json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
            headers={"X-Session-Id": "invalid-session-id-12345"},
        )
        assert response.status_code == 401, (
            f"/api/process should reject invalid session. "
            f"Got {response.status_code}: {response.json()}"
        )


class TestUploadEndpointsAuth:
    """Tests for /api/upload/* endpoints authentication (auth required)."""

    def test_upload_init_requires_auth(self, client: TestClient):
        """Test that /api/upload/init returns 401 without X-Session-Id."""
        response = client.post(
            "/api/upload/init", data={"filename": "test.mp3", "total_chunks": 1, "total_size": 1024}
        )
        assert response.status_code == 401, (
            f"/api/upload/init should require authentication. "
            f"Got {response.status_code}: {response.json()}"
        )

    def test_upload_init_works_with_session(self, client: TestClient):
        """Test that /api/upload/init works with valid X-Session-Id."""
        # Create a session first
        session_response = client.post("/api/session")
        assert session_response.status_code == 200
        session_id = session_response.json()["session_id"]

        # Now call upload/init with the session
        response = client.post(
            "/api/upload/init",
            data={"filename": "test.mp3", "total_chunks": 1, "total_size": 1024},
            headers={"X-Session-Id": session_id},
        )
        assert response.status_code == 200, (
            f"/api/upload/init should work with valid session. "
            f"Got {response.status_code}: {response.json()}"
        )
        data = response.json()
        assert "task_id" in data

    def test_upload_requires_auth(self, client: TestClient):
        """Test that /api/upload returns 401 without X-Session-Id."""
        # Use a small dummy file
        response = client.post(
            "/api/upload", files={"file": ("test.mp3", b"dummy content", "audio/mpeg")}
        )
        assert response.status_code == 401, (
            f"/api/upload should require authentication. "
            f"Got {response.status_code}: {response.json()}"
        )
