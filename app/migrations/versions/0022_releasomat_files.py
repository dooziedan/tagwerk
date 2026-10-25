"""The Releasomat area: its files, kept apart from the library (ADR 0044)

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-25 17:29:27.218270
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "releasomatfile",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("path", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("format", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("mtime", sa.Float(), nullable=False),
        sa.Column("duration", sa.Float(), nullable=True),
        sa.Column("bitrate", sa.Integer(), nullable=True),
        sa.Column("sample_rate", sa.Integer(), nullable=True),
        sa.Column("bits_per_sample", sa.Integer(), nullable=True),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("artist", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("album", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("mb_trackid", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("has_cover", sa.Boolean(), nullable=False),
        sa.Column("error", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("found_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.Column("scanned_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("releasomatfile", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_releasomatfile_found_at"), ["found_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_releasomatfile_path"), ["path"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("releasomatfile", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_releasomatfile_path"))
        batch_op.drop_index(batch_op.f("ix_releasomatfile_found_at"))

    op.drop_table("releasomatfile")
