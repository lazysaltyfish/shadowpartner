import uuid
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy import Enum as SQLEnum
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    pass


class AssetType(str, Enum):
    YOUTUBE = "youtube"
    UPLOAD = "upload"


class SubtitleTrackType(str, Enum):
    RAW = "raw"
    PROCESSED = "processed"


class SubtitleSource(str, Enum):
    USER_UPLOAD = "user_upload"
    AI_GENERATED = "ai_generated"


class PlaylistType(str, Enum):
    NORMAL = "normal"
    FAVORITES = "favorites"
    HISTORY = "history"


class OwnerType(str, Enum):
    ADMIN = "admin"
    USER = "user"


# ==================== Models ====================


class User(SQLModel, table=True):
    __tablename__ = "user"  # type: ignore[reportAssignmentType]

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    username: Optional[str] = Field(default=None, max_length=100, index=True)
    password_hash: Optional[str] = Field(default=None, max_length=255)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    assets: List["Asset"] = Relationship(back_populates="created_by_user")


class Asset(SQLModel, table=True):
    __tablename__ = "asset"  # type: ignore[reportAssignmentType]

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    type: AssetType = Field(sa_column=Column(SQLEnum(AssetType), nullable=False))
    identifier: str = Field(max_length=255, index=True)
    storage_path: Optional[str] = Field(default=None, max_length=500)
    meta: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    created_by: Optional[uuid.UUID] = Field(default=None, foreign_key="user.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    is_admin_upload: bool = Field(default=False)

    # Unique constraint on type + identifier for deduplication
    __table_args__ = (UniqueConstraint("type", "identifier", name="uq_asset_type_identifier"),)

    # Relationships
    created_by_user: Optional["User"] = Relationship(back_populates="assets")
    subtitle_tracks: List["SubtitleTrack"] = Relationship(
        back_populates="asset",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    # Keep delete-orphan off: treat this collection as read-only to avoid accidental clears.
    playlist_items: List["PlaylistAsset"] = Relationship(
        back_populates="asset",
        sa_relationship_kwargs={"cascade": "all, delete"},
    )


class SubtitleTrack(SQLModel, table=True):
    __tablename__ = "subtitle_track"  # type: ignore[reportAssignmentType]

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    asset_id: uuid.UUID = Field(foreign_key="asset.id", index=True)
    track_type: SubtitleTrackType = Field(
        sa_column=Column(SQLEnum(SubtitleTrackType), nullable=False)
    )
    source: SubtitleSource = Field(sa_column=Column(SQLEnum(SubtitleSource), nullable=False))
    language: str = Field(max_length=10)
    content: dict = Field(sa_column=Column(JSON), default_factory=dict)
    is_default: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    asset: Optional["Asset"] = Relationship(back_populates="subtitle_tracks")


class Playlist(SQLModel, table=True):
    __tablename__ = "playlist"  # type: ignore[reportAssignmentType]

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    title: str = Field(max_length=255)
    description: Optional[str] = Field(default=None, sa_column=Column(Text))
    cover_image: Optional[str] = Field(default=None, max_length=512)
    playlist_type: PlaylistType = Field(
        default=PlaylistType.NORMAL,
        sa_column=Column(SQLEnum(PlaylistType), nullable=False),
    )
    owner_type: OwnerType = Field(
        default=OwnerType.ADMIN,
        sa_column=Column(SQLEnum(OwnerType), nullable=False),
    )
    owner_id: Optional[uuid.UUID] = Field(default=None, foreign_key="user.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        sa_column=Column(
            DateTime,
            default=datetime.utcnow,
            onupdate=datetime.utcnow,
            nullable=False,
        ),
    )

    # Relationships
    items: List["PlaylistAsset"] = Relationship(
        back_populates="playlist",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class PlaylistAsset(SQLModel, table=True):
    __tablename__ = "playlist_asset"  # type: ignore[reportAssignmentType]

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    playlist_id: uuid.UUID = Field(
        sa_column=Column(ForeignKey("playlist.id", ondelete="CASCADE"), nullable=False),
    )
    asset_id: uuid.UUID = Field(
        sa_column=Column(ForeignKey("asset.id", ondelete="CASCADE"), nullable=False),
    )
    position: int = Field(default=0, index=True)
    cached_title: str = Field(max_length=512)
    cached_thumbnail: Optional[str] = Field(default=None, max_length=512)
    added_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    playlist: Optional["Playlist"] = Relationship(back_populates="items")
    asset: Optional["Asset"] = Relationship(back_populates="playlist_items")

    __table_args__ = (
        UniqueConstraint("playlist_id", "asset_id", name="uq_playlist_asset"),
        UniqueConstraint("playlist_id", "position", name="uq_playlist_position"),
        Index("ix_playlist_assets_position", "playlist_id", "position"),
    )


class VocabularyItem(SQLModel, table=True):
    __tablename__ = "vocabulary_item"  # type: ignore[reportAssignmentType]

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    asset_id: uuid.UUID = Field(foreign_key="asset.id", index=True)

    # Word information
    word: str = Field(index=True, max_length=255)  # Dictionary form (e.g., 食べる)
    reading: str = Field(max_length=255)  # Hiragana (e.g., たべる)
    surface_form: str = Field(max_length=255)  # Original in subtitle (e.g., 食べました)

    # Learning attributes
    jlpt_level: Optional[str] = Field(
        default=None, index=True, max_length=20
    )  # N1, N2, N3, N4, N5, Business
    part_of_speech: str = Field(max_length=100)  # Noun, Verb, Idiom, etc.

    # Translations & notes
    meaning_cn: str = Field(max_length=500)  # Chinese definition
    meaning_en: Optional[str] = Field(default=None, max_length=500)  # English definition
    learning_note: Optional[str] = Field(default=None, max_length=1000)

    # Context
    start_time: float  # Position in video (seconds)
    end_time: float
    context_sentence: str = Field(max_length=2000)

    # Indexes
    __table_args__ = (Index("ix_vocabulary_asset_jlpt", "asset_id", "jlpt_level"),)
