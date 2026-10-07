"""Scan the music folder and keep the ``track`` table in sync with the files on disk.

Read-only: the scanner never modifies music files.
"""

import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from glob import escape as glob_escape
from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import Session, delete, select

from app.models import RawTag, Track
from app.rawtags import RawField
from app.tags import FORMATS, FileInfo, read_file

log = logging.getLogger(__name__)

COMMIT_EVERY = 200  # files per database transaction

# Bump this whenever the tag reader learns new fields: rows from older versions are then
# re-read once on the next scan, even if the file itself didn't change.
#   1 = v0.2 (basic tags)   2 = v0.3 (DJ fields, lyrics, OGG/Opus)   3 = v0.4 (raw tag fields)
#   4 = v0.8.3 (private ID3 frames named by their owner, without their data)
#   5 = v0.9 (Discogs release and artist IDs)
SCAN_VERSION = 5


@dataclass
class ScanProgress:
    """Live counters, read by the UI while a scan runs."""

    total: int = 0  # audio files found
    processed: int = 0
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0
    errors: int = 0
    current: str = ""  # file being read right now


def find_files(music_dir: Path) -> tuple[list[Path], set[Path]]:
    """Supported audio files below ``music_dir``, and .lrc lyrics files (without extension).

    Hidden files and folders (.Trash, macOS ._ files) and @ folders are skipped.
    """
    audio, lyrics = [], set()
    for root, dirs, names in os.walk(music_dir):
        dirs[:] = sorted(d for d in dirs if not d.startswith((".", "@")))
        for name in sorted(names):
            if name.startswith("."):
                continue
            suffix = Path(name).suffix.lower()
            if suffix in FORMATS:
                audio.append(Path(root, name))
            elif suffix == ".lrc":
                lyrics.add(Path(root, name).with_suffix(""))
    return audio, lyrics


def scan_library(engine: Engine, music_dir: Path, progress: ScanProgress) -> None:
    files, lrc_files = find_files(music_dir)
    progress.total = len(files)
    log.info("Scan started: %d audio files in %s", len(files), music_dir)

    with Session(engine) as session:
        known = {
            row.path: row
            for row in session.exec(
                select(
                    Track.path,
                    Track.id,
                    Track.mtime,
                    Track.size,
                    Track.scan_version,
                    Track.has_lrc,
                    Track.error,
                )
            )
        }
        seen: set[str] = set()

        for i, path in enumerate(files, 1):
            rel = path.relative_to(music_dir).as_posix()
            progress.current = rel
            seen.add(rel)
            try:
                stat = path.stat()
            except OSError as exc:  # vanished or unreadable since the folder walk
                log.warning("Cannot access %s: %s", rel, exc)
                progress.errors += 1
                progress.processed = i
                continue

            has_lrc = path.with_suffix("") in lrc_files
            existing = known.get(rel)
            up_to_date = (
                existing is not None
                and existing.mtime == stat.st_mtime
                and existing.size == stat.st_size
                and existing.scan_version >= SCAN_VERSION
                and existing.error is None  # files that failed are retried on every scan
            )
            if up_to_date and existing.has_lrc == has_lrc:
                progress.unchanged += 1
            elif up_to_date:
                # Only a .lrc file was added or removed: no need to read the audio file.
                session.get(Track, existing.id).has_lrc = has_lrc
                progress.updated += 1
            else:
                store_file(
                    session, path, rel, stat, has_lrc, existing.id if existing else None, progress
                )
                if existing:
                    progress.updated += 1
                else:
                    progress.added += 1

            progress.processed = i
            if i % COMMIT_EVERY == 0:
                session.commit()

        gone = [path for path in known if path not in seen]
        for start in range(0, len(gone), 500):  # SQLite limits the number of query parameters
            session.exec(delete(Track).where(Track.path.in_(gone[start : start + 500])))
        progress.removed = len(gone)
        session.commit()

    progress.current = ""
    log.info("Scan finished: %s", progress)


def store_file(
    session: Session,
    path: Path,
    rel: str,
    stat: os.stat_result,
    has_lrc: bool,
    track_id: int | None,
    progress: ScanProgress | None = None,
) -> Track:
    """Read one file and save it as a Track row with its raw tag fields (insert or update)."""
    columns, raw = _read_file(path, rel, progress or ScanProgress())
    columns.update(
        path=rel,
        size=stat.st_size,
        mtime=stat.st_mtime,
        has_lrc=has_lrc,
        scan_version=SCAN_VERSION,
        scanned_at=datetime.now(UTC),
    )
    if track_id is not None:
        track = session.get(Track, track_id)
        for key, value in columns.items():
            setattr(track, key, value)
        session.exec(delete(RawTag).where(RawTag.track_id == track.id))
    else:
        track = Track(**columns, added_at=datetime.fromtimestamp(stat.st_mtime, UTC))
        session.add(track)
        session.flush()  # assigns track.id
    session.add_all(
        RawTag(track_id=track.id, system=f.system, name=f.name, value=f.value) for f in raw
    )
    return track


def refresh_track(session: Session, music_dir: Path, track: Track) -> Track:
    """Re-read one track's file after Tagwerk wrote to it."""
    path = music_dir / track.path
    has_lrc = any(
        p.suffix.lower() == ".lrc" for p in path.parent.glob(glob_escape(path.stem) + ".*")
    )
    return store_file(session, path, track.path, path.stat(), has_lrc, track.id)


def _read_file(path: Path, rel: str, progress: ScanProgress) -> tuple[dict, list[RawField]]:
    """Track columns and raw tag fields; for a broken file, empty tags plus the error."""
    try:
        info = read_file(path)
        error = None
    except Exception as exc:  # one broken file must never stop the whole scan
        log.warning("Cannot read %s: %s", rel, exc)
        info = FileInfo(format=FORMATS[path.suffix.lower()])
        error = f"{type(exc).__name__}: {exc}"[:500]
        progress.errors += 1
    return {**info.as_columns(), "error": error}, info.raw
