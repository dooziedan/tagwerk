"""Duplicates in the library: the groups found, and pairs the owner keeps apart

The groups are filled in on the next start (app/main.py), then after every scan and write.
Also an index on changeentry.track_id: Statistics and Home ask the history about every track,
which took seconds in a library of 20,000 tracks without it.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-08 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("changeentry", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_changeentry_track_id"), ["track_id"], unique=False)
    op.create_table(
        "duplicatetrack",
        sa.Column("track_id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("reason", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(["track_id"], ["track.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("track_id"),
    )
    with op.batch_alter_table("duplicatetrack", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_duplicatetrack_group_id"), ["group_id"], unique=False)
    op.create_table(
        "notduplicate",
        sa.Column("track_a", sa.Integer(), nullable=False),
        sa.Column("track_b", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["track_a"], ["track.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["track_b"], ["track.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("track_a", "track_b"),
    )


def downgrade() -> None:
    op.drop_table("notduplicate")
    with op.batch_alter_table("duplicatetrack", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_duplicatetrack_group_id"))
    op.drop_table("duplicatetrack")
    with op.batch_alter_table("changeentry", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_changeentry_track_id"))
