"""Audio analysis: BPM and key from the audio of inbox and library tracks

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-06 22:29:15.777024
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns() -> list[sa.Column]:
    return [
        sa.Column("bpm", sa.Float(), nullable=True),
        sa.Column("bpm_sure", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("key", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("key_sure", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "detail", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="{}"
        ),
        sa.Column("error", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration", sa.Float(), nullable=True),
        sa.Column("analysed_at", sa.DateTime(), nullable=False),
        sa.Column("track_id", sa.Integer(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "inboxanalysis",
        *_columns(),
        sa.ForeignKeyConstraint(["track_id"], ["inboxtrack.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("track_id"),
    )
    op.create_table(
        "libraryanalysis",
        *_columns(),
        sa.Column("decided_bpm", sa.Float(), nullable=True),
        sa.Column("decided_bpm_sure", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("decided_key", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("decided_key_sure", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "decided_notes", sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default="[]"
        ),
        sa.ForeignKeyConstraint(["track_id"], ["track.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("track_id"),
    )


def downgrade() -> None:
    op.drop_table("libraryanalysis")
    op.drop_table("inboxanalysis")
