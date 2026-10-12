"""Add play_sessions.mode (melody | rhythm).

Revision ID: c4d7e1f9a2b3
Revises: b81e4c6a9d25
Create Date: 2026-10-12 12:00:00.000000

Existing sessions were scored by pitch: they get ``melody``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4d7e1f9a2b3"
down_revision: str | Sequence[str] | None = "b81e4c6a9d25"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "play_sessions",
        sa.Column(
            "mode", sa.String(length=32), server_default="melody", nullable=False
        ),
    )
    op.create_check_constraint(
        op.f("ck_play_sessions_scoring_mode"),
        "play_sessions",
        "mode IN ('melody', 'rhythm')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        op.f("ck_play_sessions_scoring_mode"), "play_sessions", type_="check"
    )
    op.drop_column("play_sessions", "mode")
