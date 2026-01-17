from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from db.models import OwnerType, Playlist, PlaylistAsset, PlaylistType


def test_create_playlist(db_session):
    playlist = Playlist(
        title="Japanese Basics",
        description="Beginner lessons",
        playlist_type=PlaylistType.NORMAL,
        owner_type=OwnerType.ADMIN,
    )
    db_session.add(playlist)
    db_session.commit()
    db_session.refresh(playlist)

    assert playlist.id is not None
    assert playlist.title == "Japanese Basics"
    assert playlist.description == "Beginner lessons"
    assert playlist.playlist_type == PlaylistType.NORMAL
    assert playlist.owner_type == OwnerType.ADMIN


def test_update_playlist(test_playlist, db_session):
    test_playlist.title = "Updated Title"
    test_playlist.description = "Updated description"
    test_playlist.cover_image = "https://example.com/cover.jpg"
    db_session.commit()
    db_session.refresh(test_playlist)

    assert test_playlist.title == "Updated Title"
    assert test_playlist.description == "Updated description"
    assert test_playlist.cover_image == "https://example.com/cover.jpg"


def test_delete_playlist_cascades_items(test_playlist_with_items, db_session):
    playlist_id = test_playlist_with_items.id
    items_count = (
        db_session.query(PlaylistAsset).filter(PlaylistAsset.playlist_id == playlist_id).count()
    )
    assert items_count > 0

    db_session.delete(test_playlist_with_items)
    db_session.commit()

    items_count = (
        db_session.query(PlaylistAsset).filter(PlaylistAsset.playlist_id == playlist_id).count()
    )
    assert items_count == 0


def test_add_asset_to_playlist(test_playlist, test_assets, db_session):
    item = PlaylistAsset(
        playlist_id=test_playlist.id,
        asset_id=test_assets[0],
        position=0,
        cached_title="First Video",
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)

    assert item.id is not None
    assert item.position == 0
    assert item.cached_title == "First Video"


def test_add_duplicate_asset_fails(test_playlist, test_assets, db_session):
    item1 = PlaylistAsset(
        playlist_id=test_playlist.id,
        asset_id=test_assets[0],
        position=0,
        cached_title="First",
    )
    item2 = PlaylistAsset(
        playlist_id=test_playlist.id,
        asset_id=test_assets[0],
        position=1,
        cached_title="Duplicate",
    )
    db_session.add(item1)
    db_session.add(item2)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_duplicate_position_fails(test_playlist, test_assets, db_session):
    item1 = PlaylistAsset(
        playlist_id=test_playlist.id,
        asset_id=test_assets[0],
        position=0,
        cached_title="First",
    )
    item2 = PlaylistAsset(
        playlist_id=test_playlist.id,
        asset_id=test_assets[1],
        position=0,
        cached_title="Second",
    )
    db_session.add(item1)
    db_session.add(item2)
    with pytest.raises(IntegrityError):
        db_session.commit()
