# Playlist Feature Design Document

## 1. Overview

### 1.1 Purpose
Add playlist functionality to ShadowPartner, allowing administrators to create curated video collections and enabling users to browse and play through these collections.

### 1.2 Scope (Phase 1)
- Admin-created playlists with metadata (title, description, cover)
- Playlist management via admin panel (CRUD operations)
- Playlist sidebar on play page when accessed via playlist context
- Search and add existing assets to playlists
- Reorder playlist items via up/down buttons

### 1.3 Out of Scope (Future Phases)
- User-created playlists
- User favorites (playlist_type: `favorites`)
- Watch history (playlist_type: `history`)
- Playlist sharing/permissions
- Playlist collaboration

---

## 2. Data Model

### 2.1 Schema Changes

```python
# New tables to be added

class PlaylistType(str, Enum):
    NORMAL = "normal"          # Admin-created playlists
    FAVORITES = "favorites"    # User favorites (reserved for future)
    HISTORY = "history"        # Watch history (reserved for future)

class OwnerType(str, Enum):
    ADMIN = "admin"            # Created by admin
    USER = "user"              # Created by user (reserved for favorites/history)

class Playlist(Base):
    __tablename__ = "playlists"

    id: UUID = Column(UUID, primary_key=True, default=uuid4)
    title: str = Column(String(255), nullable=False)
    description: Optional[str] = Column(Text, nullable=True)
    cover_image: Optional[str] = Column(String(512), nullable=True)

    playlist_type: PlaylistType = Column(
        Enum(PlaylistType),
        default=PlaylistType.NORMAL,
        nullable=False
    )
    owner_type: OwnerType = Column(
        Enum(OwnerType),
        default=OwnerType.ADMIN,
        nullable=False
    )
    owner_id: Optional[UUID] = Column(UUID, nullable=True)  # Reserved for user playlists

    created_at: datetime = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: datetime = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False
    )

    # Relationships
    items: relationship["PlaylistAsset"] = back_populates="playlist")


class PlaylistAsset(Base):
    __tablename__ = "playlist_assets"

    id: UUID = Column(UUID, primary_key=True, default=uuid4)
    playlist_id: UUID = Column(UUID, ForeignKey("playlists.id", ondelete="CASCADE"), nullable=False)
    asset_id: UUID = Column(UUID, ForeignKey("assets.id", ondelete="CASCADE"), nullable=False)

    position: int = Column(Integer, nullable=False, default=0)

    # Cached asset info to avoid frequent JOINs
    cached_title: str = Column(String(512), nullable=False)
    cached_thumbnail: Optional[str] = Column(String(512), nullable=True)

    added_at: datetime = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    playlist: relationship["Playlist"] = back_populates="items")
    asset: relationship["Asset"]

    # Constraints
    __table_args__ = (
        UniqueConstraint("playlist_id", "asset_id", name="uq_playlist_asset"),
        UniqueConstraint("playlist_id", "position", name="uq_playlist_position"),
        Index("ix_playlist_assets_position", "playlist_id", "position"),
    )
```

### 2.2 Design Decisions

| Decision | Rationale |
|----------|-----------|
| Separate `PlaylistAsset` table | Supports ordered lists and allows many-to-many relationship |
| `position` field | Enables custom ordering (not just chronological) |
| Cached fields (`cached_title`, `cached_thumbnail`) | Faster list rendering, resilience to asset deletion |
| `playlist_type` enum | Extensible for future favorites/history features |
| `owner_type` enum | Distinguishes admin/system/user created playlists |
| CASCADE delete | Automatically removes playlist items when playlist or asset is deleted |
| Unique constraints | Prevents duplicate assets and position conflicts |

---

## 3. API Design

### 3.1 Authentication
All playlist endpoints require admin session:
```
Header: X-Admin-Session-Id: <session_id>
```

### 3.2 Endpoints

#### 3.2.1 Playlist CRUD

```
GET    /api/playlists
        Query params: none
        Response: {
          "items": [{ id, title, description, cover_image, playlist_type,
                     owner_type, item_count, created_at, updated_at }],
          "total": int
        }

GET    /api/playlists/{playlist_id}
        Response: {
          id, title, description, cover_image, playlist_type, owner_type,
          created_at, updated_at,
          items: [{ asset_id, position, cached_title, added_at }]
        }

POST   /api/playlists
        Body: { "title": str, "description"?: str, "cover_image"?: str }
        Response: { id, title, description, cover_image, ... }
        Error 400: Validation error

PUT    /api/playlists/{playlist_id}
        Body: { "title"?: str, "description"?: str, "cover_image"?: str }
        Response: { id, title, description, cover_image, ... }
        Error 404: Playlist not found

DELETE /api/playlists/{playlist_id}
        Response: 204 No Content
        Error 404: Playlist not found
```

