"""Final tracks: library tracks the owner checked and marked as done (ADR 0012).

- The mark lives only in Tagwerk's database (``finaltrack``); no tag is written for it.
- Final tracks are **locked**: edits skip them until the mark is removed.
- **Renaming** happens only here, only when the owner presses *Mark as final* and has switched
  renaming on (Settings → Final tracks). The new name comes from the filename pattern; the
  folder and the extension stay. Writing tags never renames (CLAUDE.md).
- Before renaming, Navidrome must have scanned the file's current tags: otherwise it can't
  connect the renamed file to its play counts and ratings (app/navidrome.py, scanned_since).
- Marking (with or without renaming) is recorded in the history; undo renames the file back
  and removes the mark. *Remove final mark* asks what to do with the name.
"""

import json
import logging
import os
from dataclasses import dataclass
from pathlib import PurePosixPath

from sqlalchemy import Engine, and_, exists, not_
from sqlmodel import Session, col, select

from app import genres, naming, navidrome, preferences, writer
from app.changes import WriteProgress
from app.config import Settings
from app.library import IS_FINAL, is_missing
from app.models import ChangeEntry, ChangeSet, FinalTrack, PendingChange, Track

log = logging.getLogger(__name__)

# What a track needs before it can be marked as final (shown on the Final check page).
COMPLETE = and_(
    Track.error.is_(None),
    not_(is_missing(Track.title)),
    not_(is_missing(Track.artist)),
    not_(is_missing(Track.genre)),
    Track.bpm.is_not(None),
    Track.key_camelot.is_not(None),
    col(Track.has_cover).is_(True),
)
_PENDING = exists().where(PendingChange.track_id == Track.id)
# Complete, not final yet, and no unwritten edits: ready for the Final check page.
READY = and_(COMPLETE, not_(IS_FINAL), not_(_PENDING))

MAX_NAME = 180  # characters before the extension; shares and players cope with that


class FinalError(Exception):
    """Marking or unmarking can't be done (the message says why)."""


def final_ids(session: Session, track_ids: list[int]) -> set[int]:
    """Which of these tracks are final (locked)."""
    rows = session.exec(select(FinalTrack.track_id).where(col(FinalTrack.track_id).in_(track_ids)))
    return set(rows)


def new_name(session: Session, track: Track) -> str:
    """The filename the pattern gives this track (same extension)."""
    prefs = preferences.load(session)
    values = {f: writer.current_value(track, f) for f in writer.EDITABLE}
    names = naming.values_for(values, genres.from_text(prefs.genre_map), prefs.key_notation)
    suffix = PurePosixPath(track.path).suffix
    name = naming.filename(prefs.filename_pattern, names, suffix)
    stem = name[: -len(suffix)] if suffix else name
    return stem[:MAX_NAME].rstrip(" .-") + suffix


@dataclass
class Plan:
    track: Track
    rename_to: str | None  # new filename, or None when the name stays


def plan(session: Session, track: Track) -> Plan:
    """What *Mark as final* would do with this track."""
    prefs = preferences.load(session)
    current = PurePosixPath(track.path).name
    name = new_name(session, track) if prefs.rename_on_final else current
    return Plan(track, name if name != current else None)


# --- Marking and unmarking (run as background jobs: they may wait for Navidrome) -------------


def mark(engine: Engine, settings: Settings, track_id: int, progress: WriteProgress) -> None:
    """Mark a track as final, renaming it first if the owner switched renaming on."""
    with Session(engine) as session:
        track = session.get(Track, track_id)
        if track is None:
            raise FinalError("That track is no longer in the library")
        if session.get(FinalTrack, track_id):
            raise FinalError("That track is already final")
        if not session.exec(select(Track.id).where(Track.id == track_id, COMPLETE)).first():
            raise FinalError("The track isn't complete (title, artist, genre, BPM, key, cover)")
        if session.exec(select(PendingChange).where(PendingChange.track_id == track_id)).first():
            raise FinalError("The track has pending changes: apply or discard them first")
        stat = (settings.music_dir / track.path).stat()
        if stat.st_mtime != track.mtime or stat.st_size != track.size:
            raise FinalError("The file changed since the last scan: scan the library first")
        item = plan(session, track)
        progress.total, progress.current = 1, track.path
        old_path = track.path
        changeset = ChangeSet(
            kind="final",
            tracks=1,
            fields="Marked as final" + (", renamed" if item.rename_to else ""),
        )
        session.add(changeset)
        session.commit()
        progress.changeset_id = changeset.id
        entry = ChangeEntry(
            changeset_id=changeset.id,
            track_id=track.id,
            path=old_path,
            changes=json.dumps({"final": [None, "final"]}),
            moved_from=old_path,  # undo removes the mark (and renames back if renamed)
        )
        try:
            if item.rename_to:
                _rename(settings, session, track, item.rename_to)
                entry.path = track.path
            stat = (settings.music_dir / track.path).stat()
            entry.mtime_after = stat.st_mtime
            name_before = PurePosixPath(old_path).name if item.rename_to else None
            session.add(FinalTrack(track_id=track.id, mtime=track.mtime, name_before=name_before))
            changeset.written = progress.written = 1
        except Exception as exc:
            session.rollback()
            entry.error = str(exc)[:500]
            entry.moved_from = None
            changeset.failed = progress.failed = 1
            progress.errors.append(f"{old_path}: {entry.error}")
        renamed = entry.path != old_path
        session.add(entry)
        session.add(changeset)
        session.commit()
        progress.processed = 1
    progress.current = ""
    navidrome.rescan_after_write(settings, 1 if renamed else 0)  # only a new name is news


