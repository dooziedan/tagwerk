"""When each track joined the library (Statistics: library growth)

Existing tracks get the best date the database knows: the import, for tracks imported from
the inbox; otherwise the earliest of the file's date and Tagwerk's first change to it (a
write changes the file's date, but never to before the track was there).

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-07 20:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("track", schema=None) as batch_op:
        batch_op.add_column(sa.Column("added_at", sa.DateTime(), nullable=True))
        batch_op.create_index(batch_op.f("ix_track_added_at"), ["added_at"], unique=False)
    op.execute(
        """
        UPDATE track SET added_at = coalesce(
            (SELECT min(cs.applied_at) FROM changeentry ce JOIN changeset cs
               ON cs.id = ce.changeset_id
             WHERE ce.track_id = track.id AND cs.kind = 'import' AND cs.undone_at IS NULL),
            min(
                datetime(track.mtime, 'unixepoch'),
                coalesce(
                    (SELECT min(cs.applied_at) FROM changeentry ce JOIN changeset cs
                       ON cs.id = ce.changeset_id WHERE ce.track_id = track.id),
                    datetime(track.mtime, 'unixepoch')
                )
            )
        )
        """
    )


def downgrade() -> None:
    with op.batch_alter_table("track", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_track_added_at"))
        batch_op.drop_column("added_at")