#### 3.2.2 Playlist Items

```
GET    /api/playlists/{playlist_id}/items
        Query params: none
        Response: {
          "items": [{ asset_id, position, cached_title, cached_thumbnail, added_at }],
          "total": int
        }

POST   /api/playlists/{playlist_id}/items
        Body: { "asset_id": UUID, "position"?: int }
        Response: { asset_id, position, cached_title, cached_thumbnail, added_at }
        Error 400: Asset not found
        Error 409: Asset already in playlist ("Asset already in playlist")
        Error 404: Playlist not found
        Note: position defaults to end of list if not specified

PUT    /api/playlists/{playlist_id}/items/{asset_id}
        Body: { "position": int }
        Response: { asset_id, position, cached_title, cached_thumbnail, added_at }
        Error 404: Playlist or asset not found in playlist
        Note: Idempotent - using insertion mode, shifts other items

DELETE /api/playlists/{playlist_id}/items/{asset_id}
        Response: 204 No Content
        Error 404: Playlist or asset not found in playlist
        Note: Shifts remaining items to fill the gap
```

#### 3.2.3 Asset Search (for Adding)

```
GET    /api/assets/search
        Query params: q={search_term}
        Response: {
          "items": [{ id, title, thumbnail, type }],
          "total": int
        }
        Note: Searches in asset.meta.title and asset.identifier
```

#### 3.2.4 Playlist Context (for Play Page)

```
GET    /api/playlists/{playlist_id}/context?asset_id={asset_id}
        Response: {
          "playlist_id": UUID,
          "playlist_title": str,
          "current_position": int,
          "items": [
            { asset_id, position, cached_title },
            ...
          ]
        }
        Error 404: Playlist or asset not found in playlist
```

### 3.3 Error Response Format

```json
{
  "error": {
    "code": "ASSET_ALREADY_IN_PLAYLIST",
    "message": "Asset already in playlist"
  }
}
```

---

## 4. Frontend Changes

### 4.1 Router Modifications

```javascript
// Current: /play/{asset_id}
// Extended: /play/{asset_id}?playlist_id={xxx}

// Parse playlist_id from query params
const params = new URLSearchParams(window.location.hash.split('?')[1]);
const playlistId = params.get('playlist_id');
```

### 4.2 Play Page Layout

When `playlist_id` is present:

```
┌─────────────────────────┬─────────────────────────────┐
│                         │  ▶ 日语入门                   │
│                         │  ─────────────────────────   │
│                         │  ◉ 第1课 - 问候              │
│   Video Player          │    第2课 - 自我介绍          │
│   (16:9 aspect)         │    第3课 - 数字与时间        │
│                         │    第4课 - 购物              │
│   Subtitles             │    第5课 - 问路              │
│   (scrollable)          │    ...                       │
│                         │                              │
└─────────────────────────┴─────────────────────────────┘
```

When no `playlist_id`: (current layout, no sidebar)

### 4.3 New Vue State (app.js)

```javascript
// Add to setup()
const playlistContext = ref(null);  // { playlist_id, playlist_title, items, current_position }

// Load playlist context when present
const loadPlaylistContext = async (playlistId, assetId) => {
    const data = await API.getPlaylistContext(playlistId, assetId);
    playlistContext.value = data;
};

// Navigate within playlist
const playNextInPlaylist = () => {
    const ctx = playlistContext.value;
    const nextPos = ctx.current_position + 1;
    if (nextPos < ctx.items.length) {
        const nextAssetId = ctx.items[nextPos].asset_id;
        Router.goToPlay(nextAssetId, { playlist_id: ctx.playlist_id });
    }
};

const playPrevInPlaylist = () => {
    const ctx = playlistContext.value;
    const prevPos = ctx.current_position - 1;
    if (prevPos >= 0) {
        const prevAssetId = ctx.items[prevPos].asset_id;
        Router.goToPlay(prevAssetId, { playlist_id: ctx.playlist_id });
    }
};
```

### 4.4 API Client Extensions (api.js)

