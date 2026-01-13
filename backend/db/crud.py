from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional, cast

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
        is_admin=False,
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
