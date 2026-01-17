from sqlalchemy import inspect

from db.models import Asset, Playlist


def test_playlist_relationship_cascade_config():
    asset_cascade = inspect(Asset).relationships["playlist_items"].cascade
    playlist_cascade = inspect(Playlist).relationships["items"].cascade

    assert "delete-orphan" not in asset_cascade
    assert "delete" in asset_cascade
    assert "delete-orphan" in playlist_cascade
