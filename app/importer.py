"""Importing inbox tracks into the library: write the tags, then move the file.

Per track (ADR 0007):
1. The values come from the review: the owner's value, else Tagwerk's suggestion, else the file.
2. The destination is checked first: an existing file is never overwritten.
3. Tags are written with a snapshot (app/writer.py), exactly like an applied edit.
4. The file is copied into the library folder, the copy is verified, then the original is
   deleted. **The filename never changes.**
5. The track joins the library database; the import is recorded in the history, and undo
   restores the tags and moves the file back into the inbox.
"""

import hashlib
import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import Session, col, select

from app import genres, identify, naming, preferences, writer
from app.changes import WriteProgress
from app.config import get_settings
from app.duplicates import LibraryIndex
from app.images import ImageStore
from app.inbox import owner_values, review
from app.models import ChangeEntry, ChangeSet, InboxTrack, Track
from app.rawtags import BINARY
from app.scanner import store_file

log = logging.getLogger(__name__)

REQUIRED = ("title", "artist")  # a track can't be imported without these


@dataclass
class ImportPlan:
    track: InboxTrack
    changes: dict[str, str | None]  # fields that change, with their new values
    old: dict[str, str | None]  # the same fields as they are in the file now
    folder: str  # library folder, relative to MUSIC_DIR
    problems: list[str] = field(default_factory=list)  # why it can't be imported
    # The main genre when it has no folder yet: the track goes to _Unsorted, and the Changes
    # page proposes the folder (app/folders.py).
    new_genre: str | None = None

    @property
    def destination(self) -> str:
        """Library path, relative to MUSIC_DIR: the folder plus the unchanged filename."""
        return f"{self.folder}/{Path(self.track.path).name}"


def plan(
    session: Session, track: InboxTrack, music_dir: Path, added: datetime | None = None
) -> ImportPlan:
    """What importing this track would do. ``added``: the import time (for date folders)."""
    prefs = preferences.load(session)
    fields = review(session, track, list(writer.EDITABLE))
    values = {f.field: f.value for f in fields}
    changes = {f.field: f.value for f in fields if f.value != f.in_file}
    old = {f.field: f.in_file for f in fields if f.field in changes}
    mine = owner_values(session, track.id)
    if writer.COVER in mine:  # a new cover, or None to remove it
        changes[writer.COVER] = mine[writer.COVER]
        old[writer.COVER] = writer.current_value(track, writer.COVER)
    elif cover := identify.cover_suggestion(session, track):  # found online, no cover yet
        changes[writer.COVER] = cover.image_id
        old[writer.COVER] = None
    if prefs.remove_traktor_on_import and not track.error:
        owners = writer.private_owners(get_settings().import_dir / track.path)
        if writer.TRAKTOR.removeprefix(writer.PRIVATE) in owners:
            changes[writer.TRAKTOR] = None  # removed while importing; undo puts it back
            old[writer.TRAKTOR] = BINARY
    names = naming.values_for(values, genres.from_text(prefs.genre_map), prefs.key_notation, added)
    existing = naming.existing_folders(music_dir)
    folder = naming.folder(
        prefs.folder_layout, prefs.folder_pattern, names, prefs.genre_folders, existing
    )
    result = ImportPlan(track, changes, old, folder)
    if prefs.folder_layout == "genre" and folder == naming.UNSORTED and names["genre"]:
        result.new_genre = names["genre"]
    if track.error:
        result.problems.append("the file can't be read")
    for name in REQUIRED:
        if not values.get(name):
            result.problems.append(f"needs {writer.EDITABLE[name].lower()}")
    if (music_dir / result.destination).exists():
        result.problems.append(f"{result.destination} already exists in the library")
    return result


# A file must be unchanged for this long before an automatic import: it may still be copying.
STABLE_AFTER = 120  # seconds


def ready_for_auto_import(
    session: Session,
    track: InboxTrack,
    import_dir: Path,
    music_dir: Path,
    now: float,
    library: LibraryIndex,
) -> bool:
    """True when Tagwerk may import this track without asking (automation "auto").

    Only complete tracks: title, artist, genre, BPM, key and cover; every suggestion sure;
    nothing that blocks an import; no likely copy in the library (the owner decides those);
    and the file unchanged for a while (no half downloads).
    """
    if track.error or now - track.mtime < STABLE_AFTER:
        return False
    if plan(session, track, music_dir).problems:
        return False
    fields = review(session, track, list(writer.EDITABLE))
    suggested = [f.suggestion for f in fields if f.origin == "suggested"]
    if any(not s.sure for s in suggested):
        return False
    mine = owner_values(session, track.id)
    online_cover = None if writer.COVER in mine else identify.cover_suggestion(session, track)
    if online_cover and not online_cover.sure:
        return False
    has_cover = mine[writer.COVER] is not None if writer.COVER in mine else track.has_cover
    has_cover = has_cover or online_cover is not None
    values = {f.field: f.value for f in fields}
    if library.matches(track, values["title"], values["artist"], import_dir, music_dir):
        return False
    return has_cover and all(values.get(n) for n in ("title", "artist", "genre", "bpm", "key"))


