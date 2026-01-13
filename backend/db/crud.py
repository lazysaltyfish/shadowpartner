from __future__ import annotations

import os
import uuid
from datetime import datetime
from typing import Any, List, Optional, cast

from sqlalchemy import desc
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement

from db.models import Asset, AssetType, SubtitleTrack, SubtitleTrackType, User

# ==================== User CRUD ====================


def _as_clause(value: Any) -> ColumnElement[bool]:
    return cast(ColumnElement[bool], value)


def get_user_by_id(session: Session, user_id: uuid.UUID) -> Optional[User]:
    """Get user by ID."""
    return session.get(User, user_id)


def get_or_create_guest_user(session: Session, ip_address: str) -> User:
    """Get or create a guest user for given IP address.

    For now, we create a new user for each session_id.
    In the future, we could map session_ids to the same user.
    """
    user = User(
        username=f"guest_{ip_address}",
        created_at=datetime.utcnow(),
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


# ==================== Asset CRUD ====================


def get_asset_by_identifier(
    session: Session, asset_type: AssetType, identifier: str
) -> Optional[Asset]:
    """Get asset by type and identifier (for deduplication)."""
    return (
        session.query(Asset)
        .filter(_as_clause(Asset.type == asset_type), _as_clause(Asset.identifier == identifier))
        .first()
    )


# ==================== SubtitleTrack CRUD ====================


def get_subtitle_track_by_asset(
    session: Session, asset_id: uuid.UUID, track_type: SubtitleTrackType
) -> Optional[SubtitleTrack]:
    """Get subtitle track by asset and type."""
    return (
        session.query(SubtitleTrack)
        .filter(
            _as_clause(SubtitleTrack.asset_id == asset_id),
            _as_clause(SubtitleTrack.track_type == track_type),
        )
        .first()
    )


def get_cached_result(session: Session, asset_identifier: str) -> Optional[dict]:
    """Check for cached processing result in database.

    Args:
        session: Database session
        asset_identifier: Asset identifier (YouTube ID or file hash)

    Returns:
        Cached subtitle content dict if exists, None otherwise
    """
    asset = get_asset_by_identifier(session, AssetType.YOUTUBE, asset_identifier)
    if not asset:
        asset = get_asset_by_identifier(session, AssetType.UPLOAD, asset_identifier)

    if not asset:
        return None

    track = get_subtitle_track_by_asset(session, asset.id, SubtitleTrackType.PROCESSED)
    if not track:
        return None

    return track.content


# ==================== Admin CRUD ====================


def get_all_users(session: Session, limit: int = 100, offset: int = 0) -> List[User]:
    """Get all users with pagination.

    Args:
        session: Database session
        limit: Maximum number of users to return
        offset: Number of users to skip

    Returns:
        List of User objects
    """
    return (
        session.query(User)
        .order_by(desc(cast(Any, User.created_at)))
        .limit(limit)
        .offset(offset)
        .all()
    )


def get_user_by_id_with_assets(session: Session, user_id: uuid.UUID) -> Optional[User]:
    """Get user by ID with their assets loaded.

    Args:
        session: Database session
        user_id: User UUID

    Returns:
        User with assets if found, None otherwise
    """
    return (
        session.query(User)
        .options(
            # Eager load assets relationship
        )
        .filter(_as_clause(User.id == user_id))
        .first()
    )


def delete_user(session: Session, user_id: uuid.UUID) -> bool:
    """Delete user and all their associated assets and subtitle tracks.

    Args:
        session: Database session
        user_id: User UUID to delete

    Returns:
        True if user was deleted, False if not found
    """
    user = session.get(User, user_id)
    if not user:
        return False

    # Collect all asset storage paths to delete files
    assets = (
        session.query(Asset)
        .filter(
            _as_clause(Asset.created_by == user_id),
            _as_clause(cast(Any, Asset.storage_path).is_not(None)),
        )
        .all()
    )
    storage_paths = [asset.storage_path for asset in assets if asset.storage_path]

    # Delete user (cascade will handle assets and subtitle_tracks)
    session.delete(user)
    session.commit()

    # Delete storage files
    for storage_path in storage_paths:
        try:
            if os.path.exists(storage_path):
                os.remove(storage_path)
                # Also remove directory if empty
                dir_path = os.path.dirname(storage_path)
                if dir_path and os.path.exists(dir_path) and not os.listdir(dir_path):
                    os.rmdir(dir_path)
        except OSError as e:
            print(f"Warning: Failed to delete storage file {storage_path}: {e}")

    return True


def get_all_assets(session: Session, limit: int = 100, offset: int = 0) -> List[Asset]:
    """Get all assets with pagination and user info.

    Args:
        session: Database session
        limit: Maximum number of assets to return
        offset: Number of assets to skip

    Returns:
        List of Asset objects
    """
    return (
        session.query(Asset)
        .order_by(desc(cast(Any, Asset.created_at)))
        .limit(limit)
        .offset(offset)
        .all()
    )


def get_asset_with_tracks(session: Session, asset_id: uuid.UUID) -> Optional[Asset]:
    """Get asset by ID with subtitle tracks loaded.

    Args:
        session: Database session
        asset_id: Asset UUID

    Returns:
        Asset with subtitle tracks if found, None otherwise
    """
    return session.query(Asset).filter(_as_clause(Asset.id == asset_id)).first()


def delete_asset(session: Session, asset_id: uuid.UUID) -> bool:
    """Delete asset and all associated subtitle tracks and storage files.

    Args:
        session: Database session
        asset_id: Asset UUID to delete

    Returns:
        True if asset was deleted, False if not found
    """
    asset = session.get(Asset, asset_id)
    if not asset:
        return False

    # Collect storage path for file deletion
    storage_path = asset.storage_path

    # Delete asset (cascade will handle subtitle_tracks)
    session.delete(asset)
    session.commit()

    # Delete storage file if it exists
    if storage_path and os.path.exists(storage_path):
        try:
            os.remove(storage_path)
            # Also remove directory if empty
            dir_path = os.path.dirname(storage_path)
            if dir_path and os.path.exists(dir_path) and not os.listdir(dir_path):
                os.rmdir(dir_path)
        except OSError as e:
            print(f"Warning: Failed to delete storage file {storage_path}: {e}")

    return True


def get_all_subtitle_tracks(
    session: Session, limit: int = 100, offset: int = 0
) -> List[SubtitleTrack]:
    """Get all subtitle tracks with pagination.

    Args:
        session: Database session
        limit: Maximum number of tracks to return
        offset: Number of tracks to skip

    Returns:
        List of SubtitleTrack objects
    """
    return (
        session.query(SubtitleTrack)
        .order_by(desc(cast(Any, SubtitleTrack.created_at)))
        .limit(limit)
        .offset(offset)
        .all()
    )


def delete_subtitle_track(session: Session, track_id: uuid.UUID) -> bool:
    """Delete subtitle track.

    Args:
        session: Database session
        track_id: SubtitleTrack UUID to delete

    Returns:
        True if track was deleted, False if not found
    """
    track = session.get(SubtitleTrack, track_id)
    if not track:
        return False

    session.delete(track)
    session.commit()
    return True
