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
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, func
from sqlalchemy.sql import ColumnElement

import services_registry
import session_manager
import state
from db import get_session
from db.crud import (
    get_all_assets,
    get_asset_by_id,
    get_asset_by_identifier,
    get_or_create_guest_user,
    get_subtitle_track_by_asset,
    get_vocabulary_by_asset,
    get_vocabulary_stats,
)
from db.models import Asset, AssetType, SubtitleTrack, SubtitleTrackType
from models import (
    AsyncProcessResponse,
    AuthSession,
    Segment,
    SessionResponse,
    TaskInfo,
    TaskStatus,
    UploadSession,
    VideoRequest,
    VideoResponse,
    Word,
)
from processing import check_cache, download_and_process, process_audio_task
from rate_limiter import get_limiter
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

router = APIRouter()
logger = get_logger(__name__)

limiter = get_limiter()


def _as_clause(value: Any) -> ColumnElement[bool]:
    return cast(ColumnElement[bool], value)


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


def _get_asset_thumbnail_url(request: Request, asset: Asset) -> Optional[str]:
    if asset.type == AssetType.YOUTUBE:
        return f"https://img.youtube.com/vi/{asset.identifier}/mqdefault.jpg"

    if asset.type == AssetType.UPLOAD and asset.meta:
        if asset.meta.get("thumbnail_path"):
            base_url = str(request.base_url).rstrip("/")
            return f"{base_url}/api/assets/{asset.id}/thumbnail"

    return None


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


@router.get("/api/status/{task_id}", response_model=TaskInfo)
@limiter.limit("120/minute")
async def get_task_status(request: Request, task_id: str):
    if task_id not in state.tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    return state.tasks[task_id]


@router.get("/")
@limiter.exempt
async def root(request: Request):
    return {"message": "ShadowPartner API is running"}


@router.get("/health")
@limiter.exempt
async def health_check(request: Request):
    """Comprehensive health check."""
    health_status = {
        "status": "healthy",
        "services": {
            "transcriber": services_registry.transcriber is not None,
            "analyzer": services_registry.analyzer is not None,
            "translator": services_registry.translator is not None,
            "task_manager": state.task_manager is not None,
        },
        "active_tasks": len(state.tasks),
        "pending_transcription": (
            services_registry.whisper_lock.locked() if services_registry.whisper_lock else False
        ),
    }
    return health_status


@router.post("/api/session", response_model=SessionResponse)
@limiter.limit("10/minute")
async def create_session(request: Request):
    """Create a new anonymous session for upload access."""
    client_host = request.client.host if request.client else "unknown"

    # Create Guest User record in DB
    with get_session() as db:
        user = get_or_create_guest_user(db, client_host)

    session = session_manager.create_session(client_host, user)
    return SessionResponse(session_id=session.session_id, expires_at=int(session.expires_at))


@router.post("/api/process", response_model=AsyncProcessResponse)
@limiter.limit("5/minute")
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
@limiter.limit("5/minute")
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
@limiter.limit("300/minute")
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
@limiter.limit("10/minute")
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
@limiter.limit("5/minute")
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
@limiter.limit("5/minute")
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


# ==================== Public Asset API ====================


@router.get("/api/assets/search")
async def search_assets(
    request: Request,
    q: str = "",
    limit: int = 50,
    offset: int = 0,
    admin_session: AdminSession = Depends(session_manager.get_current_admin_session),
):
    search_term = q.strip().lower()

    with get_session() as db:
        query = (
            db.query(Asset, SubtitleTrack)
            .join(SubtitleTrack)
            .filter(
                _as_clause(SubtitleTrack.track_type == SubtitleTrackType.PROCESSED),
                _as_clause(cast(Any, SubtitleTrack.is_default).is_(True)),
            )
        )
        if search_term:
            search_like = f"%{search_term}%"
            meta_title_expr = func.json_extract(Asset.meta, "$.title")
            track_title_expr = func.json_extract(SubtitleTrack.content, "$.title")
            search_title_expr = func.coalesce(
                func.nullif(meta_title_expr, ""),
                track_title_expr,
                "",
            )
            query = query.filter(
                _as_clause(func.lower(Asset.identifier).like(search_like))
                | _as_clause(func.lower(search_title_expr).like(search_like))
            )
        total = query.with_entities(cast(Any, Asset.id)).distinct().count()
        assets = (
            query.order_by(desc(cast(Any, Asset.created_at)))
            .distinct()
            .limit(limit)
            .offset(offset)
            .all()
        )
        results = []
        for asset, track in assets:
            meta_title = (asset.meta or {}).get("title")
            track_title = track.content.get("title", "") if track else ""
            title = meta_title if meta_title else track_title
            thumbnail = _get_asset_thumbnail_url(request, asset)
            results.append(
                {
                    "id": str(asset.id),
                    "title": title,
                    "thumbnail": thumbnail,
                    "type": asset.type.value,
                }
            )
        return {"items": results, "total": total}


