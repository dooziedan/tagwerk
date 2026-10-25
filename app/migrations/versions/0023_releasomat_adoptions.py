"""The Releasomat area: the record of adoptions into the inbox (ADR 0044)

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-25 17:52:10.016868
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "releasomatadoption",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("area_path", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("inbox_path", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("releasomat_id", sa.Integer(), nullable=True),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("artist", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("playlists", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("adopted_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.Column("state", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("notice", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("notice_since", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True),
        sa.Column("notice_error", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("releasomatadoption", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_releasomatadoption_adopted_at"), ["adopted_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_releasomatadoption_inbox_path"), ["inbox_path"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("releasomatadoption", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_releasomatadoption_inbox_path"))
        batch_op.drop_index(batch_op.f("ix_releasomatadoption_adopted_at"))

    op.drop_table("releasomatadoption")
