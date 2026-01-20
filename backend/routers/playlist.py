"""Playlist API routes.

This module contains endpoints for managing playlists.
- GET endpoints are public (no authentication required)
- POST/PUT/DELETE endpoints require X-Admin-Session-Id header
"""

from __future__ import annotations

from typing import Any, List, Optional, cast

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import desc, func

from api_policy import RateLimitTier
from db import get_session
from db.crud import get_asset_by_id, get_subtitle_track_by_asset
from db.models import (
    Asset,
    AssetType,
    OwnerType,
    Playlist,
    PlaylistAsset,
    PlaylistType,
    SubtitleTrackType,
)
from routers.decorators import rate_limit
from session_manager import AdminSession, get_current_admin_session
from utils.db_helpers import as_clause
from utils.logger import get_logger
from utils.validation import parse_uuid

router = APIRouter(
    prefix="/api/playlists",
    tags=["playlists"],
)
logger = get_logger(__name__)

POSITION_OFFSET_PADDING = 1000


# ==================== Request/Response Models ====================


class PlaylistCreateRequest(BaseModel):
    title: str
    description: Optional[str] = None
    cover_image: Optional[str] = None


class PlaylistUpdateRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    cover_image: Optional[str] = None


class PlaylistItemCreateRequest(BaseModel):
    asset_id: str
    position: Optional[int] = None


class PlaylistItemUpdateRequest(BaseModel):
    position: int


# ==================== Helper Functions ====================


def _get_asset_title(db, asset: Asset) -> str:
    meta_title = (asset.meta or {}).get("title")
    if meta_title:
        return meta_title
    track = get_subtitle_track_by_asset(db, asset.id, SubtitleTrackType.PROCESSED, is_default=True)
    if track and track.content:
        return track.content.get("title", "")
    return ""


def _get_asset_thumbnail(asset: Asset, base_url: Optional[str] = None) -> Optional[str]:
    if asset.type == AssetType.YOUTUBE:
        return f"https://img.youtube.com/vi/{asset.identifier}/mqdefault.jpg"
    if asset.type == AssetType.UPLOAD and base_url:
        meta = asset.meta or {}
        if meta.get("thumbnail_path"):
            return f"{base_url}/api/assets/{asset.id}/thumbnail"
    return None


def _normalize_playlist_positions(db, items: List[PlaylistAsset]) -> None:
    if not items:
        return
    max_position = max(item.position for item in items)
    offset = max(max_position + len(items) + 1, POSITION_OFFSET_PADDING + len(items))
    for idx, item in enumerate(items):
        item.position = offset + idx
    db.flush()
    for idx, item in enumerate(items):
        item.position = idx


# ==================== Playlist CRUD ====================


@router.get("")
@rate_limit(RateLimitTier.LOW)
async def list_playlists(
    request: Request,
    limit: int = 100,
    offset: int = 0,
):
    with get_session() as db:
        total = db.query(Playlist).count()
        playlist_id_col = cast(Any, PlaylistAsset.playlist_id)
        counts_subquery = (
            db.query(
                playlist_id_col.label("playlist_id"),
                func.count(cast(Any, PlaylistAsset.id)).label("item_count"),
            )
            .group_by(playlist_id_col)
            .subquery()
        )
        playlists = (
            db.query(Playlist, func.coalesce(counts_subquery.c.item_count, 0))
            .outerjoin(counts_subquery, counts_subquery.c.playlist_id == Playlist.id)
            .order_by(desc(cast(Any, Playlist.created_at)))
            .limit(limit)
            .offset(offset)
            .all()
        )
        items = []
        for playlist, item_count in playlists:
            items.append(
                {
                    "id": str(playlist.id),
                    "title": playlist.title,
                    "description": playlist.description,
                    "cover_image": playlist.cover_image,
                    "playlist_type": playlist.playlist_type.value,
                    "owner_type": playlist.owner_type.value,
                    "item_count": int(item_count or 0),
                    "created_at": playlist.created_at.isoformat(),
                    "updated_at": playlist.updated_at.isoformat(),
                }
            )
        return {"items": items, "total": total}


