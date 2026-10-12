"""Better copies: inbox bit depth, and what undoing a replacement needs

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-12 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("inboxtrack") as batch:
        batch.add_column(sa.Column("bits_per_sample", sa.Integer(), nullable=True))
    with op.batch_alter_table("changeentry") as batch:
        batch.add_column(sa.Column("details", sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    # Inbox files are read again on the next inbox check, so they get their bit depth.
    op.execute("UPDATE inboxtrack SET mtime = 0")


def downgrade() -> None:
    with op.batch_alter_table("changeentry") as batch:
        batch.drop_column("details")
    with op.batch_alter_table("inboxtrack") as batch:
        batch.drop_column("bits_per_sample")
