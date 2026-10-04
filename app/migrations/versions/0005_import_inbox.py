"""Import inbox

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-04 16:36:56.373984
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "inboxtrack",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("path", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("format", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("mtime", sa.Float(), nullable=False),
        sa.Column("duration", sa.Float(), nullable=True),
        sa.Column("bitrate", sa.Integer(), nullable=True),
        sa.Column("sample_rate", sa.Integer(), nullable=True),
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
        sa.Column("bpm", sa.Float(), nullable=True),
        sa.Column("key", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("key_camelot", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("comment", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("label", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("catalognumber", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("mb_trackid", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("has_cover", sa.Boolean(), nullable=False),
        sa.Column("error", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("found_at", sa.DateTime(), nullable=False),
        sa.Column("scanned_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("inboxtrack", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_inboxtrack_path"), ["path"], unique=True)

    op.create_table(
        "inboxvalue",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("track_id", sa.Integer(), nullable=False),
        sa.Column("field", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("value", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.ForeignKeyConstraint(["track_id"], ["inboxtrack.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("track_id", "field"),
    )
    with op.batch_alter_table("inboxvalue", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_inboxvalue_track_id"), ["track_id"], unique=False)

    # Imports are recorded in the history like edits; undo moves the file back to the inbox.
    with op.batch_alter_table("changeset", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "kind", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="edit"
            )
        )
    with op.batch_alter_table("changeentry", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("moved_from", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("changeentry", schema=None) as batch_op:
        batch_op.drop_column("moved_from")
    with op.batch_alter_table("changeset", schema=None) as batch_op:
        batch_op.drop_column("kind")
    with op.batch_alter_table("inboxvalue", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_inboxvalue_track_id"))

    op.drop_table("inboxvalue")
    with op.batch_alter_table("inboxtrack", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_inboxtrack_path"))

    op.drop_table("inboxtrack")
