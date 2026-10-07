"""Initial schema: catalog, ingestion jobs and play sessions.

Revision ID: 54b728c1d54b
Revises:
Create Date: 2026-10-06 21:34:45.806369

Enum columns are plain VARCHAR(32) guarded by a single named CHECK constraint
(``ck_<table>_<enum name>``), matching ``app.db.base.str_enum``.
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "54b728c1d54b"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum_check(column: str, values: Sequence[str], name: str) -> sa.CheckConstraint:
    """Build the CHECK constraint restricting ``column`` to ``values``."""
    allowed = ", ".join(f"'{value}'" for value in values)
    return sa.CheckConstraint(f"{column} IN ({allowed})", name=op.f(name))


def _created_at(
    name: str = "created_at", default: str = "now()"
) -> sa.Column[datetime]:
    """Build a non-null timezone-aware timestamp column with a server default."""
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.text(default),
        nullable=False,
    )


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "songs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("artist", sa.String(length=200), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        _created_at(),
        _created_at("updated_at"),
        _enum_check(
            "status",
            ["pending", "processing", "ready", "failed"],
            "ck_songs_song_status",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_songs")),
    )
    op.create_index(op.f("ix_songs_status"), "songs", ["status"], unique=False)

    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("song_id", sa.Uuid(), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("task_id", sa.String(length=155), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(default="clock_timestamp()"),
        _enum_check(
            "stage",
            [
                "queued",
                "separating",
                "transcribing",
                "segmenting",
                "extracting_pitch",
                "persisting",
                "done",
                "failed",
            ],
            "ck_ingestion_jobs_ingestion_stage",
        ),
        sa.ForeignKeyConstraint(
            ["song_id"],
            ["songs.id"],
            name=op.f("fk_ingestion_jobs_song_id_songs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingestion_jobs")),
    )
    op.create_index(
        op.f("ix_ingestion_jobs_song_id"), "ingestion_jobs", ["song_id"], unique=False
    )

    op.create_table(
        "song_analyses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("song_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("format_version", sa.Integer(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        _created_at(),
        sa.CheckConstraint(
            "version >= 1", name=op.f("ck_song_analyses_version_positive")
        ),
        sa.ForeignKeyConstraint(
            ["song_id"],
            ["songs.id"],
            name=op.f("fk_song_analyses_song_id_songs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_song_analyses")),
        sa.UniqueConstraint(
            "song_id", "version", name=op.f("uq_song_analyses_song_id_version")
        ),
    )
    op.create_index(
        "uq_song_analyses_current",
        "song_analyses",
        ["song_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )

    op.create_table(
        "song_assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("song_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        _created_at(),
        _enum_check(
            "kind",
            ["original", "vocals", "instrumental"],
            "ck_song_assets_asset_kind",
        ),
        sa.ForeignKeyConstraint(
            ["song_id"],
            ["songs.id"],
            name=op.f("fk_song_assets_song_id_songs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_song_assets")),
        sa.UniqueConstraint(
            "song_id", "kind", name=op.f("uq_song_assets_song_id_kind")
        ),
    )

    op.create_table(
        "play_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("song_id", sa.Uuid(), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("player_name", sa.String(length=50), nullable=False),
        sa.Column("latency_offset_ms", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("total_score", sa.Double(), nullable=True),
        sa.Column("accuracy", sa.Double(), nullable=True),
        sa.Column("best_streak", sa.Integer(), nullable=True),
        _created_at("started_at"),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        _enum_check(
            "status",
            ["active", "finished"],
            "ck_play_sessions_play_session_status",
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["song_analyses.id"],
            name=op.f("fk_play_sessions_analysis_id_song_analyses"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["song_id"],
            ["songs.id"],
            name=op.f("fk_play_sessions_song_id_songs"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_play_sessions")),
    )
    op.create_index(
        op.f("ix_play_sessions_analysis_id"),
        "play_sessions",
        ["analysis_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_play_sessions_song_id"), "play_sessions", ["song_id"], unique=False
    )

    op.create_table(
        "line_scores",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("line_index", sa.Integer(), nullable=False),
        sa.Column("score", sa.Double(), nullable=False),
        sa.Column("accuracy", sa.Double(), nullable=False),
        sa.Column("hit", sa.Boolean(), nullable=False),
        _created_at(),
        sa.CheckConstraint(
            "accuracy >= 0 AND accuracy <= 1",
            name=op.f("ck_line_scores_accuracy_range"),
        ),
        sa.CheckConstraint(
            "line_index >= 0", name=op.f("ck_line_scores_line_index_non_negative")
        ),
        sa.CheckConstraint(
            "score >= 0 AND score <= 100", name=op.f("ck_line_scores_score_range")
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["play_sessions.id"],
            name=op.f("fk_line_scores_session_id_play_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_line_scores")),
        sa.UniqueConstraint(
            "session_id",
            "line_index",
            name=op.f("uq_line_scores_session_id_line_index"),
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("line_scores")
    op.drop_index(op.f("ix_play_sessions_song_id"), table_name="play_sessions")
    op.drop_index(op.f("ix_play_sessions_analysis_id"), table_name="play_sessions")
    op.drop_table("play_sessions")
    op.drop_table("song_assets")
    op.drop_index("uq_song_analyses_current", table_name="song_analyses")
    op.drop_table("song_analyses")
    op.drop_index(op.f("ix_ingestion_jobs_song_id"), table_name="ingestion_jobs")
    op.drop_table("ingestion_jobs")
    op.drop_index(op.f("ix_songs_status"), table_name="songs")
    op.drop_table("songs")