```javascript
const API = {
    // ... existing methods ...

    // Playlist CRUD
    getPlaylists: () => fetchWithAuth(`${baseUrl}/playlists`),
    getPlaylist: (id) => fetchWithAuth(`${baseUrl}/playlists/${id}`),
    createPlaylist: (data) => fetchWithAuth(`${baseUrl}/playlists`, {
        method: 'POST',
        body: JSON.stringify(data)
    }),
    updatePlaylist: (id, data) => fetchWithAuth(`${baseUrl}/playlists/${id}`, {
        method: 'PUT',
        body: JSON.stringify(data)
    }),
    deletePlaylist: (id) => fetchWithAuth(`${baseUrl}/playlists/${id}`, {
        method: 'DELETE'
    }),

    // Playlist items
    getPlaylistItems: (playlistId) => fetchWithAuth(`${baseUrl}/playlists/${playlistId}/items`),
    addPlaylistItem: (playlistId, assetId, position) => fetchWithAuth(`${baseUrl}/playlists/${playlistId}/items`, {
        method: 'POST',
        body: JSON.stringify({ asset_id: assetId, position })
    }),
    setPlaylistItemPosition: (playlistId, assetId, position) => fetchWithAuth(`${baseUrl}/playlists/${playlistId}/items/${assetId}`, {
        method: 'PUT',
        body: JSON.stringify({ position })
    }),
    removePlaylistItem: (playlistId, assetId) => fetchWithAuth(`${baseUrl}/playlists/${playlistId}/items/${assetId}`, {
        method: 'DELETE'
    }),

    // Context for play page
    getPlaylistContext: (playlistId, assetId) => fetchWithAuth(`${baseUrl}/playlists/${playlistId}/context?asset_id=${assetId}`),

    // Search (for adding assets)
    searchAssets: (query) => fetchWithAuth(`${baseUrl}/assets/search?q=${encodeURIComponent(query)}`),
};
```

---

## 5. Admin Panel Changes

### 5.1 New Tab

```
[Users] [Assets] [Subtitle Tracks] [Playlists]
```

### 5.2 Playlist Management UI

```
┌────────────────────────────────────────────────────────────────┐
│  Playlists                                    [+ New Playlist]  │
├────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ 日语入门                              [Edit] [Delete]      │  │
│  │ 初级日语课程，包含基础问候和日常对话                      │  │
│  │ 5 videos • Created 2024-01-15                            │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ N2 语法精讲                            [Edit] [Delete]     │  │
│  │ JLPT N2 语法点详细讲解                                    │  │
│  │ 12 videos • Created 2024-01-10                           │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────┘
```

### 5.3 Create/Edit Playlist Modal

```
┌─────────────────────────────────────┐
│  Create/Edit Playlist               │
├─────────────────────────────────────┤
│                                     │
│  Title: [_________________________] │
│                                     │
│  Description:                       │
│  [_________________________________]│
│  [_________________________________]│
│                                     │
│  ☐ Upload custom cover image       │
│    [Browse...]                      │
│                                     │
│  [Cancel]              [Save]       │
└─────────────────────────────────────┘
```

### 5.4 Playlist Item Management

```
┌────────────────────────────────────────────────────────────────┐
│  Playlist: 日语入门                              [← Back]      │
├────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Videos                                          [+ Add Video]  │
│  ────────────────────────────────────────────────────────────  │
│                                                                 │
│  1. 第1课 - 问候                    [↑] [↓] [Remove]           │
│  2. 第2课 - 自我介绍                  [↑] [↓] [Remove]        │
│  3. 第3课 - 数字与时间                [↑] [↓] [Remove]        │
│  4. 第4课 - 购物                      [↑] [↓] [Remove]        │
│  5. 第5课 - 问路                      [↑] [↓] [Remove]        │
│                                                                 │
│  [+ Add Video] shows search modal:                               │
│  ┌─────────────────────────────────────┐                        │
│  │ Search: [______________]            │                        │
│  │                                     │                        │
│  │ ◉ 第6课 - 天气        [+ Add]       │                        │
│  │   第7课 - 交通        [+ Add]       │                        │
│  └─────────────────────────────────────┘                        │
└────────────────────────────────────────────────────────────────┘
```

---

## 6. Database Migration

```sql
-- Migration: add_playlist_tables
-- Date: 2025-01-16

CREATE TYPE playlist_type AS ENUM ('normal', 'favorites', 'history');
CREATE TYPE owner_type AS ENUM ('admin', 'user');

CREATE TABLE playlists (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(255) NOT NULL,
    description TEXT,
    cover_image VARCHAR(512),
    playlist_type playlist_type NOT NULL DEFAULT 'normal',
    owner_type owner_type NOT NULL DEFAULT 'admin',
    owner_id UUID,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE playlist_assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    playlist_id UUID NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    asset_id UUID NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    position INTEGER NOT NULL DEFAULT 0,
    cached_title VARCHAR(512) NOT NULL,
    cached_thumbnail VARCHAR(512),
    added_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (playlist_id, asset_id),
    UNIQUE (playlist_id, position)
);

CREATE INDEX ix_playlist_assets_position ON playlist_assets(playlist_id, position);
CREATE INDEX ix_playlists_owner ON playlists(owner_type, owner_id);
```

---

## 7. Test Design

### 7.1 Backend Tests (pytest)

#### 7.1.1 Test File Structure
```
backend/tests/
├── conftest.py                    # Existing fixtures
├── test_playlist_crud.py          # CRUD layer tests
└── test_playlist_api.py           # API layer tests
```

#### 7.1.2 Fixtures (conftest.py extensions)

