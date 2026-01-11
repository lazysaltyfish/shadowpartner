from __future__ import annotations

import asyncio
import os
import time
import uuid
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile

import state
from models import AsyncProcessResponse, TaskInfo, TaskStatus, UploadSession, VideoRequest
from processing import download_and_process, process_audio_task
from services.video_utils import generate_video_id_from_file
from uploads import (
    UPLOAD_DIR,
    _ensure_dir,
    _touch_file,
    _write_upload_file,
    get_upload_session,
)
from utils.logger import get_logger

router = APIRouter()
logger = get_logger(__name__)


@router.get("/api/status/{task_id}", response_model=TaskInfo)
async def get_task_status(task_id: str):
    if task_id not in state.tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    return state.tasks[task_id]


@router.get("/")
async def root():
    return {"message": "ShadowPartner API is running"}


@router.post("/api/process", response_model=AsyncProcessResponse)
async def process_video(request: VideoRequest, background_tasks: BackgroundTasks):
    try:
        task_id = str(uuid.uuid4())
        state.tasks[task_id] = TaskInfo(
            task_id=task_id,
            status=TaskStatus.PENDING,
            message="Downloading video...",
        )
        logger.info(f"Starting video processing task {task_id} for URL: {request.url}")

        if state.task_manager is None:
            raise RuntimeError("Task manager not initialized")
        state.task_manager.create_task(
            download_and_process(task_id, request.url),
            name=f"download_and_process:{task_id}",
        )

        return AsyncProcessResponse(task_id=task_id, message="Video processing started")

    except Exception as e:
        logger.error(f"Error starting video processing: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/upload/init", response_model=AsyncProcessResponse)
async def init_upload(
    filename: str = Form(...),
    total_chunks: int = Form(...),
    total_size: int = Form(...),
):
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
async def upload_chunk(
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
        if session.expected_total_chunks is not None and chunk_index >= session.expected_total_chunks:
            raise HTTPException(status_code=409, detail="Chunk index exceeds declared total")
        if chunk_index < session.next_index:
            # Duplicate chunk upload; acknowledge to support retries.
            return {"status": "success"}
        if chunk_index > session.next_index:
            raise HTTPException(
                status_code=409,
                detail=f"Out-of-order chunk. Expected {session.next_index}, got {chunk_index}.",
            )

        await asyncio.to_thread(_write_upload_file, session.temp_file, file, "ab")
        session.next_index += 1
        session.updated_at = time.time()

    state.tasks[task_id].message = f"Uploaded chunk {chunk_index + 1}"
    logger.debug(f"Task {task_id}: Uploaded chunk {chunk_index + 1}")
    return {"status": "success"}


@router.post("/api/upload/subtitle")
async def upload_subtitle(
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
async def complete_upload(
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

        # Generate stable video_id based on file content hash
        video_id = await asyncio.to_thread(generate_video_id_from_file, session.temp_file)
        logger.info(f"Task {task_id}: Generated video_id={video_id} for file={filename}")

        state.tasks[task_id].status = TaskStatus.PENDING
        state.tasks[task_id].message = "Upload complete. Processing..."

        session.completed = True
        session.processing_started = True

        if state.task_manager is None:
            raise RuntimeError("Task manager not initialized")
        state.task_manager.create_task(
            process_audio_task(
                task_id,
                session.temp_file,
                video_id,  # Use hash-based video_id
                filename,
                download_time=0.0,
                subtitle_path=subtitle_path,
            ),
            name=f"process_audio_task:{task_id}",
        )

    return AsyncProcessResponse(task_id=task_id, message="Processing started")


@router.post("/api/upload", response_model=AsyncProcessResponse)
async def upload_video(
    background_tasks: BackgroundTasks,
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
    temp_file = None
    subtitle_file = None
    try:
        # Save uploaded file immediately
        await asyncio.to_thread(_ensure_dir, UPLOAD_DIR)

        session_id = str(uuid.uuid4())
        # Use mp3 extension as we will process it as audio
        ext = os.path.splitext(file.filename)[1] or ".mp3"
        temp_file = os.path.join(UPLOAD_DIR, f"{session_id}{ext}")

        await asyncio.to_thread(_write_upload_file, temp_file, file, "wb")

        logger.info(f"File uploaded: {temp_file}")

        # Save subtitle file if provided
        if subtitle and subtitle.filename:
            subtitle_ext = os.path.splitext(subtitle.filename)[1] or ".srt"
            subtitle_file = os.path.join(UPLOAD_DIR, f"{session_id}_subtitle{subtitle_ext}")

            await asyncio.to_thread(_write_upload_file, subtitle_file, subtitle, "wb")

            logger.info(f"Subtitle uploaded: {subtitle_file}")

        # Generate stable video_id based on file content hash
        video_id = await asyncio.to_thread(generate_video_id_from_file, temp_file)
        logger.info(f"Generated video_id: {video_id} for file: {file.filename}")

        # Start async task
        task_id = str(uuid.uuid4())

        if subtitle_file:
            state.tasks[task_id] = TaskInfo(
                task_id=task_id,
                status=TaskStatus.PENDING,
                message="Files uploaded. Using provided subtitle...",
            )
        else:
            state.tasks[task_id] = TaskInfo(
                task_id=task_id,
                status=TaskStatus.PENDING,
                message="File uploaded. Queued for processing...",
            )

        logger.info(f"Starting processing task {task_id} for uploaded file")
        if state.task_manager is None:
            raise RuntimeError("Task manager not initialized")
        state.task_manager.create_task(
            process_audio_task(
                task_id,
                temp_file,
                video_id,  # Use hash-based video_id
                file.filename,
                download_time=0.0,
                subtitle_path=subtitle_file,
            ),
            name=f"process_audio_task:{task_id}",
        )

        return AsyncProcessResponse(task_id=task_id, message="File uploaded, processing started")

    except Exception as e:
        logger.error(f"Error processing uploaded file: {e}", exc_info=True)
        # Cleanup if we failed before starting task
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception as cleanup_error:
                logger.warning(f"Failed to cleanup temp file: {cleanup_error}")
        if subtitle_file and os.path.exists(subtitle_file):
            try:
                os.remove(subtitle_file)
            except Exception as cleanup_error:
                logger.warning(f"Failed to cleanup subtitle file: {cleanup_error}")
        raise HTTPException(status_code=500, detail=str(e))