@router.get("/api/assets/{asset_id}")
@limiter.limit("60/minute")
async def get_asset(request: Request, asset_id: str, limit: int = 20, offset: int = 0):
    """Get asset details or list all processed assets.

    Args:
        asset_id: Asset UUID or "list" for listing all processed assets
        limit: Maximum number of assets to return (only for list)
        offset: Number of assets to skip (only for list)

    Returns:
        Asset details with processed subtitle segments, or list of assets
    """
    # Handle list request
    if asset_id == "list":
        with get_session() as db:
            assets, total = get_all_assets(db, limit=limit, offset=offset, processed_only=True)
            items = []
            for asset in assets:
                track = get_subtitle_track_by_asset(
                    db, asset.id, SubtitleTrackType.PROCESSED, is_default=True
                )
                # Prioritize asset.meta title over track.content title
                meta_title = (asset.meta or {}).get("title")
                track_title = track.content.get("title", "") if track else ""
                title = meta_title if meta_title else track_title
                thumbnail = _get_asset_thumbnail_url(request, asset)
                items.append(
                    {
                        "id": str(asset.id),
                        "type": asset.type.value,
                        "title": title,
                        "thumbnail": thumbnail,
                        "created_at": asset.created_at.isoformat(),
                    }
                )
            return {"items": items, "total": total}

    # Handle single asset request
    try:
        asset_uuid = uuid.UUID(asset_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid asset ID format")

    with get_session() as db:
        asset = get_asset_by_id(db, asset_uuid)
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")

        # Get processed subtitle track
        track = get_subtitle_track_by_asset(
            db, asset.id, SubtitleTrackType.PROCESSED, is_default=True
        )
        if not track:
            raise HTTPException(status_code=404, detail="No processed subtitle found")

        content = track.content
        segments_data = content.get("segments", [])
        segments = [
            Segment(
                words=[Word(**w) for w in seg.get("words", [])],
                translation=seg.get("translation", ""),
                start=seg.get("start", 0.0),
                end=seg.get("end", 0.0),
            )
            for seg in segments_data
        ]

        # Prioritize asset.meta title over track.content title
        meta_title = (asset.meta or {}).get("title")
        track_title = content.get("title", "")
        title = meta_title if meta_title else track_title

        return {
            "id": str(asset.id),
            "type": asset.type.value,
            "identifier": asset.identifier,
            "title": title,
            "segments": [seg.model_dump() for seg in segments],
            "has_word_timestamps": content.get("has_word_timestamps", True),
            "created_at": asset.created_at.isoformat(),
        }


@router.get("/api/assets/{asset_id}/thumbnail")
@limiter.limit("60/minute")
async def get_asset_thumbnail(request: Request, asset_id: str):
    try:
        asset_uuid = uuid.UUID(asset_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid asset ID format")

    with get_session() as db:
        asset = get_asset_by_id(db, asset_uuid)
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")

        if asset.type != AssetType.UPLOAD:
            raise HTTPException(status_code=404, detail="Thumbnail not available")

        asset_meta = asset.meta or {}
        thumbnail_path = asset_meta.get("thumbnail_path")
        if not thumbnail_path:
            raise HTTPException(status_code=404, detail="Thumbnail not available")

    storage = services_registry.storage
    if storage is None:
        raise HTTPException(status_code=500, detail="Storage service not available")

    if not await storage.exists(thumbnail_path):
        raise HTTPException(status_code=404, detail="Thumbnail not found")

    file_size = await storage.get_file_size(thumbnail_path)
    mime_type = await storage.get_mime_type(thumbnail_path)

    return StreamingResponse(
        storage.iter_file(thumbnail_path, chunk_size=8192),
        media_type=mime_type,
        headers={"Content-Length": str(file_size)},
    )


@router.get("/api/assets/{asset_id}/stream")
@limiter.limit("30/minute")
async def stream_asset(request: Request, asset_id: str):
    """Stream media file for uploaded assets (public endpoint for play page).

    Supports HTTP Range requests for video seeking.
    Uses storage abstraction for cloud compatibility.

    Args:
        asset_id: Asset UUID

    Returns:
        StreamingResponse with media content
    """
    import mimetypes
    import re

    try:
        asset_uuid = uuid.UUID(asset_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid asset ID format")

    with get_session() as db:
        asset = get_asset_by_id(db, asset_uuid)
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")

        # Only upload type assets have local files
        if asset.type != AssetType.UPLOAD:
            raise HTTPException(
                status_code=400,
                detail="Streaming only available for uploaded files",
            )

        if not asset.storage_path:
            raise HTTPException(status_code=404, detail="File not found")

        # Store values needed outside the session context
        storage_path = asset.storage_path
        asset_meta = asset.meta

    # Get storage service
    storage = services_registry.storage
    if storage is None:
        raise HTTPException(status_code=500, detail="Storage service not available")

    # Check file exists using storage abstraction
    if not await storage.exists(storage_path):
        raise HTTPException(status_code=404, detail="File not found in storage")

    # Get file size using storage abstraction
    file_size = await storage.get_file_size(storage_path)

    # Get MIME type from original extension to avoid identifier-only paths
    ext = asset_meta.get("original_ext", ".mp3") if asset_meta else ".mp3"

    # Special handling for m4a files - use audio/mp4
    if ext.lower() == ".m4a":
        mime_type = "audio/mp4"
    else:
        mime_type, _ = mimetypes.guess_type(f"file{ext}")
        mime_type = mime_type or "application/octet-stream"

    # Handle Range request for video seeking
    range_header = request.headers.get("range")

    if range_header:
        range_match = re.match(r"bytes=(\d+)-(\d*)", range_header)
        if range_match:
            start = int(range_match.group(1))
            end = int(range_match.group(2)) if range_match.group(2) else file_size - 1
            end = min(end, file_size - 1)

            if start >= file_size:
                raise HTTPException(status_code=416, detail="Range not satisfiable")

            content_length = end - start + 1

            # Stream file content using storage abstraction
            content = storage.iter_file(storage_path, start=start, end=end, chunk_size=8192)
            return StreamingResponse(
                content,
                status_code=206,
                media_type=mime_type,
                headers={
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(content_length),
                },
            )

    # Full file response using storage abstraction
    return StreamingResponse(
        storage.iter_file(storage_path, chunk_size=8192),
        media_type=mime_type,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(file_size),
        },
    )


# ==================== Vocabulary API ====================


@router.get("/api/assets/{asset_id}/vocabulary")
@limiter.limit("60/minute")
async def get_asset_vocabulary(
    request: Request,
    asset_id: str,
    jlpt_level: Optional[str] = None,
):
    """Get vocabulary items for an asset.

    Args:
        asset_id: Asset UUID
        jlpt_level: Optional JLPT level filter (N1, N2, N3, N4, N5, Business)

    Returns:
        Vocabulary items with statistics
    """
    try:
        asset_uuid = uuid.UUID(asset_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid asset ID format")

    with get_session() as db:
        asset = get_asset_by_id(db, asset_uuid)
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")

        # Validate jlpt_level if provided
        valid_levels = {"N1", "N2", "N3", "N4", "N5", "Business"}
        if jlpt_level and jlpt_level not in valid_levels:
            raise HTTPException(status_code=400, detail="Invalid JLPT level")

        # Get vocabulary items
        vocab_items = get_vocabulary_by_asset(db, asset_uuid, jlpt_level)

        # Get statistics
        stats = get_vocabulary_stats(db, asset_uuid)

        # Format response
        items = []
        for item in vocab_items:
            items.append(
                {
                    "id": str(item.id),
                    "word": item.word,
                    "reading": item.reading,
                    "surface_form": item.surface_form,
                    "jlpt_level": item.jlpt_level,
                    "part_of_speech": item.part_of_speech,
                    "meaning_cn": item.meaning_cn,
                    "meaning_en": item.meaning_en,
                    "learning_note": item.learning_note,
                    "start_time": item.start_time,
                    "end_time": item.end_time,
                    "context_sentence": item.context_sentence,
                }
            )

        return {
            "asset_id": asset_id,
            "total_count": len(items),
            "items": items,
            "stats": stats,
        }
