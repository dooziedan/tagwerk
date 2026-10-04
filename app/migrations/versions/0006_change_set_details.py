"""Change set details

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-04 20:34:20.345914
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("changeset", schema=None) as batch_op:
        batch_op.add_column(sa.Column("details", sqlmodel.sql.sqltypes.AutoString(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("changeset", schema=None) as batch_op:
        batch_op.drop_column("details")
