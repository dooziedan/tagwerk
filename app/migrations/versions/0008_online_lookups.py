"""Online lookups

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-04 22:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "onlinelookup",
        sa.Column("track_id", sa.Integer(), nullable=False),
        sa.Column("source", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("query", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("candidates", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("error", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("looked_up_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["track_id"], ["inboxtrack.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("track_id", "source"),
    )


def downgrade() -> None:
    op.drop_table("onlinelookup")
