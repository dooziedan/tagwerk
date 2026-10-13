"""Undoing applied changes: restore each file from its snapshot, then let the feature that
moved it put it back (import, better copy, AIFF conversion, final rename, genre folder).

This sits above all of those modules, so each can import app.changes without a circle.
"""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine, and_, or_
from sqlmodel import Session, col, func, select

from app import convert, final, folders, upgrade, writer
from app.changes import WriteProgress
from app.config import Settings, get_settings
from app.images import ImageStore
from app.importer import move_back
from app.models import ChangeEntry, ChangeSet, Track
from app.scanner import refresh_track

log = logging.getLogger(__name__)


def undo_changeset(
    engine: Engine,
    music_dir: Path,
    changeset_id: int,
    progress: WriteProgress,
    images: ImageStore | None = None,
    import_dir: Path | None = None,
    settings: Settings | None = None,
) -> None:
    """Restore the files of one applied ChangeSet from their snapshots.

    A file that changed again after the change was applied is skipped, so newer edits
    (from Tagwerk or another tool) are never overwritten. Imported files also move back
    into the inbox; files moved into a new genre folder go back to _Unsorted; a better copy goes
    back into the inbox and the file it replaced comes back from the library trash.
    """
    settings = settings or get_settings()  # Navidrome, for renaming final tracks back

    with Session(engine) as session:
        changeset = session.get(ChangeSet, changeset_id)
        entries = session.exec(
            select(ChangeEntry)
            .where(ChangeEntry.changeset_id == changeset_id, _undoable())
            .order_by(ChangeEntry.id.desc())
        ).all()
        progress.total = len(entries)
        progress.changeset_id = changeset_id
        for entry in entries:
            progress.current = entry.path
            try:
                path = music_dir / entry.path
                if path.stat().st_mtime != entry.mtime_after:
                    raise writer.WriteError(
                        "the file changed after this change was applied; not undone, "
                        "so newer edits aren't lost"
                    )
                if entry.moved_from and changeset.kind == "upgrade":
                    upgrade.check_undo(entry, settings)  # before the tags change back
                if entry.snapshot:
                    writer.undo(path, json.loads(entry.snapshot), images)
                if entry.moved_from and changeset.kind == "convert":
                    convert.undo(session, entry, settings)
                elif entry.moved_from and changeset.kind == "upgrade":
                    upgrade.undo(session, entry, settings)
                elif entry.moved_from and changeset.kind == "final":
                    final.undo(session, entry, settings)
                elif entry.moved_from and changeset.kind == "folder":
                    folders.move_back(session, entry, music_dir)
                elif entry.moved_from:
                    if import_dir is None or not import_dir.is_dir():
                        raise writer.WriteError("the import folder isn't available")
                    move_back(session, entry, import_dir, music_dir)
                else:
                    track = session.get(Track, entry.track_id) if entry.track_id else None
                    if track:
                        refresh_track(session, music_dir, track)
                entry.undone = True
                progress.written += 1
            except Exception as exc:
                log.warning("Could not undo %s: %s", entry.path, exc)
                progress.failed += 1
                progress.errors.append(f"{entry.path}: {exc}")
            session.add(entry)
            session.commit()
            progress.processed += 1
        remaining = session.exec(
            select(func.count(ChangeEntry.id)).where(
                ChangeEntry.changeset_id == changeset_id, _undoable()
            )
        ).one()
        if remaining == 0:
            if changeset.kind == "folder":
                folders.finish_undo(session, changeset, music_dir)
            changeset.undone_at = datetime.now(UTC)
            session.add(changeset)
            session.commit()
    progress.current = ""


def _undoable():
    """Entries that can still be undone: written tags, or a file moved by an import."""
    return and_(
        or_(ChangeEntry.snapshot.is_not(None), ChangeEntry.moved_from.is_not(None)),
        col(ChangeEntry.undone).is_(False),
    )