def import_tracks(
    engine: Engine,
    import_dir: Path,
    music_dir: Path,
    track_ids: list[int],
    progress: WriteProgress,
    images: ImageStore | None = None,
) -> None:
    """Import inbox tracks. Tracks that can't be imported stay in the inbox with a reason."""
    with Session(engine) as session:
        tracks = session.exec(
            select(InboxTrack).where(col(InboxTrack.id).in_(track_ids)).order_by(InboxTrack.path)
        ).all()
        progress.total = len(tracks)
        changeset = ChangeSet(kind="import", tracks=len(tracks), fields="Import")
        session.add(changeset)
        session.commit()
        progress.changeset_id = changeset.id
        labels = set()

        for track in tracks:
            progress.current = track.path
            item = plan(session, track, music_dir)
            entry = ChangeEntry(
                changeset_id=changeset.id,
                path=item.destination,
                changes=json.dumps({k: [item.old[k], v] for k, v in item.changes.items()}),
                moved_from=track.path,
            )
            try:
                if item.problems:
                    raise writer.WriteError(", ".join(item.problems))
                _import_one(session, item, import_dir, music_dir, entry, images)
                labels.update(item.changes)
                progress.written += 1
                changeset.written += 1
            except Exception as exc:
                log.warning("Could not import %s: %s", track.path, exc)
                session.rollback()
                entry.error = str(exc)[:500]
                entry.moved_from = None  # nothing was moved
                progress.failed += 1
                changeset.failed += 1
                progress.errors.append(f"{track.path}: {entry.error}")
            session.add(entry)
            session.add(changeset)
            session.commit()
            progress.processed += 1

        names = [writer.label(f) for f in sorted(labels, key=writer.label_order)]
        changeset.fields = ", ".join(["Import", *names])
        session.add(changeset)
        session.commit()
    progress.current = ""


def _import_one(
    session: Session,
    item: ImportPlan,
    import_dir: Path,
    music_dir: Path,
    entry: ChangeEntry,
    images: ImageStore | None = None,
) -> None:
    track = item.track
    source = import_dir / track.path
    target = music_dir / item.destination
    stat = source.stat()
    if stat.st_mtime != track.mtime or stat.st_size != track.size:
        raise writer.WriteError("the file changed since the inbox was checked; check again")
    if target.exists():
        raise writer.WriteError(
            f"{item.destination} already exists in the library; the file was not renamed "
            "or overwritten"
        )

    snapshot = writer.write(source, item.changes, images) if item.changes else None
    try:
        move_file(source, target)
    except Exception:
        if snapshot:
            writer.undo(source, snapshot)  # leave the inbox file as it was
        raise
    entry.snapshot = json.dumps(snapshot) if snapshot else None

    stat = target.stat()
    library_track = store_file(session, target, item.destination, stat, False, None)
    entry.track_id = library_track.id
    entry.mtime_after = stat.st_mtime
    session.delete(track)


def move_file(source: Path, target: Path) -> None:
    """Copy, verify the copy, then delete the original. The name stays the same.

    /import and /music are usually different shares, so a plain rename isn't possible.
    A half-written copy never appears under the final name.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f".{target.name}.tagwerk-part")
    try:
        shutil.copy2(source, partial)
        if _sha256(partial) != _sha256(source):
            raise writer.WriteError("the copy differs from the original; nothing was moved")
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    source.unlink()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def move_back(session: Session, entry: ChangeEntry, import_dir: Path, music_dir: Path) -> None:
    """Undo of an import: the file goes back to where it was in the inbox."""
    source = music_dir / entry.path
    target = import_dir / entry.moved_from
    if target.exists():
        raise writer.WriteError(f"{entry.moved_from} already exists in the inbox")
    move_file(source, target)
    track = session.get(Track, entry.track_id) if entry.track_id else None
    if track:
        session.delete(track)
    entry.track_id = None
