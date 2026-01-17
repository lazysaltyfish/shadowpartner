"""Pytest configuration for test database isolation.

This module ensures tests use a separate test database instead of the production database.
"""

from __future__ import annotations

import os
import tempfile
import uuid

_test_db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_test_db_path = _test_db_file.name
_test_db_file.close()

os.environ["DATABASE_URL"] = f"sqlite:///{_test_db_path}"

import atexit  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402


def _cleanup_test_db():
    try:
        os.unlink(_test_db_path)
    except OSError:
        pass


atexit.register(_cleanup_test_db)


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """Set up test database engine and session factory."""
    from db.engine import engine
    from db.models import Asset, Playlist, PlaylistAsset, SubtitleTrack, User  # noqa: F401

    SQLModel.metadata.create_all(engine)

    yield engine


@pytest.fixture(scope="function", autouse=True)
def clean_database(setup_test_database):
    """Clean database tables after each test function."""
    test_engine = setup_test_database

    yield

    with test_engine.connect() as conn:
        conn.execute(text("DELETE FROM playlist_asset"))
        conn.execute(text("DELETE FROM playlist"))
        conn.execute(text("DELETE FROM subtitle_track"))
        conn.execute(text("DELETE FROM asset"))
        conn.execute(text("DELETE FROM user"))
        conn.commit()


@pytest.fixture(scope="function")
def db_session():
    """Create a database session for tests that need direct DB access."""
    from db.engine import SessionLocal

    session = SessionLocal()
    try:
        yield session
        session.rollback()
    finally:
        session.close()


@pytest.fixture
def test_user(db_session):
    """Create a test user for playlist fixtures."""
    from db.models import User

    unique_suffix = str(uuid.uuid4())[:8]
    user = User(username=f"test_user_{unique_suffix}")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user.id


@pytest.fixture
def test_assets(db_session, test_user):
    """Create assets with processed default subtitles for playlist tests."""
    from db.models import Asset, AssetType, SubtitleSource, SubtitleTrack, SubtitleTrackType

    asset_ids = []
    for idx in range(3):
        asset = Asset(
            type=AssetType.UPLOAD,
            identifier=f"test_asset_{uuid.uuid4().hex[:8]}_{idx}",
            storage_path=f"/tmp/test_asset_{idx}.mp4",
            created_by=test_user,
            meta={"title": f"Test Video {idx + 1}"},
        )
        db_session.add(asset)
        db_session.flush()
        track = SubtitleTrack(
            asset_id=asset.id,
            track_type=SubtitleTrackType.PROCESSED,
            source=SubtitleSource.AI_GENERATED,
            language="ja",
            content={"title": f"Track Title {idx + 1}"},
            is_default=True,
        )
        db_session.add(track)
        asset_ids.append(asset.id)
    db_session.commit()
    return asset_ids


@pytest.fixture
def test_playlist(db_session):
    """Create a basic playlist for tests."""
    from db.models import OwnerType, Playlist, PlaylistType

    playlist = Playlist(
        title="Test Playlist",
        description="Test description",
        playlist_type=PlaylistType.NORMAL,
        owner_type=OwnerType.ADMIN,
    )
    db_session.add(playlist)
    db_session.commit()
    db_session.refresh(playlist)
    return playlist


@pytest.fixture
def test_playlist_with_items(db_session, test_playlist, test_assets):
    """Create a playlist with items for tests."""
    from db.models import PlaylistAsset

    for idx, asset_id in enumerate(test_assets):
        item = PlaylistAsset(
            playlist_id=test_playlist.id,
            asset_id=asset_id,
            position=idx,
            cached_title=f"Video {idx + 1}",
            cached_thumbnail=None,
        )
        db_session.add(item)
    db_session.commit()
    db_session.refresh(test_playlist)
    return test_playlist
