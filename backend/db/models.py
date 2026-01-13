import uuid
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import JSON, Column, UniqueConstraint
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


# ==================== Models ====================


class User(SQLModel, table=True):
    __tablename__ = "user"  # type: ignore[reportAssignmentType]

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    username: Optional[str] = Field(default=None, max_length=100, index=True)
    password_hash: Optional[str] = Field(default=None, max_length=255)
    is_admin: bool = Field(default=False)
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

    # Unique constraint on type + identifier for deduplication
    __table_args__ = (UniqueConstraint("type", "identifier", name="uq_asset_type_identifier"),)

    # Relationships
    created_by_user: Optional["User"] = Relationship(back_populates="assets")
    subtitle_tracks: List["SubtitleTrack"] = Relationship(back_populates="asset")


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
