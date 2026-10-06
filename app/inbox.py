"""The import inbox: new music in IMPORT_DIR, waiting to be tagged and moved into the library.

Step 1 (v0.7) only reads: it keeps the ``inboxtrack`` table in sync with the files in the
inbox folder and shows what each track is missing. Proposals, writing and moving follow.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import Session, func, select

from app import analysis, genres, identify, writer
from app.models import InboxTrack, InboxValue
from app.proposals import Proposal, propose
from app.scanner import ScanProgress, find_files
from app.tags import FORMATS, read_file

log = logging.getLogger(__name__)


def scan_inbox(engine: Engine, import_dir: Path, progress: ScanProgress) -> None:
    """Read new and changed files in the inbox; forget files that are gone. Read-only."""
    files, _ = find_files(import_dir)
    progress.total = len(files)
    with Session(engine) as session:
        known = {t.path: t for t in session.exec(select(InboxTrack))}
        seen = set()
        for path in files:
            rel = path.relative_to(import_dir).as_posix()
            seen.add(rel)
            progress.current = rel
            try:
                stat = path.stat()
            except OSError:  # removed while scanning
                progress.processed += 1
                continue
            row = known.get(rel)
            if row and row.mtime == stat.st_mtime and row.size == stat.st_size:
                progress.unchanged += 1
            else:
                _store(session, path, rel, stat, row)
                if row:
                    progress.updated += 1
                else:
                    progress.added += 1
            progress.processed += 1
        for rel, row in known.items():
            if rel not in seen:
                session.delete(row)
                progress.removed += 1
        session.commit()
    progress.current = ""
    log.info(
        "Inbox scan: %d added, %d updated, %d removed",
        progress.added,
        progress.updated,
        progress.removed,
    )


def _store(session: Session, path: Path, rel: str, stat, row: InboxTrack | None) -> None:
    try:
        info = read_file(path)
        values = {k: v for k, v in info.as_columns().items() if k in InboxTrack.model_fields}
    except Exception as exc:  # a broken file is listed as unreadable, not skipped
        log.warning("Could not read %s: %s", rel, exc)
        values = {"format": FORMATS[path.suffix.lower()], "error": str(exc)[:500] or "unreadable"}
    if row is None:
        row = InboxTrack(path=rel, size=stat.st_size, mtime=stat.st_mtime, **values)
    else:
        for name in InboxTrack.model_fields:
            if name not in ("id", "path", "found_at"):
                setattr(row, name, values.get(name, InboxTrack.model_fields[name].default))
        row.size, row.mtime = stat.st_size, stat.st_mtime
        row.scanned_at = datetime.now(UTC)
    session.add(row)


def missing(track: InboxTrack) -> list[str]:
    """What a track still lacks before it is ready for the library (in display order)."""
    if track.error:
        return ["Unreadable"]
    checks = {
        "Title": track.title,
        "Artist": track.artist,
        "Genre": track.genre,
        "BPM": track.bpm,
        "Key": track.key_camelot,
        "Cover": track.has_cover,
    }
    return [name for name, value in checks.items() if not value]


def inbox_count(session: Session) -> int:
    return session.exec(select(func.count(InboxTrack.id))).one()


# --- Review: the value each field will get on import ------------------------------------------


@dataclass
class ReviewField:
    field: str
    label: str
    value: str | None  # what the field will be on import
    origin: str  # "file" (unchanged), "suggested" or "you"
    in_file: str | None  # the value in the file now
    suggestion: Proposal | None


def owner_values(session: Session, track_id: int) -> dict[str, str | None]:
    rows = session.exec(select(InboxValue).where(InboxValue.track_id == track_id))
    return {r.field: r.value for r in rows}


def suggestions(session: Session, track: InboxTrack) -> dict[str, Proposal]:
    """Tagwerk's suggestions per field: from the file and filename first, then from online
    sources for fields still empty (app/identify.py). BPM and key from the audio replace
    both: they were decided together with them (app/analysis.py)."""
    local = {p.field: p for p in propose(track, genres.active(session))}
    online = identify.suggestions(session, track, taken=set(local))
    found = local | {p.field: p for p in online}
    mine = owner_values(session, track.id)
    genre = (
        mine["genre"]
        if "genre" in mine
        else (found["genre"].value if "genre" in found else track.genre)
    )
    return found | {p.field: p for p in analysis.proposals(session, track, genre)}


def review(session: Session, track: InboxTrack, order: list[str]) -> list[ReviewField]:
    """Every editable field: the owner's value, else Tagwerk's suggestion, else the file's."""
    suggestions_ = suggestions(session, track)
    mine = owner_values(session, track.id)
    result = []
    for name in order:
        in_file = writer.current_value(track, name)
        suggestion = suggestions_.get(name)
        if name in mine:
            value, origin = mine[name], "you"
        elif suggestion:
            value, origin = suggestion.value, "suggested"
        else:
            value, origin = in_file, "file"
        result.append(ReviewField(name, writer.EDITABLE[name], value, origin, in_file, suggestion))
    return result


def save_values(session: Session, track: InboxTrack, typed: dict[str, str]) -> dict[str, str]:
    """Store what the owner typed on the review page. Returns errors per field (nothing saved).

    A value equal to the suggestion (or, without one, to the file) is not stored: the field
    then simply follows the suggestion again.
    """
    values, errors = {}, {}
    for name, raw in typed.items():
        try:
            values[name] = writer.normalize(name, raw)
        except ValueError as exc:
            errors[name] = str(exc)
    if errors:
        return errors
    suggested = {name: p.value for name, p in suggestions(session, track).items()}
    stored = {
        r.field: r for r in session.exec(select(InboxValue).where(InboxValue.track_id == track.id))
    }
    for name, value in values.items():
        default = suggested.get(name, writer.current_value(track, name))
        row = stored.get(name)
        if value == default:
            if row:
                session.delete(row)
        elif row:
            row.value = value
            session.add(row)
        else:
            session.add(InboxValue(track_id=track.id, field=name, value=value))
    session.commit()
    return {}


def set_cover(session: Session, track: InboxTrack, image_id: str | None) -> None:
    """The cover to write on import: an image from the ImageStore, or None to remove it."""
    row = session.exec(
        select(InboxValue).where(InboxValue.track_id == track.id, InboxValue.field == "cover")
    ).first()
    if image_id is None and not track.has_cover:  # nothing to remove
        if row:
            session.delete(row)
    elif row:
        row.value = image_id
        session.add(row)
    else:
        session.add(InboxValue(track_id=track.id, field="cover", value=image_id))
    session.commit()


def reset_values(session: Session, track_id: int) -> None:
    for row in session.exec(select(InboxValue).where(InboxValue.track_id == track_id)):
        session.delete(row)
    session.commit()
