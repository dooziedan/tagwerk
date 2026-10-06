"""Discogs release and artist IDs on library tracks

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-06 23:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("track", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("discogs_releaseid", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("discogs_artistid", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("track", schema=None) as batch_op:
        batch_op.drop_column("discogs_artistid")
        batch_op.drop_column("discogs_releaseid")
