from __future__ import annotations

import asyncio
import os
import shutil
import time
from typing import Optional

from fastapi import UploadFile

import state
from models import TaskStatus, UploadSession
from settings import get_settings
from utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

UPLOAD_DIR = "temp"
UPLOAD_SESSION_TTL_SECONDS = settings.upload_session_ttl_seconds
UPLOAD_SESSION_SWEEP_SECONDS = settings.upload_session_sweep_seconds

def get_upload_session(task_id: str) -> Optional[UploadSession]:
    return state.upload_sessions.get(task_id)


def release_upload_session(task_id: str):
    state.upload_sessions.pop(task_id, None)


def _ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def _touch_file(path: str):
    with open(path, "wb"):
        pass


def _write_upload_file(path: str, upload_file: UploadFile, mode: str = "wb"):
    upload_file.file.seek(0)
    with open(path, mode) as buffer:
        shutil.copyfileobj(upload_file.file, buffer)


async def _safe_remove_file(path: Optional[str], label: str):
    if not path:
        return
    if os.path.exists(path):
        try:
            await asyncio.to_thread(os.remove, path)
            logger.info(f"Removed expired upload {label}: {path}")
        except Exception as e:
            logger.warning(f"Failed to remove expired upload {label} {path}: {e}")


async def cleanup_expired_upload_sessions():
    if not state.upload_sessions:
        return

    now = time.time()
    expired_ids = [
        task_id
        for task_id, session in list(state.upload_sessions.items())
        if not session.completed and (now - session.updated_at) > UPLOAD_SESSION_TTL_SECONDS
    ]

    for task_id in expired_ids:
        session = state.upload_sessions.get(task_id)
        if session is None:
            continue
        async with session.lock:
            if session.completed:
                continue
            if (time.time() - session.updated_at) <= UPLOAD_SESSION_TTL_SECONDS:
                continue

            logger.info(f"Upload session expired: {task_id}")
            state.update_task(
                task_id,
                TaskStatus.FAILED,
                0,
                "Upload expired",
                error="Upload expired (TTL exceeded).",
            )
            await _safe_remove_file(session.temp_file, "file")
            await _safe_remove_file(session.subtitle_path, "subtitle")
            release_upload_session(task_id)


async def sweep_upload_sessions():
    while True:
        await asyncio.sleep(UPLOAD_SESSION_SWEEP_SECONDS)
        await cleanup_expired_upload_sessions()
