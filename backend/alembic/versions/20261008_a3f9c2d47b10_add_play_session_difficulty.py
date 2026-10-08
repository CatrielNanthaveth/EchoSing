"""Add play_sessions.difficulty (easy | normal | hard).

Revision ID: a3f9c2d47b10
Revises: ce422edeef88
Create Date: 2026-10-08 17:00:00.000000

New sessions default to ``normal``. Existing sessions were scored with what is
now the ``hard`` tolerance, so they get that level.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3f9c2d47b10"
down_revision: str | Sequence[str] | None = "ce422edeef88"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "play_sessions",
        sa.Column(
            "difficulty", sa.String(length=32), server_default="hard", nullable=False
        ),
    )
    op.alter_column("play_sessions", "difficulty", server_default="normal")
    op.create_check_constraint(
        op.f("ck_play_sessions_difficulty"),
        "play_sessions",
        "difficulty IN ('easy', 'normal', 'hard')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        op.f("ck_play_sessions_difficulty"), "play_sessions", type_="check"
    )
    op.drop_column("play_sessions", "difficulty")
