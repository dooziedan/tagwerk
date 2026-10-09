"""Edits from saving to writing: pending changes, applying them, and undoing applied changes.

The flow (ADR 0003): edit -> **pending** (database only) -> **review** -> **apply** (snapshot
first, then write) -> **undo** from the snapshot. Files are only written by apply() and undo().
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import Engine, and_, exists, not_, or_
from sqlmodel import Session, col, delete, func, select

from app import duplicates, writer
from app.images import ImageStore
from app.models import ChangeEntry, ChangeSet, FinalTrack, PendingChange, RawTag, Track
from app.rawtags import BINARY
from app.scanner import refresh_track

if TYPE_CHECKING:
    from app.config import Settings

log = logging.getLogger(__name__)


# Final tracks are locked against edits (app/final.py).
_NOT_FINAL = ~exists().where(FinalTrack.track_id == Track.id)


# --- Staging --------------------------------------------------------------------------------

# Where a changed value came from (recorded since v0.11; Statistics: "Tagwerk's work").
SOURCES = {
    "you": "You",
    "audio": "From the audio",
    "online": "Found online",
    "filename": "From the filename",
    "clean-up": "Clean-up (spelling, spacing)",
    "fix-ids": "Fix IDs",
    "private-data": "Private data removed",
    "genre-merge": "Genre spellings merged",
    "mix-names": "Mix names capitalised",
    "copy": "From another copy",
    "duplicates": "Duplicates page",
}


def stage(
    session: Session, track_ids: list[int], values: dict[str, str | None], source: str = "you"
) -> tuple[int, dict[str, str]]:
    """Save edits as pending changes for the given tracks.

    ``values`` maps editable fields to the typed value ("" or None removes the field).
    Returns (number of pending changes, errors per field). With any error nothing is saved.
    A value equal to the current one removes that field's pending change instead.
    Final tracks are locked: they are skipped (app/final.py), and so are fields a track's
    format can't hold (writer.supports: Opus has no ReplayGain peaks). ``source``: where the
    values came from (a key of SOURCES); a pending change saved again unchanged keeps its source.
    """
    normalized: dict[str, str | None] = {}
    errors: dict[str, str] = {}
    for name, raw in values.items():
        try:
            normalized[name] = writer.normalize(name, raw)
        except ValueError as exc:
            errors[name] = str(exc)
    if errors:
        return 0, errors

    count = 0
    for track in session.exec(select(Track).where(col(Track.id).in_(track_ids), _NOT_FINAL)):
        for name, new in normalized.items():
            if not writer.supports(track.format, name):
                continue
            old = writer.current_value(track, name)
            existing = session.exec(
                select(PendingChange).where(
                    PendingChange.track_id == track.id, PendingChange.field == name
                )
            ).first()
            if new == old:
                if existing:
                    session.delete(existing)
                continue
            if existing:
                if existing.new_value != new:
                    existing.source = source
                existing.new_value = new
                existing.created_at = datetime.now(UTC)
            else:
                session.add(
                    PendingChange(
                        track_id=track.id, field=name, old_value=old, new_value=new, source=source
                    )
                )
            count += 1
    session.commit()
    return count, {}


def stage_private_removal(session: Session, owner: str) -> int:
    """Pending changes that remove one program's private ID3 data (e.g. Traktor's) from every
    file that has it, as found at the last scan. Final tracks are skipped. Returns how many."""
    field = writer.PRIVATE + owner
    has_it = exists().where(
        RawTag.track_id == Track.id, RawTag.system == "id3", RawTag.name == f"PRIV:{owner}"
    )
    already = exists().where(PendingChange.track_id == Track.id, PendingChange.field == field)
    count = 0
    for track in session.exec(select(Track).where(has_it, not_(already), _NOT_FINAL)):
        session.add(
            PendingChange(
                track_id=track.id,
                field=field,
                old_value=BINARY,
                new_value=None,
                source="private-data",
            )
        )
        count += 1
    session.commit()
    return count


def stage_cover(
    session: Session, track_ids: list[int], image_id: str | None, source: str = "you"
) -> int:
    """Save a cover art change: an image from the ImageStore, or None to remove the cover."""
    count = 0
    for track in session.exec(select(Track).where(col(Track.id).in_(track_ids), _NOT_FINAL)):
        existing = session.exec(
            select(PendingChange).where(
                PendingChange.track_id == track.id, PendingChange.field == writer.COVER
            )
        ).first()
        if image_id is None and not track.has_cover:
            if existing:
                session.delete(existing)
            continue
        if existing:
            if existing.new_value != image_id:
                existing.source = source
            existing.new_value = image_id
            existing.created_at = datetime.now(UTC)
        else:
            session.add(
                PendingChange(
                    track_id=track.id,
                    field=writer.COVER,
                    old_value=writer.current_value(track, writer.COVER),
                    new_value=image_id,
                    source=source,
                )
            )
        count += 1
    session.commit()
    return count


@dataclass
class PendingTrack:
    track: Track
    changes: list[PendingChange]


def pending(session: Session, change_ids: list[int] | None = None) -> list[PendingTrack]:
    """Pending changes grouped by track; ``change_ids``: only these (the ticked ones)."""
    query = (
        select(PendingChange, Track)
        .join(Track, col(Track.id) == PendingChange.track_id)
        .order_by(Track.path, PendingChange.id)
    )
    if change_ids is not None:
        query = query.where(col(PendingChange.id).in_(change_ids))
    rows = session.exec(query).all()
    grouped: dict[int, PendingTrack] = {}
    for change, track in rows:
        grouped.setdefault(track.id, PendingTrack(track, [])).changes.append(change)
    for item in grouped.values():
        item.changes.sort(key=lambda c: writer.label_order(c.field))
    return list(grouped.values())


def pending_count(session: Session) -> int:
    return session.exec(select(func.count(PendingChange.id))).one()


def discard(session: Session, change_ids: list[int] | None = None) -> None:
    """Remove these pending changes, or all of them."""
    query = delete(PendingChange)
    if change_ids is not None:
        query = query.where(col(PendingChange.id).in_(change_ids))
    session.exec(query)
    session.commit()


# --- Applying and undoing (run as background jobs) ------------------------------------------


@dataclass
class WriteProgress:
    action: str = "apply"  # apply, import or undo
    total: int = 0  # files
    processed: int = 0
    written: int = 0
    failed: int = 0
    current: str = ""
    changeset_id: int | None = None
    errors: list[str] = field(default_factory=list)  # "path: reason"
    trashed: int = 0  # copies moved to the library trash (queued on the Duplicates page)
    # An apply's ticked changes (None: all pending ones): the Changes page leaves them out while
    # they are being written, so they don't show up again after the list burnt away.
    change_ids: list[int] | None = None


def apply_pending(
    engine: Engine,
    music_dir: Path,
    progress: WriteProgress,
    images: ImageStore | None = None,
    change_ids: list[int] | None = None,
) -> None:
    """Write pending changes: all of them, or only ``change_ids`` (the ticked ones; the others
    stay pending). Failed files keep their pending changes for another try.

    Copies queued on the Duplicates page go to the library trash afterwards (their other
    pending changes aren't written: the file leaves the library). Trash moves aren't part of
    the change set; the trash is their record, with Restore (ADR 0023, ADR 0027).
    """
    with Session(engine) as session:
        items = pending(session, change_ids)
        progress.total = len(items)
        trashed = [i for i in items if any(c.field == writer.TRASH for c in i.changes)]
        items = [i for i in items if i not in trashed]
        if items:
            _write_items(session, music_dir, progress, images, items)
        for item in trashed:
            _trash_item(session, music_dir, progress, item)
    progress.current = ""


def _trash_item(session: Session, music_dir: Path, progress: WriteProgress, item) -> None:
    """Move one queued copy to the library trash; it stays queued if that's not possible."""
    track = item.track
    progress.current = track.path
    keep = next(c.new_value for c in item.changes if c.field == writer.TRASH)
    try:
        duplicates.trash_copy(session, music_dir, track.id, int(keep or 0))
        progress.trashed += 1
    except Exception as exc:
        log.warning("Could not move %s to the trash: %s", track.path, exc)
        session.rollback()
        progress.failed += 1
        progress.errors.append(f"{track.path}: {str(exc)[:500]}")
    progress.processed += 1


def _write_items(session: Session, music_dir: Path, progress, images, items) -> None:
    """Write the tag changes of these tracks, as one change set."""
    fields = sorted({c.field for item in items for c in item.changes}, key=writer.label_order)
    labels = [writer.label(f) for f in fields]
    changeset = ChangeSet(tracks=len(items), fields=", ".join(labels))
    session.add(changeset)
    session.commit()
    progress.changeset_id = changeset.id

    for item in items:
        track = item.track
        progress.current = track.path
        values = {c.field: c.new_value for c in item.changes}
        entry = ChangeEntry(
            changeset_id=changeset.id,
            track_id=track.id,
            path=track.path,
            changes=json.dumps({c.field: [c.old_value, c.new_value] for c in item.changes}),
            sources=sources_json({c.field: c.source for c in item.changes}),
        )
        try:
            path = music_dir / track.path
            stat = path.stat()
            if stat.st_mtime != track.mtime or stat.st_size != track.size:
                raise writer.WriteError(
                    "the file changed since the last scan; scan again, then apply"
                )
            snapshot = writer.write(path, values, images)
            entry.snapshot = json.dumps(snapshot)
            refreshed = refresh_track(session, music_dir, track)
            entry.mtime_after = refreshed.mtime
            raw = {r.name for r in session.exec(select(RawTag).where(RawTag.track_id == track.id))}
            mismatch = _verify(refreshed, values, snapshot["system"], raw)
            if mismatch:
                entry.error = "written, but reads back differently: " + mismatch
            for change in item.changes:
                session.delete(change)
            progress.written += 1
            changeset.written += 1
        except Exception as exc:
            log.warning("Could not write %s: %s", track.path, exc)
            session.rollback()
            entry.error = str(exc)[:500]
            progress.failed += 1
            changeset.failed += 1
            progress.errors.append(f"{track.path}: {entry.error}")
        session.add(entry)
        session.commit()
        progress.processed += 1


def sources_json(sources: dict[str, str | None]) -> str | None:
    """A ChangeEntry's ``sources``: only the known ones; None when none is known."""
    known = {k: v for k, v in sources.items() if v}
    return json.dumps(known) if known else None


def _verify(track: Track, values: dict[str, str | None], system: str, raw: set[str]) -> str:
    """Compare what the file now says with what was written (``raw``: its raw field names)."""
    problems = []
    for name, expected in values.items():
        if name.startswith(writer.PRIVATE):
            if f"PRIV:{name.removeprefix(writer.PRIVATE)}" in raw:
                problems.append(f"{writer.label(name)} is still there")
            continue
        if name == writer.COVER:
            if track.has_cover != (expected is not None):
                problems.append("Cover art " + ("is missing" if expected else "is still there"))
            continue
        if expected is not None and name == "bpm" and system in ("id3", "mp4"):
            expected = str(round(float(expected)))  # stored as an integer in these formats
        actual = writer.current_value(track, name)
        if actual != expected:
            problems.append(f"{writer.label(name)} is {actual!r}, expected {expected!r}")
    return "; ".join(problems)


def undo_changeset(
    engine: Engine,
    music_dir: Path,
    changeset_id: int,
    progress: WriteProgress,
    images: ImageStore | None = None,
    import_dir: Path | None = None,
    settings: "Settings | None" = None,
) -> None:
    """Restore the files of one applied ChangeSet from their snapshots.

    A file that changed again after the change was applied is skipped, so newer edits
    (from Tagwerk or another tool) are never overwritten. Imported files also move back
    into the inbox; files moved into a new genre folder go back to _Unsorted.
    """
    from app import convert, final, folders  # these import app.changes themselves
    from app.config import get_settings
    from app.importer import move_back

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
                if entry.snapshot:
                    writer.undo(path, json.loads(entry.snapshot), images)
                if entry.moved_from and changeset.kind == "convert":
                    convert.undo(session, entry, settings)
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


HISTORY_PAGE = 50


def history(session: Session, limit: int = HISTORY_PAGE, page: int = 1) -> list[ChangeSet]:
    """Applied change sets, newest first; ``page`` 2 is the next 50 older ones."""
    return list(
        session.exec(
            select(ChangeSet)
            .order_by(ChangeSet.applied_at.desc())
            .offset((max(1, page) - 1) * limit)
            .limit(limit)
        ).all()
    )


def history_pages(session: Session) -> int:
    total = session.exec(select(func.count(ChangeSet.id))).one()
    return max(1, -(-total // HISTORY_PAGE))


def entries(session: Session, changeset_id: int) -> list[ChangeEntry]:
    return list(
        session.exec(
            select(ChangeEntry)
            .where(ChangeEntry.changeset_id == changeset_id)
            .order_by(ChangeEntry.path)
        ).all()
    )
