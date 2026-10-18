"""Notifications: read on opening, kept until cleared

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-18 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("notification", schema=None) as batch_op:
        batch_op.add_column(sa.Column("cleared_at", sa.DateTime(), nullable=True))
        batch_op.create_index(batch_op.f("ix_notification_cleared_at"), ["cleared_at"])
    # Until now, read notifications were the History: they stay there.
    op.execute("UPDATE notification SET cleared_at = read_at WHERE read_at IS NOT NULL")


def downgrade() -> None:
    # Before, the History was every read notification: read but not cleared ones join it.
    with op.batch_alter_table("notification", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_notification_cleared_at"))
        batch_op.drop_column("cleared_at")
