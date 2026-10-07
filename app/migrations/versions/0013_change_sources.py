"""Where each changed value came from: you, the audio, online, the filename …

Only recorded from now on: older pending changes and history entries keep NULL, shown as
"source unknown".

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-07 22:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("pendingchange", schema=None) as batch_op:
        batch_op.add_column(sa.Column("source", sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    with op.batch_alter_table("changeentry", schema=None) as batch_op:
        batch_op.add_column(sa.Column("sources", sqlmodel.sql.sqltypes.AutoString(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("changeentry", schema=None) as batch_op:
        batch_op.drop_column("sources")
    with op.batch_alter_table("pendingchange", schema=None) as batch_op:
        batch_op.drop_column("source")
