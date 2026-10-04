"""Final tracks

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-04 21:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "finaltrack",
        sa.Column("track_id", sa.Integer(), nullable=False),
        sa.Column("marked_at", sa.DateTime(), nullable=False),
        sa.Column("mtime", sa.Float(), nullable=False),
        sa.Column("name_before", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.ForeignKeyConstraint(["track_id"], ["track.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("track_id"),
    )


def downgrade() -> None:
    op.drop_table("finaltrack")