@router.get("/{playlist_id}")
@rate_limit(RateLimitTier.LOW)
async def get_playlist(
    request: Request,
    playlist_id: str,
):
    playlist_uuid = parse_uuid(playlist_id, "playlist ID")

    with get_session() as db:
        playlist = db.get(Playlist, playlist_uuid)
        if not playlist:
            raise HTTPException(status_code=404, detail="Playlist not found")

        items = (
            db.query(PlaylistAsset)
            .filter(as_clause(PlaylistAsset.playlist_id == playlist.id))
            .order_by(cast(Any, PlaylistAsset.position))
            .all()
        )
        return {
            "id": str(playlist.id),
            "title": playlist.title,
            "description": playlist.description,
            "cover_image": playlist.cover_image,
            "playlist_type": playlist.playlist_type.value,
            "owner_type": playlist.owner_type.value,
            "created_at": playlist.created_at.isoformat(),
            "updated_at": playlist.updated_at.isoformat(),
            "items": [
                {
                    "asset_id": str(item.asset_id),
                    "position": item.position,
                    "cached_title": item.cached_title,
                    "cached_thumbnail": item.cached_thumbnail,
                    "added_at": item.added_at.isoformat(),
                }
                for item in items
            ],
        }


@router.post("")
@rate_limit(RateLimitTier.ADMIN)
async def create_playlist(
    request: Request,
    data: PlaylistCreateRequest,
    admin_session: AdminSession = Depends(get_current_admin_session),
):
    title = data.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title is required")

    with get_session() as db:
        playlist = Playlist(
            title=title,
            description=data.description,
            cover_image=data.cover_image,
            playlist_type=PlaylistType.NORMAL,
            owner_type=OwnerType.ADMIN,
        )
        db.add(playlist)
        db.commit()
        db.refresh(playlist)
        return {
            "id": str(playlist.id),
            "title": playlist.title,
            "description": playlist.description,
            "cover_image": playlist.cover_image,
            "playlist_type": playlist.playlist_type.value,
            "owner_type": playlist.owner_type.value,
            "created_at": playlist.created_at.isoformat(),
            "updated_at": playlist.updated_at.isoformat(),
        }


@router.put("/{playlist_id}")
@rate_limit(RateLimitTier.ADMIN)
async def update_playlist(
    request: Request,
    playlist_id: str,
    data: PlaylistUpdateRequest,
    admin_session: AdminSession = Depends(get_current_admin_session),
):
    if data.title is None and data.description is None and data.cover_image is None:
        raise HTTPException(status_code=400, detail="No fields to update")

    if data.title is not None and not data.title.strip():
        raise HTTPException(status_code=400, detail="Title is required")

    playlist_uuid = parse_uuid(playlist_id, "playlist ID")

    with get_session() as db:
        playlist = db.get(Playlist, playlist_uuid)
        if not playlist:
            raise HTTPException(status_code=404, detail="Playlist not found")

        if data.title is not None:
            playlist.title = data.title.strip()
        if data.description is not None:
            playlist.description = data.description
        if data.cover_image is not None:
            playlist.cover_image = data.cover_image

        db.add(playlist)
        db.commit()
        db.refresh(playlist)
        return {
            "id": str(playlist.id),
            "title": playlist.title,
            "description": playlist.description,
            "cover_image": playlist.cover_image,
            "playlist_type": playlist.playlist_type.value,
            "owner_type": playlist.owner_type.value,
            "created_at": playlist.created_at.isoformat(),
            "updated_at": playlist.updated_at.isoformat(),
        }