def unmark(
    engine: Engine, settings: Settings, track_id: int, name: str | None, progress: WriteProgress
) -> None:
    """Remove the final mark. ``name``: the new filename, or None to keep the current one."""
    with Session(engine) as session:
        track = session.get(Track, track_id)
        final = session.get(FinalTrack, track_id)
        if track is None or final is None:
            raise FinalError("That track isn't final")
        progress.total, progress.current = 1, track.path
        old_path = track.path
        current = PurePosixPath(track.path).name
        name = _checked_name(name, current) if name else None
        changeset = ChangeSet(
            kind="final",
            tracks=1,
            fields="Final mark removed" + (", renamed" if name and name != current else ""),
        )
        session.add(changeset)
        session.commit()
        progress.changeset_id = changeset.id
        entry = ChangeEntry(
            changeset_id=changeset.id,
            track_id=track.id,
            path=old_path,
            changes=json.dumps({"final": ["final", None]}),
        )
        try:
            if name and name != current:
                _rename(settings, session, track, name)
                entry.path = track.path
            session.delete(final)
            changeset.written = progress.written = 1
        except Exception as exc:
            session.rollback()
            entry.error = str(exc)[:500]
            changeset.failed = progress.failed = 1
            progress.errors.append(f"{old_path}: {entry.error}")
        renamed = entry.path != old_path
        session.add(entry)
        session.add(changeset)
        session.commit()
        progress.processed = 1
    progress.current = ""
    navidrome.rescan_after_write(settings, 1 if renamed else 0)  # only a new name is news


def undo(session: Session, entry: ChangeEntry, settings: Settings) -> None:
    """Undo of *Mark as final*: the old name comes back and the mark goes."""
    track = session.get(Track, entry.track_id) if entry.track_id else None
    if track is None:
        raise FinalError("The track is no longer in the library")
    if entry.moved_from != track.path:
        _rename(settings, session, track, PurePosixPath(entry.moved_from).name)
    final = session.get(FinalTrack, track.id)
    if final:
        session.delete(final)


def _checked_name(name: str, current: str) -> str:
    """A typed filename, made safe; the extension always stays the same."""
    suffix = PurePosixPath(current).suffix
    stem = naming.render(name.removesuffix(suffix), {}) if name.strip() else ""
    if not stem:
        raise FinalError("Type a filename")
    return stem[:MAX_NAME] + suffix


def _rename(settings: Settings, session: Session, track: Track, name: str) -> None:
    """Rename a library file in its folder (with a .lrc of the same name). Never overwrites.

    Waits until Navidrome has scanned the file's current tags first (see module docstring).
    """
    music_dir = settings.music_dir
    source = music_dir / track.path
    target = source.with_name(name)
    if target.exists() and target != source:
        raise FinalError(f"{name} already exists in that folder; nothing was renamed")
    lyrics, lyrics_target = source.with_suffix(".lrc"), target.with_suffix(".lrc")
    if lyrics.exists() and lyrics_target.exists() and lyrics_target != lyrics:
        raise FinalError(f"{lyrics_target.name} already exists; nothing was renamed")
    ready = navidrome.scanned_since(settings, source.stat().st_mtime)
    if not ready.ok:
        raise FinalError(f"Not renamed: {ready.message}")
    os.rename(source, target)
    if lyrics.exists():
        os.rename(lyrics, lyrics_target)
    track.path = target.relative_to(music_dir).as_posix()
    session.add(track)
    log.info("Renamed %s to %s", source.name, name)
