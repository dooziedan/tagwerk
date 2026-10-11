"""Secret tracks: unofficial edits and bootlegs, never looked up online

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-11 22:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "secrettrack",
        sa.Column("marked_at", sa.DateTime(), nullable=False),
        sa.Column("track_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["track_id"], ["track.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("track_id"),
    )
    op.create_table(
        "secretinboxtrack",
        sa.Column("marked_at", sa.DateTime(), nullable=False),
        sa.Column("track_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["track_id"], ["inboxtrack.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("track_id"),
    )


def downgrade() -> None:
    op.drop_table("secretinboxtrack")
    op.drop_table("secrettrack")