```python
# Add to conftest.py
@pytest.fixture
def test_playlist(db_session):
    """Create a test playlist with admin owner."""
    from db.models import Playlist, PlaylistType, OwnerType
    playlist = Playlist(
        title="Test Playlist",
        description="Test description",
        playlist_type=PlaylistType.NORMAL,
        owner_type=OwnerType.ADMIN,
    )
    db_session.add(playlist)
    db_session.commit()
    db_session.refresh(playlist)
    yield playlist
    # Cleanup handled by clean_database fixture


@pytest.fixture
def test_playlist_with_items(test_playlist, test_assets):
    """Create a playlist with multiple test assets."""
    from db.models import PlaylistAsset
    for idx, asset_id in enumerate(test_assets):
        item = PlaylistAsset(
            playlist_id=test_playlist.id,
            asset_id=asset_id,
            position=idx,
            cached_title=f"Video {idx + 1}",
        )
        db_session.add(item)
    db_session.commit()
    return test_playlist


@pytest.fixture
def test_assets(db_session, test_user):
    """Create multiple test assets."""
    from db.models import Asset, AssetType
    asset_ids = []
    for i in range(3):
        asset = Asset(
            type=AssetType.UPLOAD,
            identifier=f"test_asset_{i}",
            storage_path=f"/tmp/test_{i}.mp4",
            created_by=test_user,
            meta={"title": f"Test Video {i + 1}"}
        )
        db_session.add(asset)
        db_session.flush()
        asset_ids.append(asset.id)
    db_session.commit()
    return asset_ids
```

#### 7.1.3 CRUD Layer Tests (test_playlist_crud.py)

```python
"""Test playlist CRUD operations."""

import pytest
from sqlalchemy.exc import IntegrityError
from db.models import Playlist, PlaylistAsset, PlaylistType, OwnerType


class TestPlaylistCRUD:
    """Test playlist CRUD operations."""

    def test_create_playlist(self, db_session):
        """Test creating a new playlist."""
        playlist = Playlist(
            title="Japanese Basics",
            description="Beginner Japanese lessons",
            playlist_type=PlaylistType.NORMAL,
            owner_type=OwnerType.ADMIN,
        )
        db_session.add(playlist)
        db_session.commit()
        db_session.refresh(playlist)

        assert playlist.id is not None
        assert playlist.title == "Japanese Basics"
        assert playlist.description == "Beginner Japanese lessons"
        assert playlist.playlist_type == PlaylistType.NORMAL
        assert playlist.owner_type == OwnerType.ADMIN

    def test_create_playlist_empty_title_fails(self, db_session):
        """Test that playlist with empty title fails."""
        playlist = Playlist(
            title="",
            playlist_type=PlaylistType.NORMAL,
            owner_type=OwnerType.ADMIN,
        )
        db_session.add(playlist)
        with pytest.raises(IntegrityError):
            db_session.commit()

    def test_update_playlist(self, test_playlist, db_session):
        """Test updating playlist metadata."""
        test_playlist.title = "Updated Title"
        test_playlist.description = "Updated description"
        test_playlist.cover_image = "https://example.com/cover.jpg"
        db_session.commit()
        db_session.refresh(test_playlist)

        assert test_playlist.title == "Updated Title"
        assert test_playlist.description == "Updated description"
        assert test_playlist.cover_image == "https://example.com/cover.jpg"

    def test_delete_playlist_cascades_items(self, test_playlist_with_items, db_session):
        """Test that deleting playlist cascades to playlist_assets."""
        playlist_id = test_playlist_with_items.id

        # Count items before deletion
        items_count = db_session.query(PlaylistAsset).filter(
            PlaylistAsset.playlist_id == playlist_id
        ).count()
        assert items_count > 0

        # Delete playlist
        db_session.delete(test_playlist_with_items)
        db_session.commit()

        # Verify items are deleted
        items_count = db_session.query(PlaylistAsset).filter(
            PlaylistAsset.playlist_id == playlist_id
        ).count()
        assert items_count == 0


class TestPlaylistAssetCRUD:
    """Test playlist asset CRUD operations."""

    def test_add_asset_to_playlist(self, test_playlist, test_assets, db_session):
        """Test adding an asset to a playlist."""
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

    def test_add_duplicate_asset_fails(self, test_playlist, test_assets, db_session):
        """Test that adding duplicate asset raises integrity error."""
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

    def test_duplicate_position_fails(self, test_playlist, test_assets, db_session):
        """Test that duplicate position raises integrity error."""
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

    def test_set_asset_position(self, test_playlist_with_items, db_session):
        """Test updating asset position (insertion mode)."""
        playlist_id = test_playlist_with_items.id

        # Get initial positions
        items = db_session.query(PlaylistAsset).filter(
            PlaylistAsset.playlist_id == playlist_id
        ).order_by(PlaylistAsset.position).all()
        assert [i.position for i in items] == [0, 1, 2]

        # Move item at position 2 to position 0
        item_to_move = items[2]
        item_to_move.position = 0
        db_session.commit()

        # Verify positions shifted (insertion mode - handled by application logic)
        # Note: Database constraint alone doesn't handle shifting, CRUD layer must

    def test_remove_asset_from_playlist(self, test_playlist_with_items, db_session):
        """Test removing an asset from playlist."""
        playlist_id = test_playlist_with_items.id
        items = db_session.query(PlaylistAsset).filter(
            PlaylistAsset.playlist_id == playlist_id
        ).all()
        initial_count = len(items)

        # Remove first item
        db_session.delete(items[0])
        db_session.commit()

        # Verify count decreased
        final_count = db_session.query(PlaylistAsset).filter(
            PlaylistAsset.playlist_id == playlist_id
        ).count()
        assert final_count == initial_count - 1

    def test_get_playlist_items_ordered(self, test_playlist_with_items, db_session):
        """Test that playlist items are returned in correct order."""
        items = db_session.query(PlaylistAsset).filter(
            PlaylistAsset.playlist_id == test_playlist_with_items.id
        ).order_by(PlaylistAsset.position).all()

        assert items[0].position == 0
        assert items[1].position == 1
        assert items[2].position == 2
```

