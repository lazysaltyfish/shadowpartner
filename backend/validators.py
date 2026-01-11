from __future__ import annotations

import os
from pathlib import Path

import magic
from fastapi import HTTPException, UploadFile

ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".flv", ".webm", ".mp3", ".m4a", ".wav"}
ALLOWED_VIDEO_MIME_TYPES = {
    "video/mp4",
    "video/quicktime",
    "video/x-msvideo",
    "video/x-matroska",
    "video/webm",
    "video/x-flv",
    "audio/mpeg",
    "audio/mp4",
    "audio/wav",
    "audio/x-wav",
}
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB


def get_upload_file_size(upload_file: UploadFile) -> int:
    upload_file.file.seek(0, os.SEEK_END)
    file_size = upload_file.file.tell()
    upload_file.file.seek(0)
    return file_size


def _validate_extension(filename: str) -> None:
    if not filename:
        raise HTTPException(status_code=400, detail="Missing filename")
    file_ext = Path(filename).suffix.lower()
    if file_ext not in ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(status_code=415, detail=f"File type {file_ext} not allowed")


def validate_upload_size(file_size: int) -> None:
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large (max {MAX_FILE_SIZE // (1024 * 1024)}MB)",
        )


def validate_upload_metadata(filename: str, total_size: int) -> None:
    _validate_extension(filename)
    validate_upload_size(total_size)


async def validate_upload_mime(file: UploadFile) -> None:
    chunk = await file.read(2048)
    file.file.seek(0)
    mime = magic.from_buffer(chunk, mime=True)
    if mime not in ALLOWED_VIDEO_MIME_TYPES:
        raise HTTPException(status_code=415, detail=f"MIME type {mime} not allowed")


async def validate_upload_file(file: UploadFile) -> None:
    file_size = get_upload_file_size(file)
    validate_upload_size(file_size)
    _validate_extension(file.filename)
    await validate_upload_mime(file)
