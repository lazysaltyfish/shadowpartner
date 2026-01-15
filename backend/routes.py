from __future__ import annotations

import asyncio
import os
import time
import uuid
from typing import Optional

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

import services_registry
import session_manager
import state
from db import get_session
from db.crud import (
    get_all_assets,
    get_asset_by_id,
    get_or_create_guest_user,
    get_subtitle_track_by_asset,
)
from db.models import AssetType, SubtitleTrackType
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
) -> tuple[str, Optional[VideoResponse], Optional[str], Optional[str]]:
    """Handle file upload with cache check and temp storage.

    Args:
        file: Uploaded file object
        filename: Original filename
        auth_session: Auth session for user tracking
        subtitle: Optional subtitle file

    Returns:
        (video_id, cached_result, temp_file, subtitle_path)
    """
    # Generate video_id from file hash
    await asyncio.to_thread(_ensure_dir, UPLOAD_DIR)
    ext = os.path.splitext(filename)[1] or ".mp3"
    temp_file = os.path.join(UPLOAD_DIR, f"{uuid.uuid4()}{ext}")

    await asyncio.to_thread(_write_upload_file, temp_file, file, "wb")
    video_id = await asyncio.to_thread(generate_video_id_from_file, temp_file)
    logger.info(f"Generated video_id: {video_id} for file: {filename}")

    cached_result = check_cache(video_id)
    if cached_result:
        logger.info(f"Cached result found for: {video_id}, skipping processing")
        try:
            os.remove(temp_file)
        except OSError as e:
            logger.warning(f"Failed to remove temp file {temp_file}: {e}")
        return video_id, cached_result, None, None

    subtitle_file = None
    if subtitle and subtitle.filename:
        subtitle_ext = os.path.splitext(subtitle.filename)[1] or ".srt"
        subtitle_file = os.path.join(UPLOAD_DIR, f"{uuid.uuid4()}{subtitle_ext}")
        await asyncio.to_thread(_write_upload_file, subtitle_file, subtitle, "wb")
        logger.info(f"Subtitle uploaded: {subtitle_file}")

    return video_id, None, temp_file, subtitle_file


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
):
    try:
        # Check for cached result
        youtube_id = video_request.url.split("v=")[-1].split("&")[0].split("/watch?v=")[-1][:11]
        cached_result = check_cache(youtube_id)

        if cached_result:
            task_id = str(uuid.uuid4())
            state.tasks[task_id] = TaskInfo(
                task_id=task_id,
                status=TaskStatus.COMPLETED,
                progress=100,
                message="Using cached processing result",
                result=cached_result,
            )
            if auth_session:
                await session_manager.update_session_upload(auth_session, 0, task_increment=True)
            return AsyncProcessResponse(task_id=task_id, message="Using cached result")

        task_id = str(uuid.uuid4())
        state.tasks[task_id] = TaskInfo(
            task_id=task_id,
            status=TaskStatus.PENDING,
            message="Downloading video...",
        )
        logger.info(f"Starting video processing task {task_id} for URL: {video_request.url}")

        if auth_session:
            await session_manager.update_session_upload(auth_session, 0, task_increment=True)

        if state.task_manager is None:
            raise RuntimeError("Task manager not initialized")
        state.task_manager.create_task(
            download_and_process(task_id, video_request.url),
            name=f"download_and_process:{task_id}",
        )

        return AsyncProcessResponse(task_id=task_id, message="Video processing started")

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

        # Check for existing asset (deduplication only)
        # Note: session.temp_file already contains the complete file
        video_id, cached_result = await handle_existing_file(
            file_path=session.temp_file,
            filename=filename,
        )

        if cached_result:
            # Update the existing task with cached result
            state.tasks[task_id] = TaskInfo(
                task_id=task_id,
                status=TaskStatus.COMPLETED,
                progress=100,
                message="Using cached processing result",
                result=cached_result,
            )
            session.completed = True
            session.processing_started = True
            await session_manager.update_session_upload(
                auth_session, total_size, task_increment=True
            )
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
            return AsyncProcessResponse(task_id=task_id, message="Using cached result")

        # Start processing
        state.tasks[task_id].status = TaskStatus.PENDING
        state.tasks[task_id].message = "Upload complete. Processing..."

        session.completed = True
        session.processing_started = True

        await session_manager.update_session_upload(auth_session, total_size, task_increment=True)

        if state.task_manager is None:
            raise RuntimeError("Task manager not initialized")

        # Use the original temp file for processing (session.temp_file contains the uploaded data)
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

    # Handle file upload with Asset creation and deduplication
    video_id, cached_result, temp_file, subtitle_path = await handle_file_upload(
        file, file.filename, subtitle
    )

    file_size = file.size if file.size is not None else 0
    await session_manager.update_session_upload(auth_session, file_size, task_increment=True)

    if cached_result:
        task_id = str(uuid.uuid4())
        state.tasks[task_id] = TaskInfo(
            task_id=task_id,
            status=TaskStatus.COMPLETED,
            progress=100,
            message="Using cached processing result",
            result=cached_result,
        )
        return AsyncProcessResponse(task_id=task_id, message="Using cached result")

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
        ),
        name=f"process_audio_task:{task_id}",
    )

    return AsyncProcessResponse(task_id=task_id, message="File uploaded, processing started")


# ==================== Public Asset API ====================


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
                title = track.content.get("title", "") if track else ""
                thumbnail = None
                if asset.type == AssetType.YOUTUBE:
                    thumbnail = f"https://img.youtube.com/vi/{asset.identifier}/mqdefault.jpg"
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

        return {
            "id": str(asset.id),
            "type": asset.type.value,
            "identifier": asset.identifier,
            "title": content.get("title", ""),
            "segments": [seg.model_dump() for seg in segments],
            "has_word_timestamps": content.get("has_word_timestamps", True),
            "created_at": asset.created_at.isoformat(),
        }


@router.get("/api/assets/{asset_id}/stream")
@limiter.limit("30/minute")
async def stream_asset(request: Request, asset_id: str):
    """Stream media file for uploaded assets (public endpoint for play page).

    Supports HTTP Range requests for video seeking.

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

        # Get storage service and file path
        storage = services_registry.storage
        if storage is None:
            raise HTTPException(status_code=500, detail="Storage service not available")

        full_path = storage.get_full_path(asset.storage_path)
        if not os.path.exists(full_path):
            raise HTTPException(status_code=404, detail="File not found in storage")

        # Get file info
        file_size = os.path.getsize(full_path)
        ext = asset.meta.get("original_ext", ".mp3") if asset.meta else ".mp3"
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

                def iter_range():
                    with open(full_path, "rb") as f:
                        f.seek(start)
                        remaining = content_length
                        while remaining > 0:
                            chunk_size = min(8192, remaining)
                            chunk = f.read(chunk_size)
                            if not chunk:
                                break
                            remaining -= len(chunk)
                            yield chunk

                return StreamingResponse(
                    iter_range(),
                    status_code=206,
                    media_type=mime_type,
                    headers={
                        "Content-Range": f"bytes {start}-{end}/{file_size}",
                        "Accept-Ranges": "bytes",
                        "Content-Length": str(content_length),
                    },
                )

        # Full file response
        def iter_file():
            with open(full_path, "rb") as f:
                while chunk := f.read(8192):
                    yield chunk

        return StreamingResponse(
            iter_file(),
            media_type=mime_type,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(file_size),
            },
        )
