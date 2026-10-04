"""dj fields and settings

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-04 10:51:41.367571
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "appsetting",
        sa.Column("key", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("value", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    with op.batch_alter_table("track", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("has_lyrics", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(
            sa.Column("has_lrc", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(sa.Column("bpm", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("key", sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.add_column(
            sa.Column("key_camelot", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch_op.add_column(sa.Column("comment", sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.add_column(sa.Column("label", sqlmodel.sql.sqltypes.AutoString(), nullable=True))
        batch_op.add_column(
            sa.Column("catalognumber", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch_op.add_column(sa.Column("replaygain_track_gain", sa.Float(), nullable=True))
        batch_op.add_column(
            sa.Column("scan_version", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.create_index(batch_op.f("ix_track_key_camelot"), ["key_camelot"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("track", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_track_key_camelot"))
        batch_op.drop_column("scan_version")
        batch_op.drop_column("replaygain_track_gain")
        batch_op.drop_column("catalognumber")
        batch_op.drop_column("label")
        batch_op.drop_column("comment")
        batch_op.drop_column("key_camelot")
        batch_op.drop_column("key")
        batch_op.drop_column("bpm")
        batch_op.drop_column("has_lrc")
        batch_op.drop_column("has_lyrics")

    op.drop_table("appsetting")
