"""changes and history

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-04 13:33:57.526551
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "changeset",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("applied_at", sa.DateTime(), nullable=False),
        sa.Column("tracks", sa.Integer(), nullable=False),
        sa.Column("written", sa.Integer(), nullable=False),
        sa.Column("failed", sa.Integer(), nullable=False),
        sa.Column("fields", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("undone_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "changeentry",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("changeset_id", sa.Integer(), nullable=False),
        sa.Column("track_id", sa.Integer(), nullable=True),
        sa.Column("path", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("changes", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("snapshot", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("mtime_after", sa.Float(), nullable=True),
        sa.Column("error", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("undone", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["changeset_id"], ["changeset.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["track_id"], ["track.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("changeentry", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_changeentry_changeset_id"), ["changeset_id"], unique=False
        )

    op.create_table(
        "pendingchange",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("track_id", sa.Integer(), nullable=False),
        sa.Column("field", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("old_value", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("new_value", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["track_id"], ["track.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("track_id", "field"),
    )
    with op.batch_alter_table("pendingchange", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_pendingchange_track_id"), ["track_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("pendingchange", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_pendingchange_track_id"))

    op.drop_table("pendingchange")
    with op.batch_alter_table("changeentry", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_changeentry_changeset_id"))

    op.drop_table("changeentry")
    op.drop_table("changeset")
