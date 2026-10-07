"""Add songs.separation_preset (demucs | roformer).

Revision ID: 561cb5129631
Revises: 54b728c1d54b
Create Date: 2026-10-07 00:15:39.023652

Existing songs get the ``demucs`` preset, which is what they were processed with.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "561cb5129631"
down_revision: str | Sequence[str] | None = "54b728c1d54b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "songs",
        sa.Column(
            "separation_preset",
            sa.String(length=32),
            server_default="demucs",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f("ck_songs_separation_preset"),
        "songs",
        "separation_preset IN ('demucs', 'roformer')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f("ck_songs_separation_preset"), "songs", type_="check")
    op.drop_column("songs", "separation_preset")
