"""raw tag fields

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-04 11:24:12.944084
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rawtag",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("track_id", sa.Integer(), nullable=False),
        sa.Column("system", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("value", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(["track_id"], ["track.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("rawtag", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_rawtag_name"), ["name"], unique=False)
        batch_op.create_index(batch_op.f("ix_rawtag_track_id"), ["track_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("rawtag", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_rawtag_track_id"))
        batch_op.drop_index(batch_op.f("ix_rawtag_name"))

    op.drop_table("rawtag")