#### 7.1.4 API Layer Tests (test_playlist_api.py)

```python
"""Test playlist API endpoints."""

import pytest
from db.models import Playlist, PlaylistAsset, PlaylistType, OwnerType


class TestPlaylistAuth:
    """Test authentication for playlist endpoints."""

    def test_get_playlists_requires_admin(self, client):
        """Test that getting playlists requires admin session."""
        response = client.get("/api/playlists")
        assert response.status_code == 401

    def test_create_playlist_requires_admin(self, client):
        """Test that creating playlist requires admin session."""
        response = client.post("/api/playlists", json={"title": "Test"})
        assert response.status_code == 401


class TestPlaylistAPI:
    """Test playlist CRUD API endpoints."""

    def test_get_playlists_empty(self, admin_client):
        """Test getting playlists when none exist."""
        response = admin_client.get("/api/playlists")
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_get_playlists_with_data(self, admin_client, test_playlist):
        """Test getting playlists with existing data."""
        response = admin_client.get("/api/playlists")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["title"] == "Test Playlist"

    def test_get_playlist_by_id(self, admin_client, test_playlist):
        """Test getting a single playlist by ID."""
        response = admin_client.get(f"/api/playlists/{test_playlist.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(test_playlist.id)
        assert data["title"] == "Test Playlist"

    def test_get_playlist_not_found(self, admin_client):
        """Test getting non-existent playlist returns 404."""
        fake_id = "00000000-0000-0000-0000-000000000000"
        response = admin_client.get(f"/api/playlists/{fake_id}")
        assert response.status_code == 404

    def test_create_playlist_success(self, admin_client):
        """Test creating a new playlist."""
        payload = {
            "title": "New Playlist",
            "description": "New description",
        }
        response = admin_client.post("/api/playlists", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "New Playlist"
        assert data["description"] == "New description"

    def test_create_playlist_empty_title_fails(self, admin_client):
        """Test creating playlist with empty title fails."""
        response = admin_client.post("/api/playlists", json={"title": ""})
        assert response.status_code == 400

    def test_update_playlist_success(self, admin_client, test_playlist):
        """Test updating playlist metadata."""
        payload = {
            "title": "Updated Title",
            "description": "Updated description",
        }
        response = admin_client.put(f"/api/playlists/{test_playlist.id}", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Updated Title"

    def test_delete_playlist_success(self, admin_client, test_playlist):
        """Test deleting a playlist."""
        response = admin_client.delete(f"/api/playlists/{test_playlist.id}")
        assert response.status_code == 204

        # Verify deleted
        response = admin_client.get(f"/api/playlists/{test_playlist.id}")
        assert response.status_code == 404


class TestPlaylistItemAPI:
    """Test playlist item API endpoints."""

    def test_get_playlist_items(self, admin_client, test_playlist_with_items):
        """Test getting items in a playlist."""
        response = admin_client.get(f"/api/playlists/{test_playlist_with_items.id}/items")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        assert len(data["items"]) == 3

    def test_add_item_to_playlist(self, admin_client, test_playlist, test_assets):
        """Test adding an asset to a playlist."""
        payload = {"asset_id": str(test_assets[0])}
        response = admin_client.post(
            f"/api/playlists/{test_playlist.id}/items",
            json=payload
        )
        assert response.status_code == 200
        data = response.json()
        assert data["position"] == 0

    def test_add_item_with_position(self, admin_client, test_playlist, test_assets):
        """Test adding an asset at specific position."""
        payload = {"asset_id": str(test_assets[0]), "position": 5}
        response = admin_client.post(
            f"/api/playlists/{test_playlist.id}/items",
            json=payload
        )
        assert response.status_code == 200
        data = response.json()
        assert data["position"] == 5

    def test_add_duplicate_item_returns_409(self, admin_client, test_playlist_with_items, test_assets):
        """Test adding duplicate asset returns 409 conflict."""
        # Get first asset_id from playlist
        response = admin_client.get(f"/api/playlists/{test_playlist_with_items.id}/items")
        existing_asset_id = response.json()["items"][0]["asset_id"]

        payload = {"asset_id": existing_asset_id}
        response = admin_client.post(
            f"/api/playlists/{test_playlist_with_items.id}/items",
            json=payload
        )
        assert response.status_code == 409
        assert "already in playlist" in response.json()["detail"].lower()

    def test_set_item_position(self, admin_client, test_playlist_with_items):
        """Test setting item position (insertion mode)."""
        # Get current items
        response = admin_client.get(f"/api/playlists/{test_playlist_with_items.id}/items")
        items = response.json()["items"]
        asset_id = items[2]["asset_id"]  # Last item

        # Move to position 0
        payload = {"position": 0}
        response = admin_client.put(
            f"/api/playlists/{test_playlist_with_items.id}/items/{asset_id}",
            json=payload
        )
        assert response.status_code == 200

        # Verify order changed
        response = admin_client.get(f"/api/playlists/{test_playlist_with_items.id}/items")
        items = response.json()["items"]
        assert items[0]["asset_id"] == asset_id

    def test_remove_item_from_playlist(self, admin_client, test_playlist_with_items):
        """Test removing an item from playlist."""
        # Get first item
        response = admin_client.get(f"/api/playlists/{test_playlist_with_items.id}/items")
        asset_id = response.json()["items"][0]["asset_id"]

        # Remove it
        response = admin_client.delete(
            f"/api/playlists/{test_playlist_with_items.id}/items/{asset_id}"
        )
        assert response.status_code == 204

        # Verify removed
        response = admin_client.get(f"/api/playlists/{test_playlist_with_items.id}/items")
        items = response.json()["items"]
        assert len(items) == 2


class TestPlaylistContextAPI:
    """Test playlist context endpoint for play page."""

    def test_get_playlist_context(self, admin_client, test_playlist_with_items):
        """Test getting playlist context for play page."""
        # Get first asset_id
        response = admin_client.get(f"/api/playlists/{test_playlist_with_items.id}/items")
        asset_id = response.json()["items"][0]["asset_id"]

        # Get context
        response = admin_client.get(
            f"/api/playlists/{test_playlist_with_items.id}/context?asset_id={asset_id}"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["playlist_id"] == str(test_playlist_with_items.id)
        assert data["current_position"] == 0
        assert len(data["items"]) == 3

    def test_get_playlist_context_asset_not_in_playlist(self, admin_client, test_playlist):
        """Test context with asset not in playlist returns 404."""
        fake_asset_id = "00000000-0000-0000-0000-000000000000"
        response = admin_client.get(
            f"/api/playlists/{test_playlist.id}/context?asset_id={fake_asset_id}"
        )
        assert response.status_code == 404


class TestAssetSearchAPI:
    """Test asset search endpoint."""

    def test_search_assets_by_title(self, admin_client, test_assets):
        """Test searching assets by title."""
        response = admin_client.get("/api/assets/search?q=Test")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 3

    def test_search_assets_empty_query(self, admin_client):
        """Test search with empty query returns all assets."""
        response = admin_client.get("/api/assets/search?q=")
        assert response.status_code == 200
        # Should return results or empty based on implementation

    def test_search_assets_no_results(self, admin_client):
        """Test search with no matching results."""
        response = admin_client.get("/api/assets/search?q=NonexistentVideoXYZ")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0


class TestPlaylistIntegration:
    """Integration tests for complete workflows."""

    def test_full_playlist_workflow(self, admin_client, test_assets):
        """Test complete workflow: create → add → reorder → delete."""
        # 1. Create playlist
        payload = {"title": "Integration Test Playlist"}
        response = admin_client.post("/api/playlists", json=payload)
        assert response.status_code == 200
        playlist_id = response.json()["id"]

        # 2. Add multiple assets
        for asset_id in test_assets:
            payload = {"asset_id": asset_id}
            response = admin_client.post(f"/api/playlists/{playlist_id}/items", json=payload)
            assert response.status_code == 200

        # 3. Verify all added
        response = admin_client.get(f"/api/playlists/{playlist_id}/items")
        assert response.json()["total"] == 3

        # 4. Reorder items
        response = admin_client.get(f"/api/playlists/{playlist_id}/items")
        items = response.json()["items"]
        last_asset_id = items[2]["asset_id"]

        # Move last item to first position
        admin_client.put(
            f"/api/playlists/{playlist_id}/items/{last_asset_id}",
            json={"position": 0}
        )

        # Verify reorder
        response = admin_client.get(f"/api/playlists/{playlist_id}/items")
        items = response.json()["items"]
        assert items[0]["asset_id"] == last_asset_id

        # 5. Remove one item
        admin_client.delete(f"/api/playlists/{playlist_id}/items/{items[1]['asset_id']}")
        response = admin_client.get(f"/api/playlists/{playlist_id}/items")
        assert response.json()["total"] == 2

        # 6. Delete playlist
        response = admin_client.delete(f"/api/playlists/{playlist_id}")
        assert response.status_code == 204

        # Verify deleted
        response = admin_client.get(f"/api/playlists/{playlist_id}")
        assert response.status_code == 404

    def test_empty_playlist_workflow(self, admin_client):
        """Test operations on an empty playlist."""
        # Create empty playlist
        response = admin_client.post("/api/playlists", json={"title": "Empty"})
        playlist_id = response.json()["id"]

        # Get items should return empty
        response = admin_client.get(f"/api/playlists/{playlist_id}/items")
        assert response.json()["total"] == 0

        # Delete should work
        response = admin_client.delete(f"/api/playlists/{playlist_id}")
        assert response.status_code == 204
```

