"""Unit tests for the database cleanup script.

Tests for orphan detection and cleanup functions in cleanup_database.py
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from db.engine import SessionLocal
from db.models import Asset, AssetType, SubtitleSource, SubtitleTrack, SubtitleTrackType, User
from scripts.cleanup_database import (
    cleanup_orphaned_assets,
    cleanup_orphaned_files,
    cleanup_orphaned_tracks,
    cleanup_orphaned_users,
    detect_orphaned_assets,
    detect_orphaned_files,
    detect_orphaned_subtitle_tracks,
    detect_orphaned_users,
)
from services_registry import init_services
from settings import get_settings

settings = get_settings()


@pytest.fixture(scope="session", autouse=True)
def initialize_storage():
    """Initialize storage service for all tests."""
    init_services()
    yield


@pytest.fixture(scope="function")
def db_session():
    """Create a fresh database session for each test."""
    session = SessionLocal()
    try:
        yield session
        session.rollback()
    finally:
        session.close()


@pytest.fixture
def cleanup_test_data(db_session: SessionLocal):
    """Create test data for cleanup script testing.

    Creates:
    - A normal user with 1 asset and 1 subtitle track (valid data)
    - An orphaned subtitle track (asset doesn't exist)
    - An orphaned user (no assets)
    - An orphaned asset (storage file will be missing)
    """
    # Create a normal user
    unique_suffix = str(uuid.uuid4())[:8]
    user = User(username=f"test_cleanup_user_{unique_suffix}")
    db_session.add(user)
    db_session.flush()

    # Create a normal asset with a subtitle track
    asset = Asset(
        type=AssetType.YOUTUBE,
        identifier=f"youtube_test_{unique_suffix}",
        storage_path=None,  # YouTube assets have no storage path
        created_by=user.id,
    )
    db_session.add(asset)
    db_session.flush()

    track = SubtitleTrack(
        asset_id=asset.id,
        track_type=SubtitleTrackType.PROCESSED,
        source=SubtitleSource.AI_GENERATED,
        language="ja",
        content={"test": "data"},
    )
    db_session.add(track)

    # Create an orphaned subtitle track (references non-existent asset)
    fake_asset_id = uuid.uuid4()
    orphaned_track = SubtitleTrack(
        asset_id=fake_asset_id,
        track_type=SubtitleTrackType.PROCESSED,
        source=SubtitleSource.AI_GENERATED,
        language="ja",
        content={"orphaned": "track"},
    )
    db_session.add(orphaned_track)

    # Create an orphaned user (no assets)
    orphaned_user = User(username=f"orphaned_user_{unique_suffix}")
    # Set created_at to old date for age threshold testing
    orphaned_user.created_at = datetime.utcnow() - timedelta(days=60)
    db_session.add(orphaned_user)

    # Create an orphaned asset (storage path set but file doesn't exist)
    orphaned_asset = Asset(
        type=AssetType.UPLOAD,
        identifier=f"upload_orphaned_{unique_suffix}",
        storage_path="upload_nonexistent_file_xyz",  # File doesn't exist
        created_by=user.id,
    )
    db_session.add(orphaned_asset)

    db_session.commit()

    return {
        "user_id": user.id,
        "asset_id": asset.id,
        "track_id": track.id,
        "orphaned_track_id": orphaned_track.id,
        "orphaned_user_id": orphaned_user.id,
        "orphaned_asset_id": orphaned_asset.id,
    }


# ==================== Orphaned SubtitleTrack Tests ====================


def test_detect_orphaned_subtitle_tracks_finds_orphans(
    db_session: SessionLocal, cleanup_test_data: dict
):
    """Test detection of orphaned subtitle tracks."""
    orphaned_tracks = detect_orphaned_subtitle_tracks(db_session)

    assert len(orphaned_tracks) == 1
    assert orphaned_tracks[0].id == cleanup_test_data["orphaned_track_id"]


def test_detect_orphaned_subtitle_tracks_excludes_valid(
    db_session: SessionLocal, cleanup_test_data: dict
):
    """Test that valid subtitle tracks are not detected as orphans."""
    orphaned_tracks = detect_orphaned_subtitle_tracks(db_session)

    # Should not include the valid track
    orphaned_ids = {t.id for t in orphaned_tracks}
    assert cleanup_test_data["track_id"] not in orphaned_ids


def test_cleanup_orphaned_tracks_dry_run(db_session: SessionLocal, cleanup_test_data: dict):
    """Test cleanup of orphaned tracks in dry-run mode."""
    orphaned_tracks = detect_orphaned_subtitle_tracks(db_session)
    initial_count = len(orphaned_tracks)

    # Dry run should not delete
    count = cleanup_orphaned_tracks(db_session, orphaned_tracks, dry_run=True)

    assert count == initial_count

    # Verify track still exists
    db_session.rollback()
    remaining_orphaned = detect_orphaned_subtitle_tracks(db_session)
    assert len(remaining_orphaned) == initial_count


def test_cleanup_orphaned_tracks_force(db_session: SessionLocal, cleanup_test_data: dict):
    """Test cleanup of orphaned tracks in force mode."""
    orphaned_tracks = detect_orphaned_subtitle_tracks(db_session)
    initial_count = len(orphaned_tracks)

    # Force delete
    count = cleanup_orphaned_tracks(db_session, orphaned_tracks, dry_run=False)

    assert count == initial_count

    # Verify track is deleted
    db_session.rollback()
    remaining_orphaned = detect_orphaned_subtitle_tracks(db_session)
    assert len(remaining_orphaned) == 0


# ==================== Orphaned Asset Tests ====================


@pytest.mark.asyncio
async def test_detect_orphaned_assets_finds_missing_files(
    db_session: SessionLocal, cleanup_test_data: dict
):
    """Test detection of assets with missing storage files."""
    orphaned_assets = await detect_orphaned_assets(db_session)

    assert len(orphaned_assets) == 1
    assert orphaned_assets[0].id == cleanup_test_data["orphaned_asset_id"]


@pytest.mark.asyncio
async def test_detect_orphaned_assets_excludes_youtube(
    db_session: SessionLocal, cleanup_test_data: dict
):
    """Test that YouTube assets (no storage file) are not detected as orphans."""
    orphaned_assets = await detect_orphaned_assets(db_session)

    # Should not include the YouTube asset
    orphaned_ids = {a.id for a in orphaned_assets}
    assert cleanup_test_data["asset_id"] not in orphaned_ids


@pytest.mark.asyncio
async def test_cleanup_orphaned_assets_dry_run(db_session: SessionLocal, cleanup_test_data: dict):
    """Test cleanup of orphaned assets in dry-run mode."""
    orphaned_assets = await detect_orphaned_assets(db_session)
    initial_count = len(orphaned_assets)

    # Dry run should not delete
    count = cleanup_orphaned_assets(db_session, orphaned_assets, dry_run=True)

    assert count == initial_count

    # Verify asset still exists
    db_session.rollback()
    remaining_orphaned = await detect_orphaned_assets(db_session)
    assert len(remaining_orphaned) == initial_count


@pytest.mark.asyncio
async def test_cleanup_orphaned_assets_force(db_session: SessionLocal, cleanup_test_data: dict):
    """Test cleanup of orphaned assets in force mode."""
    orphaned_assets = await detect_orphaned_assets(db_session)
    initial_count = len(orphaned_assets)

    # Force delete
    count = cleanup_orphaned_assets(db_session, orphaned_assets, dry_run=False)

    assert count == initial_count

    # Verify asset is deleted
    db_session.rollback()
    remaining_orphaned = await detect_orphaned_assets(db_session)
    assert len(remaining_orphaned) == 0


# ==================== Orphaned User Tests ====================


def test_detect_orphaned_users_finds_orphans(db_session: SessionLocal, cleanup_test_data: dict):
    """Test detection of orphaned users."""
    orphaned_users = detect_orphaned_users(db_session, age_threshold_days=30)

    assert len(orphaned_users) == 1
    assert orphaned_users[0].id == cleanup_test_data["orphaned_user_id"]


def test_detect_orphaned_users_with_age_threshold(
    db_session: SessionLocal, cleanup_test_data: dict
):
    """Test age threshold filtering for orphaned users."""
    # Orphaned user is 60 days old, should be found with 30-day threshold
    orphaned_users = detect_orphaned_users(db_session, age_threshold_days=30)
    assert len(orphaned_users) == 1

    # Should not be found with 90-day threshold
    orphaned_users = detect_orphaned_users(db_session, age_threshold_days=90)
    assert len(orphaned_users) == 0

    # Should be found with 0-day threshold (no age filtering)
    orphaned_users = detect_orphaned_users(db_session, age_threshold_days=0)
    assert len(orphaned_users) == 1


def test_detect_orphaned_users_excludes_valid(db_session: SessionLocal, cleanup_test_data: dict):
    """Test that users with assets are not detected as orphans."""
    orphaned_users = detect_orphaned_users(db_session, age_threshold_days=0)

    # Should not include the normal user who has assets
    orphaned_ids = {u.id for u in orphaned_users}
    assert cleanup_test_data["user_id"] not in orphaned_ids


def test_cleanup_orphaned_users_dry_run(db_session: SessionLocal, cleanup_test_data: dict):
    """Test cleanup of orphaned users in dry-run mode."""
    orphaned_users = detect_orphaned_users(db_session, age_threshold_days=30)
    initial_count = len(orphaned_users)

    # Dry run should not delete
    count = cleanup_orphaned_users(db_session, orphaned_users, dry_run=True)

    assert count == initial_count

    # Verify user still exists
    db_session.rollback()
    remaining_orphaned = detect_orphaned_users(db_session, age_threshold_days=30)
    assert len(remaining_orphaned) == initial_count


def test_cleanup_orphaned_users_force(db_session: SessionLocal, cleanup_test_data: dict):
    """Test cleanup of orphaned users in force mode."""
    orphaned_users = detect_orphaned_users(db_session, age_threshold_days=30)
    initial_count = len(orphaned_users)

    # Force delete
    count = cleanup_orphaned_users(db_session, orphaned_users, dry_run=False)

    assert count == initial_count

    # Verify user is deleted
    db_session.rollback()
    remaining_orphaned = detect_orphaned_users(db_session, age_threshold_days=30)
    assert len(remaining_orphaned) == 0


# ==================== Orphaned File Tests ====================


@pytest.mark.asyncio
async def test_detect_orphaned_files_returns_list(db_session: SessionLocal):
    """Test that orphaned file detection returns a list."""
    # Even with no orphaned files, should return an empty list
    orphaned_files = await detect_orphaned_files(db_session)

    assert isinstance(orphaned_files, list)


@pytest.mark.asyncio
async def test_cleanup_orphaned_files_dry_run(db_session: SessionLocal):
    """Test cleanup of orphaned files in dry-run mode."""
    test_files = ["upload_test_file_1", "upload_test_file_2"]

    # Dry run should not delete
    count = await cleanup_orphaned_files(db_session, test_files, dry_run=True)

    assert count == len(test_files)


# ==================== Edge Cases ====================


def test_empty_database(db_session: SessionLocal):
    """Test cleanup functions with empty database."""
    # All detection functions should return empty lists
    orphaned_tracks = detect_orphaned_subtitle_tracks(db_session)
    orphaned_users = detect_orphaned_users(db_session, age_threshold_days=0)

    assert len(orphaned_tracks) == 0
    assert len(orphaned_users) == 0


def test_cleanup_with_empty_lists(db_session: SessionLocal):
    """Test cleanup functions with empty lists."""
    # All cleanup functions should handle empty lists gracefully
    count_tracks = cleanup_orphaned_tracks(db_session, [], dry_run=False)
    count_users = cleanup_orphaned_users(db_session, [], dry_run=False)

    assert count_tracks == 0
    assert count_users == 0
