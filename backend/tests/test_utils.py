from __future__ import annotations

import asyncio
import uuid
from unittest.mock import MagicMock

import httpx
import pytest
import tenacity
from fastapi import HTTPException
from sqlalchemy import literal

from utils.db_helpers import as_clause
from utils.resilience import retry_on_http_errors, retry_on_ytdlp_errors
from utils.task_manager import TaskManager
from utils.validation import parse_uuid


class TestRetryOnHttpErrors:
    def test_retries_timeout_error(self, monkeypatch):
        monkeypatch.setattr(tenacity.nap, "sleep", lambda _: None)
        calls = {"count": 0}

        @retry_on_http_errors(attempts=3)
        def flaky():
            calls["count"] += 1
            raise httpx.TimeoutException("timeout")

        with pytest.raises(httpx.TimeoutException):
            flaky()

        assert calls["count"] == 3

    def test_non_retryable_error_passthrough(self, monkeypatch):
        monkeypatch.setattr(tenacity.nap, "sleep", lambda _: None)
        calls = {"count": 0}

        @retry_on_http_errors(attempts=3)
        def boom():
            calls["count"] += 1
            raise ValueError("no retry")

        with pytest.raises(ValueError):
            boom()

        assert calls["count"] == 1


class TestRetryOnYtdlpErrors:
    def test_retries_timeout_error(self, monkeypatch):
        pytest.importorskip("yt_dlp")
        monkeypatch.setattr(tenacity.nap, "sleep", lambda _: None)
        calls = {"count": 0}

        @retry_on_ytdlp_errors(attempts=2)
        def flaky():
            calls["count"] += 1
            raise TimeoutError("timeout")

        with pytest.raises(TimeoutError):
            flaky()

        assert calls["count"] == 2


class TestTaskManager:
    @pytest.mark.asyncio
    async def test_create_task_tracks_and_cleans_up(self):
        logger = MagicMock()
        manager = TaskManager(logger)

        async def work():
            await asyncio.sleep(0)
            return "done"

        task = manager.create_task(work())
        assert task in manager._tasks

        await task
        await asyncio.sleep(0)

        assert task not in manager._tasks

    def test_create_task_raises_when_closing(self):
        manager = TaskManager(MagicMock())
        manager._closing = True
        coro = asyncio.sleep(0)

        with pytest.raises(RuntimeError):
            manager.create_task(coro)

        coro.close()

    @pytest.mark.asyncio
    async def test_shutdown_cancels_pending_tasks(self):
        logger = MagicMock()
        manager = TaskManager(logger)
        blocker = asyncio.Event()

        async def wait_forever():
            await blocker.wait()

        task = manager.create_task(wait_forever())
        await manager.shutdown(timeout=0)

        assert logger.warning.called
        assert task.cancelled() or task.done()

        await asyncio.sleep(0)
        assert task not in manager._tasks


class TestValidation:
    def test_parse_uuid_valid(self):
        value = uuid.uuid4()
        assert parse_uuid(str(value)) == value

    def test_parse_uuid_invalid(self):
        with pytest.raises(HTTPException) as exc_info:
            parse_uuid("not-a-uuid", "asset ID")

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Invalid asset ID format"


class TestDbHelpers:
    def test_as_clause_returns_expression(self):
        expr = literal(True)
        assert as_clause(expr) is expr
