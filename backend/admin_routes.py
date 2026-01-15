from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict

from db import get_session
from db.crud import (
    delete_asset,
    delete_subtitle_track,
    delete_user,
    get_all_assets,
    get_all_subtitle_tracks,
    get_all_users,
)
from models import AdminLoginRequest
from session_manager import (
    AdminSession,
    create_admin_session,
    get_current_admin_session,
    invalidate_admin_session,
    validate_admin_login,
)
from utils.logger import get_logger

router = APIRouter()
logger = get_logger(__name__)


# ==================== Request/Response Models ====================


class AdminLoginResponse(BaseModel):
    session_id: str
    expires_at: int


class UserResponse(BaseModel):
    id: str
    username: Optional[str]
    created_at: str
    assets_count: int

    model_config = ConfigDict(from_attributes=True)


class AssetResponse(BaseModel):
    id: str
    type: str
    identifier: str
    storage_path: Optional[str]
    meta: Optional[dict]
    created_by: Optional[str]
    created_at: str
    subtitle_tracks_count: int

    model_config = ConfigDict(from_attributes=True)


class SubtitleTrackResponse(BaseModel):
    id: str
    asset_id: str
    asset_identifier: str
    asset_type: str
    track_type: str
    source: str
    language: str
    is_default: bool
    created_at: str

    model_config = ConfigDict(from_attributes=True)


# ==================== Admin Authentication ====================


@router.post("/api/admin/login", response_model=AdminLoginResponse)
async def admin_login(request: AdminLoginRequest):
    """Admin login endpoint.

    Validates admin credentials from environment variables and creates an admin session.

    Returns:
        AdminLoginResponse with session_id and expires_at timestamp
    """
    if not validate_admin_login(request):
        raise HTTPException(status_code=401, detail="Invalid admin credentials")

    session = create_admin_session(request.username)
    return AdminLoginResponse(session_id=session.session_id, expires_at=int(session.expires_at))


@router.post("/api/admin/logout")
async def admin_logout(
    session_id: str = Header(..., alias="X-Admin-Session-Id"),
):
    """Admin logout endpoint.

    Invalidates the admin session.

    Args:
        session_id: Admin session ID from X-Admin-Session-Id header

    Returns:
        Success message
    """
    if invalidate_admin_session(session_id):
        return {"message": "Logged out successfully"}
    raise HTTPException(status_code=404, detail="Session not found")


# ==================== User Management ====================


@router.get("/api/admin/users", response_model=List[UserResponse])
async def list_users(
    admin_session: AdminSession = Depends(get_current_admin_session),
    limit: int = 100,
    offset: int = 0,
):
    """List all users.

    Requires admin authentication.

    Args:
        admin_session: Admin session from dependency
        limit: Maximum number of users to return
        offset: Number of users to skip

    Returns:
        List of UserResponse objects
    """
    with get_session() as db:
        users = get_all_users(db, limit=limit, offset=offset)
        result = []
        for user in users:
            user_response = UserResponse(
                id=str(user.id),
                username=user.username,
                created_at=user.created_at.isoformat(),
                assets_count=len(user.assets),
            )
            result.append(user_response)
        return result


@router.delete("/api/admin/users/{user_id}")
async def delete_user_endpoint(
    user_id: str,
    admin_session: AdminSession = Depends(get_current_admin_session),
):
    """Delete a user and all their assets.

    Requires admin authentication.

    Args:
        user_id: User UUID to delete
        admin_session: Admin session from dependency

    Returns:
        Success message

    Raises:
        HTTPException 404 if user not found
    """
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user ID format")

    with get_session() as db:
        if delete_user(db, user_uuid):
            logger.info(f"Admin {admin_session.username} deleted user {user_id}")
            return {"message": f"User {user_id} deleted successfully"}
        raise HTTPException(status_code=404, detail="User not found")


# ==================== Asset Management ====================


@router.get("/api/admin/assets", response_model=List[AssetResponse])
async def list_assets(
    admin_session: AdminSession = Depends(get_current_admin_session),
    limit: int = 100,
    offset: int = 0,
):
    """List all assets.

    Requires admin authentication.

    Args:
        admin_session: Admin session from dependency
        limit: Maximum number of assets to return
        offset: Number of assets to skip

    Returns:
        List of AssetResponse objects
    """
    with get_session() as db:
        assets = get_all_assets(db, limit=limit, offset=offset)
        result = []
        for asset in assets:
            asset_response = AssetResponse(
                id=str(asset.id),
                type=asset.type.value,
                identifier=asset.identifier,
                storage_path=asset.storage_path,
                meta=asset.meta,
                created_by=str(asset.created_by) if asset.created_by else None,
                created_at=asset.created_at.isoformat(),
                subtitle_tracks_count=len(asset.subtitle_tracks),
            )
            result.append(asset_response)
        return result


@router.delete("/api/admin/assets/{asset_id}")
async def delete_asset_endpoint(
    asset_id: str,
    admin_session: AdminSession = Depends(get_current_admin_session),
):
    """Delete an asset and all its subtitle tracks.

    Requires admin authentication.

    Args:
        asset_id: Asset UUID to delete
        admin_session: Admin session from dependency

    Returns:
        Success message

    Raises:
        HTTPException 404 if asset not found
    """
    try:
        asset_uuid = uuid.UUID(asset_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid asset ID format")

    with get_session() as db:
        if delete_asset(db, asset_uuid):
            logger.info(f"Admin {admin_session.username} deleted asset {asset_id}")
            return {"message": f"Asset {asset_id} deleted successfully"}
        raise HTTPException(status_code=404, detail="Asset not found")


# ==================== Subtitle Track Management ====================


@router.get("/api/admin/subtitle-tracks", response_model=List[SubtitleTrackResponse])
async def list_subtitle_tracks(
    admin_session: AdminSession = Depends(get_current_admin_session),
    limit: int = 100,
    offset: int = 0,
):
    """List all subtitle tracks.

    Requires admin authentication.

    Args:
        admin_session: Admin session from dependency
        limit: Maximum number of tracks to return
        offset: Number of tracks to skip

    Returns:
        List of SubtitleTrackResponse objects
    """
    with get_session() as db:
        tracks = get_all_subtitle_tracks(db, limit=limit, offset=offset)
        result = []
        for track in tracks:
            track_response = SubtitleTrackResponse(
                id=str(track.id),
                asset_id=str(track.asset_id),
                asset_identifier=track.asset.identifier if track.asset else "",
                asset_type=track.asset.type.value if track.asset else "",
                track_type=track.track_type.value,
                source=track.source.value,
                language=track.language,
                is_default=track.is_default,
                created_at=track.created_at.isoformat(),
            )
            result.append(track_response)
        return result


@router.delete("/api/admin/subtitle-tracks/{track_id}")
async def delete_subtitle_track_endpoint(
    track_id: str,
    admin_session: AdminSession = Depends(get_current_admin_session),
):
    """Delete a subtitle track.

    Requires admin authentication.

    Args:
        track_id: SubtitleTrack UUID to delete
        admin_session: Admin session from dependency

    Returns:
        Success message

    Raises:
        HTTPException 404 if track not found
    """
    try:
        track_uuid = uuid.UUID(track_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid track ID format")

    with get_session() as db:
        if delete_subtitle_track(db, track_uuid):
            logger.info(f"Admin {admin_session.username} deleted subtitle track {track_id}")
            return {"message": f"Subtitle track {track_id} deleted successfully"}
        raise HTTPException(status_code=404, detail="Subtitle track not found")