### 7.2 Frontend Tests (Playwright)

#### 7.2.1 Test File Structure
```
frontend/tests/
├── admin.spec.js           # Existing
├── home.spec.js            # Existing
├── playpage.spec.js        # Existing
├── upload.spec.js          # Existing
└── playlist.spec.js        # New: playlist management tests
```

#### 7.2.2 Playlist Tests (playlist.spec.js)

```javascript
const { test, expect } = require('@playwright/test');

test.describe('Playlist Management', () => {
  test.beforeEach(async ({ page }) => {
    // Mock admin login
    await page.route('**/api/admin/login', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          session_id: 'test-admin-session',
          expires_at: Date.now() + 3600000
        })
      });
    });

    // Mock playlists list
    await page.route('**/api/playlists', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [
            {
              id: '11111111-1111-1111-1111-111111111111',
              title: '日语入门',
              description: '初级日语课程',
              cover_image: null,
              item_count: 5,
              created_at: '2024-01-15T10:00:00Z'
            }
          ],
          total: 1
        })
      });
    });
  });

  test('should show playlists tab in admin panel', async ({ page }) => {
    await page.goto('/#/admin');
    await page.fill('input[placeholder="Enter admin username"]', 'admin');
    await page.fill('input[placeholder="Enter admin password"]', 'pass');
    await page.click('button:has-text("Login")');

    // Should have Playlists tab
    await expect(page.locator('text=Playlists')).toBeVisible();
  });

  test('should display playlist list', async ({ page }) => {
    await page.goto('/#/admin');
    await page.fill('input[placeholder="Enter admin username"]', 'admin');
    await page.fill('input[placeholder="Enter admin password"]', 'pass');
    await page.click('button:has-text("Login")');
    await page.click('text=Playlists');

    // Mock playlist items response
    await page.route('**/api/playlists/*/items', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [
            { asset_id: 'aaa-1', position: 0, cached_title: '第1课 - 问候' },
            { asset_id: 'aaa-2', position: 1, cached_title: '第2课 - 自我介绍' }
          ],
          total: 2
        })
      });
    });

    await expect(page.locator('text=日语入门')).toBeVisible();
    await expect(page.locator('text=5 videos')).toBeVisible();
  });

  test('should create new playlist', async ({ page }) => {
    // Mock create endpoint
    await page.route('**/api/playlists', async (route) => {
      const method = route.request().method();
      if (method === 'POST') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            id: '22222222-2222-2222-2222-222222222222',
            title: '新列表',
            description: '',
            cover_image: null
          })
        });
      } else {
        await route.continue();
      }
    });

    await page.goto('/#/admin');
    await page.fill('input[placeholder="Enter admin username"]', 'admin');
    await page.fill('input[placeholder="Enter admin password"]', 'pass');
    await page.click('button:has-text("Login")');
    await page.click('text=Playlists');
    await page.click('button:has-text("+ New Playlist")');

    await page.fill('input[placeholder*="title"]', '新列表');
    await page.click('button:has-text("Save")');

    await expect(page.locator('text=新列表')).toBeVisible();
  });
});

test.describe('Play Page with Playlist', () => {
  test('should show playlist sidebar when playlist_id param exists', async ({ page }) => {
    // Mock asset and playlist context
    await page.route('**/api/assets/*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'asset-123',
          type: 'youtube',
          identifier: 'test123',
          title: 'Test Video',
          segments: []
        })
      });
    });

    await page.route('**/api/playlists/*/context*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          playlist_id: '11111111-1111-1111-1111-111111111111',
          playlist_title: '日语入门',
          current_position: 0,
          items: [
            { asset_id: 'asset-123', position: 0, cached_title: '第1课 - 问候' },
            { asset_id: 'asset-456', position: 1, cached_title: '第2课 - 自我介绍' }
          ]
        })
      });
    });

    await page.goto('/#/play/asset-123?playlist_id=11111111-1111-1111-1111-111111111111');

    // Should show playlist sidebar
    await expect(page.locator('text=日语入门')).toBeVisible();
    await expect(page.locator('text=第2课 - 自我介绍')).toBeVisible();
  });

  test('should navigate to next video in playlist', async ({ page }) => {
    // Same mocks as above
    await page.route('**/api/assets/*', async (route) => {
      const url = route.request().url();
      const assetId = url.includes('asset-456') ? 'asset-456' : 'asset-123';
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: assetId,
          type: 'youtube',
          identifier: assetId,
          title: assetId === 'asset-456' ? 'Video 2' : 'Video 1',
          segments: []
        })
      });
    });

    await page.route('**/api/playlists/*/context*', async (route) => {
      const url = new URL(route.request().url());
      const assetId = url.searchParams.get('asset_id');
      const position = assetId === 'asset-456' ? 1 : 0;

      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          playlist_id: '11111111-1111-1111-1111-111111111111',
          playlist_title: '日语入门',
          current_position: position,
          items: [
            { asset_id: 'asset-123', position: 0, cached_title: '第1课' },
            { asset_id: 'asset-456', position: 1, cached_title: '第2课' }
          ]
        })
      });
    });

    await page.goto('/#/play/asset-123?playlist_id=11111111-1111-1111-1111-111111111111');

    // Click next video
    await page.click('text=第2课');

    // Should navigate to next video
    await expect(page).toHaveURL(/\/play\/asset-456/);
  });

  test('should NOT show sidebar without playlist_id', async ({ page }) => {
    await page.route('**/api/assets/*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'asset-123',
          type: 'youtube',
          identifier: 'test123',
          title: 'Test Video',
          segments: []
        })
      });
    });

    await page.goto('/#/play/asset-123');

    // Should NOT show playlist sidebar
    await expect(page.locator('text=日语入门')).not.toBeVisible();
  });
});
```

