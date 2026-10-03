"""create track table

Revision ID: 0001
Revises:
Create Date: 2026-10-04 00:28:52.545259
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "track",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("path", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("format", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("mtime", sa.Float(), nullable=False),
        sa.Column("duration", sa.Float(), nullable=True),
        sa.Column("bitrate", sa.Integer(), nullable=True),
        sa.Column("sample_rate", sa.Integer(), nullable=True),
        sa.Column("bits_per_sample", sa.Integer(), nullable=True),
        sa.Column("channels", sa.Integer(), nullable=True),
        sa.Column("tag_format", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("artist", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("album", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("albumartist", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("tracknumber", sa.Integer(), nullable=True),
        sa.Column("tracktotal", sa.Integer(), nullable=True),
        sa.Column("discnumber", sa.Integer(), nullable=True),
        sa.Column("disctotal", sa.Integer(), nullable=True),
        sa.Column("date", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("genre", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("mb_trackid", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("mb_albumid", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("mb_artistid", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("mb_albumartistid", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("mbid_invalid", sa.Boolean(), nullable=False),
        sa.Column("has_cover", sa.Boolean(), nullable=False),
        sa.Column("error", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("scanned_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("track", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_track_format"), ["format"], unique=False)
        batch_op.create_index(batch_op.f("ix_track_path"), ["path"], unique=True)
        batch_op.create_index(batch_op.f("ix_track_year"), ["year"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("track", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_track_year"))
        batch_op.drop_index(batch_op.f("ix_track_path"))
        batch_op.drop_index(batch_op.f("ix_track_format"))

    op.drop_table("track")