@router.delete("/{playlist_id}")
@rate_limit(RateLimitTier.ADMIN)
async def delete_playlist(
    request: Request,
    playlist_id: str,
    admin_session: AdminSession = Depends(get_current_admin_session),
):
    playlist_uuid = parse_uuid(playlist_id, "playlist ID")

    with get_session() as db:
        playlist = db.get(Playlist, playlist_uuid)
        if not playlist:
            raise HTTPException(status_code=404, detail="Playlist not found")
        db.delete(playlist)
        db.commit()
        return {"message": "Playlist deleted"}


# ==================== Playlist Items ====================


@router.get("/{playlist_id}/items")
@rate_limit(RateLimitTier.LOW)
async def get_playlist_items(
    request: Request,
    playlist_id: str,
):
    playlist_uuid = parse_uuid(playlist_id, "playlist ID")

    with get_session() as db:
        playlist = db.get(Playlist, playlist_uuid)
        if not playlist:
            raise HTTPException(status_code=404, detail="Playlist not found")
        items = (
            db.query(PlaylistAsset)
            .filter(as_clause(PlaylistAsset.playlist_id == playlist.id))
            .order_by(cast(Any, PlaylistAsset.position))
            .all()
        )
        return {
            "items": [
                {
                    "asset_id": str(item.asset_id),
                    "position": item.position,
                    "cached_title": item.cached_title,
                    "cached_thumbnail": item.cached_thumbnail,
                    "added_at": item.added_at.isoformat(),
                }
                for item in items
            ],
            "total": len(items),
        }


@router.post("/{playlist_id}/items")
@rate_limit(RateLimitTier.ADMIN)
async def add_playlist_item(
    request: Request,
    playlist_id: str,
    data: PlaylistItemCreateRequest,
    admin_session: AdminSession = Depends(get_current_admin_session),
):
    if data.position is not None and data.position < 0:
        raise HTTPException(status_code=400, detail="Position must be >= 0")

    playlist_uuid = parse_uuid(playlist_id, "playlist ID")
    asset_uuid = parse_uuid(data.asset_id, "asset ID")

    with get_session() as db:
        playlist = db.get(Playlist, playlist_uuid)
        if not playlist:
            raise HTTPException(status_code=404, detail="Playlist not found")

        asset = get_asset_by_id(db, asset_uuid)
        if not asset:
            raise HTTPException(status_code=400, detail="Asset not found")
        track = get_subtitle_track_by_asset(
            db, asset.id, SubtitleTrackType.PROCESSED, is_default=True
        )
        if not track:
            raise HTTPException(status_code=400, detail="Asset has no processed subtitles")

        existing = (
            db.query(PlaylistAsset)
            .filter(
                as_clause(PlaylistAsset.playlist_id == playlist.id),
                as_clause(PlaylistAsset.asset_id == asset_uuid),
            )
            .first()
        )
        if existing:
            raise HTTPException(status_code=409, detail="Asset already in playlist")

        items = (
            db.query(PlaylistAsset)
            .filter(as_clause(PlaylistAsset.playlist_id == playlist.id))
            .order_by(cast(Any, PlaylistAsset.position))
            .all()
        )
        insert_position = len(items) if data.position is None else data.position
        if insert_position > len(items):
            insert_position = len(items)

        base_url = str(request.base_url).rstrip("/")
        new_item = PlaylistAsset(
            playlist_id=playlist.id,
            asset_id=asset.id,
            position=len(items) + 1000,
            cached_title=_get_asset_title(db, asset),
            cached_thumbnail=_get_asset_thumbnail(asset, base_url=base_url),
        )
        items.insert(insert_position, new_item)
        db.add(new_item)
        _normalize_playlist_positions(db, items)
        db.commit()
        db.refresh(new_item)
        return {
            "asset_id": str(new_item.asset_id),
            "position": new_item.position,
            "cached_title": new_item.cached_title,
            "cached_thumbnail": new_item.cached_thumbnail,
            "added_at": new_item.added_at.isoformat(),
        }


