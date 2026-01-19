"""Authenticated API routes - requires X-Session-Id header.

This module contains endpoints for file upload and processing that require
an anonymous auth session.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from typing import Any, Optional, cast

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from sqlalchemy.sql import ColumnElement

import session_manager
import state
from api_policy import RateLimitTier
from db import get_session
from db.crud import get_asset_by_identifier
from db.models import Asset, AssetType
from models import (
    AsyncProcessResponse,
    AuthSession,
    TaskInfo,
    TaskStatus,
    UploadSession,
    VideoRequest,
    VideoResponse,
)
from processing import check_cache, download_and_process, process_audio_task
from routers.decorators import rate_limit
from services.video_utils import generate_video_id_from_file
from session_manager import AdminSession
from uploads import (
    UPLOAD_DIR,
    _ensure_dir,
    _touch_file,
    _write_upload_file,
    get_upload_session,
    release_upload_session,
)
from utils.logger import get_logger
from validators import (
    get_upload_file_size,
    validate_upload_file,
    validate_upload_metadata,
    validate_upload_mime,
    validate_upload_size,
)

router = APIRouter(dependencies=[Depends(session_manager.get_current_session)], tags=["auth"])
logger = get_logger(__name__)


def _as_clause(value: Any) -> ColumnElement[bool]:
    return cast(ColumnElement[bool], value)


def _get_asset_thumbnail_url(request: Request, asset: Asset) -> Optional[str]:
    if asset.type == AssetType.YOUTUBE:
        return f"https://img.youtube.com/vi/{asset.identifier}/mqdefault.jpg"

    if asset.type == AssetType.UPLOAD and asset.meta:
        if asset.meta.get("thumbnail_path"):
            base_url = str(request.base_url).rstrip("/")
            return f"{base_url}/api/assets/{asset.id}/thumbnail"

    return None


def _get_existing_asset(identifier: str, asset_type: AssetType) -> Optional[Asset]:
    """Check if an asset with the given identifier and type already exists.

    Args:
        identifier: Asset identifier (YouTube ID or file hash)
        asset_type: Asset type (YOUTUBE or UPLOAD)

    Returns:
        Asset if exists, None otherwise
    """
    with get_session() as db:
        return get_asset_by_identifier(db, asset_type, identifier)


async def handle_existing_file(
    file_path: str,
    filename: str,
) -> tuple[str, Optional[VideoResponse]]:
    """Check for existing asset with cached result by file hash.

    Args:
        file_path: Path to existing file
        filename: Original filename

    Returns:
        (video_id, is_cached) - video_id from file hash, is_cached if processed result exists
    """
    video_id = await asyncio.to_thread(generate_video_id_from_file, file_path)
    logger.info(f"Generated video_id: {video_id} for file: {filename}")

    # Check if we have a cached processing result (not just asset exists)
    cached_result = check_cache(video_id)
    if cached_result:
        logger.info(f"Cached result found for: {video_id}, skipping processing")
        return video_id, cached_result

    return video_id, None


async def handle_file_upload(
    file: UploadFile,
    filename: str,
    subtitle: Optional[UploadFile] = None,
) -> tuple[str, Optional[str], Optional[str]]:
    """Handle file upload and temp storage.

    Args:
        file: Uploaded file object
        filename: Original filename
        subtitle: Optional subtitle file

    Returns:
        (video_id, temp_file, subtitle_path)
    """
    # Generate video_id from file hash
    await asyncio.to_thread(_ensure_dir, UPLOAD_DIR)
    ext = os.path.splitext(filename)[1] or ".mp3"
    temp_file = os.path.join(UPLOAD_DIR, f"{uuid.uuid4()}{ext}")

    await asyncio.to_thread(_write_upload_file, temp_file, file, "wb")
    video_id = await asyncio.to_thread(generate_video_id_from_file, temp_file)
    logger.info(f"Generated video_id: {video_id} for file: {filename}")

    subtitle_file = None
    if subtitle and subtitle.filename:
        subtitle_ext = os.path.splitext(subtitle.filename)[1] or ".srt"
        subtitle_file = os.path.join(UPLOAD_DIR, f"{uuid.uuid4()}{subtitle_ext}")
        await asyncio.to_thread(_write_upload_file, subtitle_file, subtitle, "wb")
        logger.info(f"Subtitle uploaded: {subtitle_file}")

    return video_id, temp_file, subtitle_file


@router.post("/api/process", response_model=AsyncProcessResponse)
@rate_limit(RateLimitTier.UPLOAD)
async def process_video(
    request: Request,
    video_request: VideoRequest,
    background_tasks: BackgroundTasks,
    auth_session: Optional[AuthSession] = Depends(session_manager.get_current_session_optional),
    admin_session: Optional[AdminSession] = Depends(
        session_manager.get_current_admin_session_optional
    ),
):
    try:
        # Check session limits BEFORE creating any task entries
        if auth_session:
            limit_ok = await session_manager.update_session_upload(
                auth_session, 0, task_increment=True
            )
            if not limit_ok:
                raise HTTPException(status_code=429, detail="Session upload limit exceeded")

        # Check for existing asset
        youtube_id = video_request.url.split("v=")[-1].split("&")[0].split("/watch?v=")[-1][:11]
        existing_asset = _get_existing_asset(youtube_id, AssetType.YOUTUBE)

        if existing_asset:
            # Asset already exists, return 409 with asset info
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "该内容已存在",
                    "asset_id": str(existing_asset.id),
                    "title": existing_asset.meta.get("title") if existing_asset.meta else None,
                },
            )

        task_id = str(uuid.uuid4())
        state.tasks[task_id] = TaskInfo(
            task_id=task_id,
            status=TaskStatus.PENDING,
            message="Downloading video...",
        )
        logger.info(f"Starting video processing task {task_id} for URL: {video_request.url}")

        if state.task_manager is None:
            raise RuntimeError("Task manager not initialized")

        is_admin_upload = admin_session is not None
        state.task_manager.create_task(
            download_and_process(task_id, video_request.url, is_admin_upload=is_admin_upload),
            name=f"download_and_process:{task_id}",
        )

        return AsyncProcessResponse(task_id=task_id, message="Video processing started")

    except HTTPException:
        # Re-raise HTTPException as-is (don't wrap in 500)
        raise
    except Exception as e:
        logger.error(f"Error starting video processing: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/upload/init", response_model=AsyncProcessResponse)
@rate_limit(RateLimitTier.UPLOAD)
async def init_upload(
    request: Request,
    auth_session: AuthSession = Depends(session_manager.get_current_session),
    filename: str = Form(...),
    total_chunks: int = Form(...),
    total_size: int = Form(...),
):
    validate_upload_metadata(filename, total_size)
    task_id = str(uuid.uuid4())
    await asyncio.to_thread(_ensure_dir, UPLOAD_DIR)

    ext = os.path.splitext(filename)[1] or ".mp3"
    temp_file = os.path.join(UPLOAD_DIR, f"{task_id}{ext}")

    await asyncio.to_thread(_touch_file, temp_file)

    state.tasks[task_id] = TaskInfo(
        task_id=task_id,
        status=TaskStatus.PENDING,
        message="Initialized upload...",
    )
    state.upload_sessions[task_id] = UploadSession(
        task_id=task_id,
        temp_file=temp_file,
        expected_total_chunks=total_chunks,
        expected_total_size=total_size,
    )
    logger.info(f"Upload initialized: task_id={task_id}, filename={filename}")

    return AsyncProcessResponse(task_id=task_id, message="Upload initialized")


@router.post("/api/upload/chunk")
@rate_limit(RateLimitTier.CHUNK)
async def upload_chunk(
    request: Request,
    auth_session: AuthSession = Depends(session_manager.get_current_session),
    task_id: str = Form(...),
    chunk_index: int = Form(...),
    file: UploadFile = File(...),
):
    if task_id not in state.tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    session = get_upload_session(task_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Upload session not found")

    if chunk_index < 0:
        raise HTTPException(status_code=400, detail="Invalid chunk index")

    async with session.lock:
        if session.completed:
            raise HTTPException(status_code=409, detail="Upload already completed")
        if (
            session.expected_total_chunks is not None
            and chunk_index >= session.expected_total_chunks
        ):
            raise HTTPException(status_code=409, detail="Chunk index exceeds declared total")
        if chunk_index < session.next_index:
            # Duplicate chunk upload; acknowledge to support retries.
            return {"status": "success"}
        if chunk_index > session.next_index:
            raise HTTPException(
                status_code=409,
                detail=f"Out-of-order chunk. Expected {session.next_index}, got {chunk_index}.",
            )

        if session.expected_total_size is not None:
            validate_upload_size(session.expected_total_size)
        chunk_size = get_upload_file_size(file)
        current_size = os.path.getsize(session.temp_file)
        if (
            session.expected_total_size is not None
            and current_size + chunk_size > session.expected_total_size
        ):
            raise HTTPException(status_code=409, detail="Upload size exceeds declared total")
        validate_upload_size(current_size + chunk_size)
        if chunk_index == 0:
            await validate_upload_mime(file)

        await asyncio.to_thread(_write_upload_file, session.temp_file, file, "ab")
        session.next_index += 1
        session.updated_at = time.time()

    state.tasks[task_id].message = f"Uploaded chunk {chunk_index + 1}"
    logger.debug(f"Task {task_id}: Uploaded chunk {chunk_index + 1}")
    return {"status": "success"}


@router.post("/api/upload/subtitle")
@rate_limit(RateLimitTier.STRICT)
async def upload_subtitle(
    request: Request,
    auth_session: AuthSession = Depends(session_manager.get_current_session),
    task_id: str = Form(...),
    file: UploadFile = File(...),
):
    """
    Upload a subtitle file for an existing chunked upload session.
    The subtitle file will be saved with the naming convention {task_id}_subtitle.{ext}
    """
    if task_id not in state.tasks:
        raise HTTPException(status_code=404, detail="Task not found")

    session = get_upload_session(task_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Upload session not found")
    if not os.path.exists(UPLOAD_DIR):
        await asyncio.to_thread(_ensure_dir, UPLOAD_DIR)

    if not file.filename:
        raise HTTPException(status_code=400, detail="Subtitle filename is missing")

    # Save subtitle file with task_id prefix
    subtitle_ext = os.path.splitext(file.filename)[1] or ".srt"
    subtitle_path = os.path.join(UPLOAD_DIR, f"{task_id}_subtitle{subtitle_ext}")

    async with session.lock:
        if session.completed:
            raise HTTPException(status_code=409, detail="Upload already completed")
        await asyncio.to_thread(_write_upload_file, subtitle_path, file, "wb")
        session.subtitle_path = subtitle_path
        session.updated_at = time.time()

    logger.info(f"Task {task_id}: Subtitle uploaded - {subtitle_path}")
    return {"status": "success", "path": subtitle_path}


@router.post("/api/upload/complete", response_model=AsyncProcessResponse)
@rate_limit(RateLimitTier.UPLOAD)
async def complete_upload(
    request: Request,
    auth_session: AuthSession = Depends(session_manager.get_current_session),
    admin_session: Optional[AdminSession] = Depends(
        session_manager.get_current_admin_session_optional
    ),
    task_id: str = Form(...),
    filename: str = Form(...),
    subtitle_filename: Optional[str] = Form(None),
    total_chunks: int = Form(...),
    total_size: int = Form(...),
):
    if task_id not in state.tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    session = get_upload_session(task_id)
    if session is None:
        return AsyncProcessResponse(task_id=task_id, message="Processing already started")

    async with session.lock:
        if session.completed:
            return AsyncProcessResponse(task_id=task_id, message="Processing already started")
        if not os.path.exists(session.temp_file):
            raise HTTPException(status_code=404, detail="File not found")

        if session.expected_total_chunks != total_chunks:
            raise HTTPException(status_code=400, detail="Total chunks mismatch")

        if session.expected_total_size != total_size:
            raise HTTPException(status_code=400, detail="Total size mismatch")

        if session.next_index != session.expected_total_chunks:
            raise HTTPException(status_code=409, detail="Upload incomplete")

        actual_size = os.path.getsize(session.temp_file)
        if actual_size != session.expected_total_size:
            raise HTTPException(status_code=409, detail="Upload size mismatch")

        subtitle_path = session.subtitle_path
        if subtitle_filename and subtitle_path is None:
            subtitle_files = [
                f for f in os.listdir(UPLOAD_DIR) if f.startswith(f"{task_id}_subtitle")
            ]
            if subtitle_files:
                subtitle_path = os.path.join(UPLOAD_DIR, subtitle_files[0])
                logger.info(f"Task {task_id}: Found subtitle for completion - {subtitle_path}")

        # Check for existing asset
        video_id = await asyncio.to_thread(generate_video_id_from_file, session.temp_file)
        existing_asset = _get_existing_asset(video_id, AssetType.UPLOAD)

        if existing_asset:
            # Clean up temp files
            if session.temp_file and os.path.exists(session.temp_file):
                try:
                    os.remove(session.temp_file)
                except OSError as e:
                    logger.warning(f"Failed to remove temp file {session.temp_file}: {e}")
            if subtitle_path and os.path.exists(subtitle_path):
                try:
                    os.remove(subtitle_path)
                except OSError as e:
                    logger.warning(f"Failed to remove subtitle file {subtitle_path}: {e}")
            release_upload_session(task_id)

            # Asset already exists, return 409 with asset info
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "该内容已存在",
                    "asset_id": str(existing_asset.id),
                    "title": existing_asset.meta.get("title") if existing_asset.meta else filename,
                },
            )

        # Start processing
        state.tasks[task_id].status = TaskStatus.PENDING
        state.tasks[task_id].message = "Upload complete. Processing..."

        session.completed = True
        session.processing_started = True

        limit_ok = await session_manager.update_session_upload(
            auth_session, total_size, task_increment=True
        )
        if not limit_ok:
            raise HTTPException(status_code=429, detail="Session upload limit exceeded")

        if state.task_manager is None:
            raise RuntimeError("Task manager not initialized")

        # Use the original temp file for processing (session.temp_file contains the uploaded data)
        is_admin_upload = admin_session is not None
        state.task_manager.create_task(
            process_audio_task(
                task_id,
                session.temp_file,
                video_id,
                filename,
                download_time=0.0,
                subtitle_path=subtitle_path,
                created_by=auth_session.user_id,
                asset_meta={
                    "filename": filename,
                    "original_ext": os.path.splitext(filename)[1] or ".mp3",
                },
                is_admin_upload=is_admin_upload,
            ),
            name=f"process_audio_task:{task_id}",
        )

    return AsyncProcessResponse(task_id=task_id, message="Processing started")


@router.post("/api/upload", response_model=AsyncProcessResponse)
@rate_limit(RateLimitTier.UPLOAD)
async def upload_video(
    request: Request,
    background_tasks: BackgroundTasks,
    auth_session: AuthSession = Depends(session_manager.get_current_session),
    admin_session: Optional[AdminSession] = Depends(
        session_manager.get_current_admin_session_optional
    ),
    file: UploadFile = File(...),
    subtitle: Optional[UploadFile] = File(None),
):
    """
    Upload audio/video file for processing.

    Args:
        file: The audio/video file to process (required)
        subtitle: Optional subtitle file in SRT format. If provided, AI transcription
                 will be skipped and the provided subtitle will be used instead.

    Returns:
        AsyncProcessResponse with task_id for tracking progress
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is missing")

    await validate_upload_file(file)

    # Handle file upload and check for existing asset
    video_id, temp_file, subtitle_path = await handle_file_upload(file, file.filename, subtitle)

    file_size = file.size if file.size is not None else 0
    limit_ok = await session_manager.update_session_upload(
        auth_session, file_size, task_increment=True
    )
    if not limit_ok:
        raise HTTPException(status_code=429, detail="Session upload limit exceeded")

    # Check for existing asset
    existing_asset = _get_existing_asset(video_id, AssetType.UPLOAD)
    if existing_asset:
        # Clean up temp files
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except OSError as e:
                logger.warning(f"Failed to remove temp file {temp_file}: {e}")
        if subtitle_path and os.path.exists(subtitle_path):
            try:
                os.remove(subtitle_path)
            except OSError as e:
                logger.warning(f"Failed to remove subtitle file {subtitle_path}: {e}")

        # Asset already exists, return 409 with asset info
        raise HTTPException(
            status_code=409,
            detail={
                "message": "该内容已存在",
                "asset_id": str(existing_asset.id),
                "title": existing_asset.meta.get("title") if existing_asset.meta else file.filename,
            },
        )

    # Start async task
    task_id = str(uuid.uuid4())
    state.tasks[task_id] = TaskInfo(
        task_id=task_id,
        status=TaskStatus.PENDING,
        message="File uploaded. Queued for processing...",
    )

    logger.info(f"Starting processing task {task_id} for uploaded file")
    if state.task_manager is None:
        raise RuntimeError("Task manager not initialized")

    if temp_file is None:
        raise HTTPException(status_code=500, detail="Temporary upload file missing")

    is_admin_upload = admin_session is not None
    state.task_manager.create_task(
        process_audio_task(
            task_id,
            temp_file,
            video_id,
            file.filename,
            download_time=0.0,
            subtitle_path=subtitle_path,
            created_by=auth_session.user_id,
            asset_meta={
                "filename": file.filename,
                "original_ext": os.path.splitext(file.filename)[1] or ".mp3",
            },
            is_admin_upload=is_admin_upload,
        ),
        name=f"process_audio_task:{task_id}",
    )

    return AsyncProcessResponse(task_id=task_id, message="File uploaded, processing started")
