"""New genre folders: proposed on the Changes page, created only after the owner's OK (ADR 0010).

With the genre layout, an imported track whose main genre has no folder yet goes to
``_Unsorted``. This module groups the tracks in ``_Unsorted`` by main genre and proposes one
change per genre: "create Rock/ and move these files into it". Applying it
1. creates the folder (if it isn't there yet),
2. moves the files with their exact filenames (and a .lrc lyrics file next to a track),
3. adds the genre to the owner's main genres (if they ticked any), so later imports go there.
Everything is recorded in the history, and undo moves the files back.
"""

import json
import logging
import os
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

from sqlalchemy import Engine
from sqlmodel import Session, col, select

from app import genres, naming, preferences, writer
from app.changes import WriteProgress
from app.models import ChangeEntry, ChangeSet, Track

log = logging.getLogger(__name__)


@dataclass
class Move:
    track: Track
    target: str  # new path, relative to MUSIC_DIR


@dataclass
class FolderProposal:
    genre: str  # main genre, e.g. "Rock"
    folder: str  # the folder to move into, relative to MUSIC_DIR
    exists: bool  # the folder is already there (only the files move)
    moves: list[Move]


def proposals(session: Session, music_dir: Path) -> list[FolderProposal]:
    """One proposal per main genre of the tracks in _Unsorted (genre layout only)."""
    prefs = preferences.load(session)
    if prefs.folder_layout != "genre":
        return []
    genre_map = genres.from_text(prefs.genre_map)
    allowed = prefs.genre_folders or naming.existing_folders(music_dir)
    kept = {g.lower() for g in prefs.kept_unsorted}
    unsorted = PurePosixPath(naming.UNSORTED)
    found: dict[str, FolderProposal] = {}
    query = select(Track).where(col(Track.path).startswith(f"{naming.UNSORTED}/"))
    for track in session.exec(query.order_by(Track.path)):
        path = PurePosixPath(track.path)
        genre = naming.main_genre(track.genre, genre_map)
        if path.parent != unsorted or not genre or genre.lower() in kept:
            continue  # only files right in _Unsorted, with a genre the owner didn't keep there
        proposal = found.get(genre.lower())
        if proposal is None:
            spelling = naming.genre_folder(genre, allowed) or genre  # as the folder is spelled
            folder = naming.folder("genre", "", {"genre": spelling}, [spelling])
            if folder == naming.UNSORTED:
                continue  # a genre that makes no folder name, e.g. "?"
            proposal = FolderProposal(genre, folder, (music_dir / folder).is_dir(), [])
            found[genre.lower()] = proposal
        proposal.moves.append(Move(track, f"{proposal.folder}/{path.name}"))
    return sorted(found.values(), key=lambda p: (-len(p.moves), p.genre.lower()))


def proposal_count(session: Session, music_dir: Path) -> int:
    return len(proposals(session, music_dir))


def keep_unsorted(session: Session, genre: str | None) -> None:
    """Don't propose a folder for this genre any more; None proposes all of them again."""
    prefs = preferences.load(session)
    kept = [*prefs.kept_unsorted, genre] if genre else []
    preferences.save(session, replace(prefs, kept_unsorted=list(dict.fromkeys(kept))))


def create_folder(engine: Engine, music_dir: Path, genre: str, progress: WriteProgress) -> None:
    """Apply the proposal for one genre: create the folder and move the files into it."""
    with Session(engine) as session:
        proposal = next(
            (p for p in proposals(session, music_dir) if p.genre.lower() == genre.lower()), None
        )
        if proposal is None:
            raise writer.WriteError(f"there are no tracks to move into a {genre} folder")
        prefs = preferences.load(session)
        target = music_dir / proposal.folder
        details = {"folder": proposal.folder, "created": not target.is_dir(), "added_genre": None}
        if prefs.genre_folders and not naming.genre_folder(proposal.genre, prefs.genre_folders):
            details["added_genre"] = proposal.genre  # later imports go to the new folder too
            preferences.save(
                session, replace(prefs, genre_folders=[*prefs.genre_folders, proposal.genre])
            )
        target.mkdir(exist_ok=True)

        verb = "New folder" if details["created"] else "Moved into"
        changeset = ChangeSet(
            kind="folder",
            tracks=len(proposal.moves),
            fields=f"{verb} {proposal.folder}",
            details=json.dumps(details),
        )
        session.add(changeset)
        session.commit()
        progress.total = len(proposal.moves)
        progress.changeset_id = changeset.id

        for move in proposal.moves:
            track = move.track
            progress.current = track.path
            entry = ChangeEntry(
                changeset_id=changeset.id,
                track_id=track.id,
                path=move.target,
                changes=json.dumps({"folder": [naming.UNSORTED, proposal.folder]}),
                moved_from=track.path,
            )
            try:
                _move(music_dir, track.path, move.target)
                track.path = move.target
                entry.mtime_after = (music_dir / move.target).stat().st_mtime
                session.add(track)
                progress.written += 1
                changeset.written += 1
            except Exception as exc:
                log.warning("Could not move %s: %s", track.path, exc)
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
    progress.current = ""


def move_back(session: Session, entry: ChangeEntry, music_dir: Path) -> None:
    """Undo of one moved file: back to where it was, and the track's path with it."""
    _move(music_dir, entry.path, entry.moved_from)
    track = session.get(Track, entry.track_id) if entry.track_id else None
    if track:
        track.path = entry.moved_from
        session.add(track)


def finish_undo(session: Session, changeset: ChangeSet, music_dir: Path) -> None:
    """After every file moved back: remove the folder Tagwerk created (if it's empty) and the
    genre it added to the main genres."""
    details = json.loads(changeset.details or "{}")
    folder = music_dir / details.get("folder", "")
    if details.get("created") and folder != music_dir and folder.is_dir():
        try:
            folder.rmdir()  # only removes an empty folder: files someone added there stay
        except OSError:
            log.info("Kept %s: it isn't empty", folder)
    added = details.get("added_genre")
    if added:
        prefs = preferences.load(session)
        rest = [g for g in prefs.genre_folders if g.lower() != added.lower()]
        preferences.save(session, replace(prefs, genre_folders=rest))


def _move(music_dir: Path, old: str, new: str) -> None:
    """Move a file inside the library; the name stays the same. Never overwrites anything.

    Both places are on the same share, so this is a rename: the file's contents are not
    rewritten. A .lrc lyrics file with the same name moves along.
    """
    source, target = music_dir / old, music_dir / new
    if target.exists():
        raise writer.WriteError(f"{new} already exists; nothing was moved or overwritten")
    lyrics, lyrics_target = source.with_suffix(".lrc"), target.with_suffix(".lrc")
    if lyrics.exists() and lyrics_target.exists():
        raise writer.WriteError(f"{lyrics_target.name} already exists; nothing was moved")
    target.parent.mkdir(parents=True, exist_ok=True)
    os.rename(source, target)
    if lyrics.exists():
        try:
            os.rename(lyrics, lyrics_target)
        except OSError:
            os.rename(target, source)  # all or nothing: the track goes back to its lyrics
            raise
