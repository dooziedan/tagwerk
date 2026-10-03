"""Scan the music folder and keep the ``track`` table in sync with the files on disk.

Read-only: the scanner never modifies music files.
"""

import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import Session, delete, select

from app.models import Track
from app.tags import FORMATS, FileInfo, read_file

log = logging.getLogger(__name__)

COMMIT_EVERY = 200  # files per database transaction


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


def find_audio_files(music_dir: Path) -> list[Path]:
    """All supported audio files below ``music_dir``, skipping hidden folders like .Trash."""
    files = []
    for root, dirs, names in os.walk(music_dir):
        dirs[:] = sorted(d for d in dirs if not d.startswith((".", "@")))
        files.extend(
            Path(root, name)
            for name in sorted(names)
            if not name.startswith(".") and Path(name).suffix.lower() in FORMATS
        )
    return files


def scan_library(engine: Engine, music_dir: Path, progress: ScanProgress) -> None:
    files = find_audio_files(music_dir)
    progress.total = len(files)
    log.info("Scan started: %d audio files in %s", len(files), music_dir)

    with Session(engine) as session:
        known = {
            row.path: (row.id, row.mtime, row.size)
            for row in session.exec(select(Track.path, Track.id, Track.mtime, Track.size))
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

            existing = known.get(rel)
            if existing and existing[1] == stat.st_mtime and existing[2] == stat.st_size:
                progress.unchanged += 1
            else:
                columns = _read_columns(path, rel, progress)
                columns.update(
                    path=rel,
                    size=stat.st_size,
                    mtime=stat.st_mtime,
                    scanned_at=datetime.now(UTC),
                )
                if existing:
                    track = session.get(Track, existing[0])
                    for key, value in columns.items():
                        setattr(track, key, value)
                    progress.updated += 1
                else:
                    session.add(Track(**columns))
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


def _read_columns(path: Path, rel: str, progress: ScanProgress) -> dict:
    """Tag columns for a file; on a broken file, empty tags plus the error message."""
    try:
        info = read_file(path)
        error = None
    except Exception as exc:  # one broken file must never stop the whole scan
        log.warning("Cannot read %s: %s", rel, exc)
        info = FileInfo(format=FORMATS[path.suffix.lower()])
        error = f"{type(exc).__name__}: {exc}"[:500]
        progress.errors += 1
    return {**info.as_columns(), "error": error}