@router.put("/{playlist_id}/items/{asset_id}")
@rate_limit(RateLimitTier.ADMIN)
async def set_playlist_item_position(
    request: Request,
    playlist_id: str,
    asset_id: str,
    data: PlaylistItemUpdateRequest,
    admin_session: AdminSession = Depends(get_current_admin_session),
):
    if data.position < 0:
        raise HTTPException(status_code=400, detail="Position must be >= 0")

    playlist_uuid = parse_uuid(playlist_id, "playlist ID")
    asset_uuid = parse_uuid(asset_id, "asset ID")

    with get_session() as db:
        playlist = db.get(Playlist, playlist_uuid)
        if not playlist:
            raise HTTPException(status_code=404, detail="Playlist not found")

        items = (
            db.query(PlaylistAsset)
            .filter(as_clause(PlaylistAsset.playlist_id == playlist.id))
            .order_by(cast(Any, PlaylistAsset.position))
            .all()
        )
        target = next((item for item in items if item.asset_id == asset_uuid), None)
        if not target:
            raise HTTPException(status_code=404, detail="Asset not in playlist")

        items.remove(target)
        new_position = data.position
        if new_position >= len(items):
            new_position = len(items)
        items.insert(new_position, target)
        _normalize_playlist_positions(db, items)
        db.commit()
        db.refresh(target)
        return {
            "asset_id": str(target.asset_id),
            "position": target.position,
            "cached_title": target.cached_title,
            "cached_thumbnail": target.cached_thumbnail,
            "added_at": target.added_at.isoformat(),
        }


@router.delete("/{playlist_id}/items/{asset_id}")
@rate_limit(RateLimitTier.ADMIN)
async def delete_playlist_item(
    request: Request,
    playlist_id: str,
    asset_id: str,
    admin_session: AdminSession = Depends(get_current_admin_session),
):
    playlist_uuid = parse_uuid(playlist_id, "playlist ID")
    asset_uuid = parse_uuid(asset_id, "asset ID")

    with get_session() as db:
        playlist = db.get(Playlist, playlist_uuid)
        if not playlist:
            raise HTTPException(status_code=404, detail="Playlist not found")

        items = (
            db.query(PlaylistAsset)
            .filter(as_clause(PlaylistAsset.playlist_id == playlist.id))
            .order_by(cast(Any, PlaylistAsset.position))
            .all()
        )
        target = next((item for item in items if item.asset_id == asset_uuid), None)
        if not target:
            raise HTTPException(status_code=404, detail="Asset not in playlist")

        items.remove(target)
        db.delete(target)
        if items:
            _normalize_playlist_positions(db, items)
        db.commit()
        return {"message": "Playlist item deleted"}


@router.get("/{playlist_id}/context")
@rate_limit(RateLimitTier.LOW)
async def get_playlist_context(
    request: Request,
    playlist_id: str,
    asset_id: str,
):
    playlist_uuid = parse_uuid(playlist_id, "playlist ID")
    asset_uuid = parse_uuid(asset_id, "asset ID")

    with get_session() as db:
        playlist = db.get(Playlist, playlist_uuid)
        if not playlist:
            raise HTTPException(status_code=404, detail="Playlist not found")

        items = (
            db.query(PlaylistAsset)
            .filter(as_clause(PlaylistAsset.playlist_id == playlist.id))
            .order_by(cast(Any, PlaylistAsset.position))
            .all()
        )
        current_item = next((item for item in items if item.asset_id == asset_uuid), None)
        if not current_item:
            raise HTTPException(status_code=404, detail="Asset not in playlist")

        return {
            "playlist_id": str(playlist.id),
            "playlist_title": playlist.title,
            "current_position": current_item.position,
            "items": [
                {
                    "asset_id": str(item.asset_id),
                    "position": item.position,
                    "cached_title": item.cached_title,
                }
                for item in items
            ],
        }
