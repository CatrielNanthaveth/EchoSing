"""ORM models of the EchoSing catalog, ingestion and play sessions.

Relationships are intentionally not mapped: repositories query explicitly, which
avoids implicit lazy loads (unsupported with asyncio). Deletion rules live in
the database through ``ON DELETE`` clauses.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, str_enum
from app.domain.enums import AssetKind, IngestionStage, PlaySessionStatus, SongStatus


class Song(Base):
    """A song of the catalog."""

    __tablename__ = "songs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(200))
    artist: Mapped[str] = mapped_column(String(200))
    language: Mapped[str | None] = mapped_column(String(8))
    duration_ms: Mapped[int | None]
    status: Mapped[SongStatus] = mapped_column(
        str_enum(SongStatus, "song_status"), default=SongStatus.PENDING, index=True
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )


class SongAsset(Base):
    """An audio file of a song (original upload or separated stem)."""

    __tablename__ = "song_assets"
    # The unique constraint also serves lookups by song_id (leading column).
    __table_args__ = (UniqueConstraint("song_id", "kind"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    song_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("songs.id", ondelete="CASCADE")
    )
    kind: Mapped[AssetKind] = mapped_column(str_enum(AssetKind, "asset_kind"))
    storage_key: Mapped[str] = mapped_column(String(500))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class SongAnalysis(Base):
    """One version of the lyrics, timestamps and reference pitch of a song.

    Reprocessing a song creates a new version instead of overwriting, so play
    sessions keep pointing at the exact analysis they were scored against.
    """

    __tablename__ = "song_analyses"
    __table_args__ = (
        # Also serves lookups by song_id (leading column).
        UniqueConstraint("song_id", "version"),
        # At most one current analysis per song.
        Index(
            "uq_song_analyses_current",
            "song_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
        CheckConstraint("version >= 1", name="version_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    song_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("songs.id", ondelete="CASCADE")
    )
    version: Mapped[int]
    is_current: Mapped[bool] = mapped_column(default=False)
    format_version: Mapped[int]
    data: Mapped[dict[str, Any]]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class IngestionJob(Base):
    """A run of the ingestion pipeline for a song."""

    __tablename__ = "ingestion_jobs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    song_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("songs.id", ondelete="CASCADE"), index=True
    )
    stage: Mapped[IngestionStage] = mapped_column(
        str_enum(IngestionStage, "ingestion_stage"), default=IngestionStage.QUEUED
    )
    task_id: Mapped[str | None] = mapped_column(String(155))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    # clock_timestamp() (not now(), which is fixed per transaction) so jobs
    # created in the same transaction are still ordered by creation.
    created_at: Mapped[datetime] = mapped_column(server_default=func.clock_timestamp())


class PlaySession(Base):
    """A karaoke performance of one player on one analysis of a song."""

    __tablename__ = "play_sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    song_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("songs.id", ondelete="RESTRICT"), index=True
    )
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("song_analyses.id", ondelete="RESTRICT"), index=True
    )
    player_name: Mapped[str] = mapped_column(String(50))
    latency_offset_ms: Mapped[int] = mapped_column(default=0)
    status: Mapped[PlaySessionStatus] = mapped_column(
        str_enum(PlaySessionStatus, "play_session_status"),
        default=PlaySessionStatus.ACTIVE,
    )
    total_score: Mapped[float | None]
    accuracy: Mapped[float | None]
    best_streak: Mapped[int | None]
    started_at: Mapped[datetime] = mapped_column(server_default=func.now())
    finished_at: Mapped[datetime | None]


class LineScore(Base):
    """Score obtained by a play session on a single lyric line."""

    __tablename__ = "line_scores"
    __table_args__ = (
        UniqueConstraint("session_id", "line_index"),
        CheckConstraint("score >= 0 AND score <= 100", name="score_range"),
        CheckConstraint("accuracy >= 0 AND accuracy <= 1", name="accuracy_range"),
        CheckConstraint("line_index >= 0", name="line_index_non_negative"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("play_sessions.id", ondelete="CASCADE")
    )
    line_index: Mapped[int]
    score: Mapped[float]
    accuracy: Mapped[float]
    hit: Mapped[bool]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
