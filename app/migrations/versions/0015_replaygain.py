"""ReplayGain: track peak, album gain and album peak next to the track gain

Empty until the next scan reads them (SCAN_VERSION 6 re-reads every track once).

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-09 21:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = ("replaygain_track_peak", "replaygain_album_gain", "replaygain_album_peak")


def upgrade() -> None:
    with op.batch_alter_table("track", schema=None) as batch_op:
        for name in COLUMNS:
            batch_op.add_column(sa.Column(name, sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("track", schema=None) as batch_op:
        for name in reversed(COLUMNS):
            batch_op.drop_column(name)