### 7.3 Test Execution

```bash
# Backend tests
cd backend
pytest tests/test_playlist_crud.py -v
pytest tests/test_playlist_api.py -v

# Frontend tests
cd frontend
npm run test playlist.spec.js
npm run test:ui   # Run with UI
```

---

## 8. Implementation Tasks

### Backend
1. [ ] Create database migration for playlist tables
2. [ ] Add `Playlist` and `PlaylistAsset` models to `backend/db/models.py`
3. [ ] Add playlist CRUD operations to `backend/db/crud.py`
4. [ ] Add playlist routes to `backend/routes.py`
5. [ ] Add asset search endpoint
6. [ ] Write tests for playlist operations

### Frontend
1. [ ] Add playlist API methods to `frontend/js/api.js`
2. [ ] Add playlist context state to `frontend/js/app.js`
3. [ ] Create playlist sidebar component for play page
4. [ ] Add playlist tab to admin panel
5. [ ] Create playlist management UI (list, create, edit)
6. [ ] Create playlist item management UI (add, remove, reorder)
7. [ ] Create asset search modal for adding to playlist

### Test Infrastructure
1. [ ] Update `backend/tests/conftest.py`:
   - Import `Playlist` and `PlaylistAsset` models
   - Add playlist cleanup to `clean_database` fixture
   - Add `test_playlist`, `test_playlist_with_items`, `test_assets` fixtures
2. [ ] Create `backend/tests/test_playlist_crud.py`
3. [ ] Create `backend/tests/test_playlist_api.py`
4. [ ] Create `frontend/tests/playlist.spec.js`

---

## 9. Open Questions

| Question | Status |
|----------|--------|
| Should we auto-play next video when current finishes? | TBD |
| Max items per playlist limit? | No (Phase 1) |
| Should we cache playlist data for performance? | No (Phase 1) |
| Internationalization for playlist titles? | Existing pattern |

---

## 10. Appendix: Error Codes

| Code | Message | HTTP Status |
|------|---------|-------------|
| `PLAYLIST_NOT_FOUND` | Playlist not found | 404 |
| `ASSET_NOT_FOUND` | Asset not found | 404 |
| `ASSET_ALREADY_IN_PLAYLIST` | Asset already in playlist | 409 |
| `INVALID_POSITION` | Position must be >= 0 | 400 |
| `PLAYLIST_NOT_EMPTY` | Cannot delete playlist with items | 400 (if we add this restriction) |
