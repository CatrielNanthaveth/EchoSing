"""Add songs.lyrics_text (official lyrics, one verse per line).

Revision ID: 0d122f277411
Revises: 561cb5129631
Create Date: 2026-10-07 21:54:02.868629
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0d122f277411"
down_revision: str | Sequence[str] | None = "561cb5129631"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("songs", sa.Column("lyrics_text", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("songs", "lyrics_text")
