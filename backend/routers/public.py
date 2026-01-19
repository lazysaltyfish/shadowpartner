"""Public API routes - no authentication required.

This module contains all endpoints that are accessible without any session.
"""

from __future__ import annotations

import session_manager
import uuid
from typing import Any, Optional, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import desc, func
from sqlalchemy.sql import ColumnElement

import services_registry
import state
from db import get_session
from db.crud import (
    get_all_assets,
    get_asset_by_id,
    get_or_create_guest_user,
    get_subtitle_track_by_asset,
    get_vocabulary_by_asset,
    get_vocabulary_stats,
)
from db.models import Asset, AssetType, SubtitleTrack, SubtitleTrackType
from api_policy import RateLimitTier
from models import Segment, SessionResponse, TaskInfo, Word
from routers.decorators import rate_limit
from session_manager import AdminSession, get_current_admin_session
from utils.logger import get_logger

router = APIRouter(tags=["public"])
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


@router.get("/")
@rate_limit(RateLimitTier.EXEMPT)
async def root(request: Request):
    return {"message": "ShadowPartner API is running"}


@router.get("/health")
@rate_limit(RateLimitTier.EXEMPT)
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


@router.get("/api/status/{task_id}", response_model=TaskInfo)
@rate_limit(RateLimitTier.HIGH)
async def get_task_status(request: Request, task_id: str):
    if task_id not in state.tasks:
        raise HTTPException(status_code=404, detail="Task not found")
    return state.tasks[task_id]


@router.post("/api/session")
@rate_limit(RateLimitTier.STRICT)
async def create_session(request: Request):
    """Create a new anonymous session for upload access.

    Returns:
        SessionResponse with session_id and expires_at timestamp
    """
    client_host = request.client.host if request.client else "unknown"

    # Create Guest User record in DB
    with get_session() as db:
        user = get_or_create_guest_user(db, client_host)

    session = session_manager.create_session(client_host, user)
    return SessionResponse(session_id=session.session_id, expires_at=int(session.expires_at))


@router.get("/api/assets/search")
@rate_limit(RateLimitTier.LOW)
async def search_assets(
    request: Request,
    q: str = "",
    limit: int = 50,
    offset: int = 0,
    admin_session: AdminSession = Depends(get_current_admin_session),
):
    """Search processed assets by title/identifier (admin only)."""
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
@rate_limit(RateLimitTier.LOW)
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
@rate_limit(RateLimitTier.LOW)
async def get_asset_thumbnail(request: Request, asset_id: str):
    from fastapi.responses import StreamingResponse

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
@rate_limit(RateLimitTier.MEDIUM)
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

    from fastapi.responses import StreamingResponse

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


@router.get("/api/assets/{asset_id}/vocabulary")
@rate_limit(RateLimitTier.LOW)
async def get_asset_vocabulary(
    request: Request,
    asset_id: str,
):
    """Get vocabulary items for an asset.

    Args:
        asset_id: Asset UUID

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

        # Get all vocabulary items
        vocab_items = get_vocabulary_by_asset(db, asset_uuid)

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
