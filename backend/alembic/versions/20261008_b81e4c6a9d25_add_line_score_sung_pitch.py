"""Add line_scores.sung_pitch: the pitch the player sang over the line.

Revision ID: b81e4c6a9d25
Revises: a3f9c2d47b10
Create Date: 2026-10-08 19:00:00.000000

Kept as the client sent it (``{"hop_ms", "f0_hz"}``) so a line can be analyzed
again later (practice charts, diagnostics). Older lines have none.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b81e4c6a9d25"
down_revision: str | Sequence[str] | None = "a3f9c2d47b10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "line_scores",
        sa.Column("sung_pitch", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("line_scores", "sung_pitch")
