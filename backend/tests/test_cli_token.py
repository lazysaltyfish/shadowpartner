"""Tests for X-CLI-Token authentication and rate limit bypass."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

import settings
from main import create_app
from models import AuthSession
from routers import decorators
from session_manager import update_session_upload
from utils.cli_token import CLI_TOKEN_HEADER
from api_policy import RateLimitTier


@pytest.fixture
def cli_token(monkeypatch: pytest.MonkeyPatch) -> str:
    token = "test-cli-token"
    monkeypatch.setenv("CLI_MAGIC_TOKEN", token)
    settings.get_settings.cache_clear()
    yield token
    settings.get_settings.cache_clear()


@pytest.fixture
def cli_client(cli_token: str) -> TestClient:
    app = create_app(rate_limit_enabled_override=False)
    return TestClient(app)


def test_cli_token_process_allows_without_sessions(cli_client: TestClient, cli_token: str):
    response = cli_client.post(
        "/api/process",
        json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
        headers={CLI_TOKEN_HEADER: cli_token},
    )
    assert response.status_code != 401
    assert response.status_code in (200, 500, 503)


def test_cli_token_upload_init_allows_without_sessions(cli_client: TestClient, cli_token: str):
    response = cli_client.post(
        "/api/upload/init",
        data={"filename": "test.mp3", "total_chunks": 1, "total_size": 1024},
        headers={CLI_TOKEN_HEADER: cli_token},
    )
    assert response.status_code in (200, 503)


def test_cli_token_playlist_create(cli_client: TestClient, cli_token: str):
    response = cli_client.post(
        "/api/playlists",
        json={"title": "CLI Playlist"},
        headers={CLI_TOKEN_HEADER: cli_token},
    )
    assert response.status_code == 200
    data = response.json()
    assert "id" in data


def test_cli_token_bypasses_session_limits(cli_token: str):
    session = AuthSession(
        session_id="cli-session",
        ip_address="cli",
        created_at=0.0,
        expires_at=999999.0,
        user_id=uuid.UUID(int=0),
        is_cli=True,
    )
    result = asyncio.run(update_session_upload(session, file_size=10**12, task_increment=True))
    assert result is True


def test_rate_limit_bypass_for_cli_token(monkeypatch: pytest.MonkeyPatch, cli_token: str):
    calls = {"limited": 0, "raw": 0}

    def fake_limit(tier: str):
        def decorator(func):
            def wrapped(*args, **kwargs):
                calls["limited"] += 1
                return func(*args, **kwargs)

            return wrapped

        return decorator

    monkeypatch.setattr(decorators.limiter, "limit", fake_limit)

    @decorators.rate_limit(RateLimitTier.LOW)
    def handler(request: Request):
        calls["raw"] += 1
        return "ok"

    cli_scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(CLI_TOKEN_HEADER.lower().encode(), cli_token.encode())],
    }
    handler(Request(cli_scope))

    normal_scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
    }
    handler(Request(normal_scope))

    assert calls["raw"] == 2
    assert calls["limited"] == 1
