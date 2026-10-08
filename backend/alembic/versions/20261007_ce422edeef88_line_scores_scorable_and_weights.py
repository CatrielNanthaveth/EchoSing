"""Line scores: scorable flag, voiced-frame weight and nullable score.

Revision ID: ce422edeef88
Revises: 0d122f277411
Create Date: 2026-10-07 23:27:38.724663

Lines with too little singing in the reference are recorded without a score.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ce422edeef88"
down_revision: str | Sequence[str] | None = "0d122f277411"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DOUBLE: sa.types.TypeEngine[float] = sa.DOUBLE_PRECISION(precision=53)


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "line_scores",
        sa.Column("scorable", sa.Boolean(), server_default="true", nullable=False),
    )
    op.add_column(
        "line_scores",
        sa.Column("voiced_frames", sa.Integer(), server_default="0", nullable=False),
    )
    op.alter_column("line_scores", "score", existing_type=_DOUBLE, nullable=True)
    op.alter_column("line_scores", "accuracy", existing_type=_DOUBLE, nullable=True)
    op.create_check_constraint(
        op.f("ck_line_scores_scorable_has_score"),
        "line_scores",
        "NOT scorable OR (score IS NOT NULL AND accuracy IS NOT NULL)",
    )


def downgrade() -> None:
    """Downgrade schema.

    The previous schema cannot represent unscored lines, so they are deleted.
    """
    op.drop_constraint(
        op.f("ck_line_scores_scorable_has_score"), "line_scores", type_="check"
    )
    op.execute("DELETE FROM line_scores WHERE score IS NULL OR accuracy IS NULL")
    op.alter_column("line_scores", "accuracy", existing_type=_DOUBLE, nullable=False)
    op.alter_column("line_scores", "score", existing_type=_DOUBLE, nullable=False)
    op.drop_column("line_scores", "voiced_frames")
    op.drop_column("line_scores", "scorable")
