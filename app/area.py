"""The Releasomat area: the folder inside the library where Releasomat, the owner's playlist
downloader, saves its downloads (ADR 0044).

**Optional.** Tagwerk works in full without Releasomat: with no ``RELEASOMAT_FOLDER`` and no
confirmed folder, nothing here does anything, and no page mentions Releasomat.

The area is a discovery folder, not part of the curated library. Once the owner confirmed it
(Settings → Releasomat, "Keep this folder out of the library"), the library scan skips it: its
files get no ``track`` rows, so nothing in Tagwerk can tag, rename, move, trash or count them.
Only the confirmed folder is skipped. This module never touches a file: it only checks the
folder's name and counts what leaves Tagwerk's lists.
"""

from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

from sqlalchemy import func, or_
from sqlmodel import Session, col, select

from app import naming, preferences, trash
from app.config import Settings
from app.models import DuplicateTrack, FinalTrack, PendingChange, SecretTrack, Track
from app.preferences import Preferences
from app.scanner import in_folder

# The pending change that queues a copy for the library trash (app.writer.TRASH).
_TRASH = "trash"


class FolderProblem(Exception):
    """The folder can't be the Releasomat area (the message says why, in plain words)."""


def proposed(settings: Settings) -> str:
    """The folder the container settings name (``RELEASOMAT_FOLDER``), as typed; empty when
    none is set."""
    return settings.releasomat_folder.strip()


def confirmed(prefs: Preferences) -> str:
    """The folder the owner confirmed to keep out of the library; empty: none."""
    return prefs.releasomat_area


def skipped(prefs: Preferences) -> tuple[str, ...]:
    """The folders the library scan leaves out (relative to MUSIC_DIR): the confirmed one."""
    return (prefs.releasomat_area,) if prefs.releasomat_area else ()


def configured(settings: Settings, prefs: Preferences) -> bool:
    """True when the owner set Releasomat up at all: only then does Settings show it."""
    return bool(proposed(settings) or confirmed(prefs))


def contains(prefs: Preferences, path: str) -> bool:
    """True when ``path`` (relative to MUSIC_DIR) is inside the confirmed area."""
    return any(in_folder(path, folder) for folder in skipped(prefs))


def check_folder(name: str, settings: Settings, prefs: Preferences) -> str:
    """The folder's path relative to MUSIC_DIR (``/`` between folders), after the checks: a
    folder inside the library that exists, isn't hidden, isn't ``_Unsorted``, isn't the whole
    library and isn't a ticked main genre. Raises FolderProblem with the reason."""
    text = name.strip().replace("\\", "/")
    if not text:
        raise FolderProblem("No folder is set.")
    music_dir = settings.music_dir
    path = PurePosixPath(text)
    if path.is_absolute():  # "/music/Releasomat" is fine, a folder elsewhere isn't
        try:
            path = path.relative_to(music_dir.as_posix())
        except ValueError:
            raise FolderProblem(f"{text} isn't inside the music folder ({music_dir}).") from None
    parts = [part for part in path.parts if part not in ("", ".")]
    if not parts:
        raise FolderProblem("That is the whole music folder, not a folder inside it.")
    if ".." in parts:
        raise FolderProblem(f"{text} points outside the music folder.")
    if any(part.startswith((".", "@")) for part in parts):
        raise FolderProblem(f"{text} is a hidden folder: Tagwerk never reads those anyway.")
    folder = "/".join(parts)
    if parts[0] == naming.UNSORTED:
        raise FolderProblem(f"{naming.UNSORTED} is where imports wait for their genre folder.")
    if len(parts) == 1 and folder.lower() in {g.lower() for g in prefs.genre_folders}:
        raise FolderProblem(f"{folder} is one of your genre folders (Settings → Import).")
    if not (music_dir / folder).is_dir():
        raise FolderProblem(f"There is no folder {folder} in the music folder ({music_dir}).")
    return folder


@dataclass
class Precheck:
    """What leaves Tagwerk's lists when the folder is kept out of the library. The files
    themselves stay where they are."""

    folder: str
    tracks: int = 0
    with_changes: int = 0  # tracks with pending changes (they go with the tracks)
    final: int = 0  # tracks marked final
    secret: int = 0  # tracks marked secret
    duplicate_groups: int = 0  # groups with a copy in the folder
    trash_kept_here: int = 0  # library copies queued for the trash, keeping a copy in the folder
    in_library_trash: int = 0  # library-trash entries that came from the folder

    @property
    def marks(self) -> int:
        return self.with_changes + self.final + self.secret + self.duplicate_groups


def precheck(session: Session, music_dir: Path, folder: str) -> Precheck:
    """Count what keeping ``folder`` out would take out of the library lists."""
    ids = area_track_ids(session, folder)
    result = Precheck(folder, tracks=len(ids))
    result.in_library_trash = sum(in_folder(d.path, folder) for d in trash.items(music_dir))
    if not ids:
        return result
    for start in range(0, len(ids), 500):  # SQLite limits the number of query parameters
        chunk = ids[start : start + 500]
        result.with_changes += _count(
            session,
            select(func.count(func.distinct(PendingChange.track_id))).where(
                col(PendingChange.track_id).in_(chunk), PendingChange.field != _TRASH
            ),
        )
        result.final += _count(
            session, select(func.count()).where(col(FinalTrack.track_id).in_(chunk))
        )
        result.secret += _count(
            session, select(func.count()).where(col(SecretTrack.track_id).in_(chunk))
        )
        result.trash_kept_here += _count(
            session,
            select(func.count()).where(
                PendingChange.field == _TRASH,
                col(PendingChange.new_value).in_([str(i) for i in chunk]),
            ),
        )
    groups = session.exec(
        select(DuplicateTrack.group_id, DuplicateTrack.track_id)
    ).all()  # a few hundred rows at most
    in_area = set(ids)
    result.duplicate_groups = len({group for group, track in groups if track in in_area})
    return result


def area_track_ids(session: Session, folder: str) -> list[int]:
    """Library rows inside ``folder`` (before the first scan that skips it)."""
    query = select(Track.id).where(
        or_(Track.path == folder, col(Track.path).startswith(f"{folder}/"))
    )
    return list(session.exec(query))


def keep_out(session: Session, settings: Settings, name: str) -> str:
    """The owner's click: keep this folder out of the library from the next scan on. Only the
    folder ``RELEASOMAT_FOLDER`` names can be confirmed. Returns the folder."""
    prefs = preferences.load(session)
    if name.strip() != proposed(settings):
        raise FolderProblem("The Releasomat folder changed meanwhile: check the numbers again.")
    folder = check_folder(name, settings, prefs)
    preferences.save(session, replace(prefs, releasomat_area=folder))
    return folder


def treat_as_library(session: Session) -> None:
    """Undo keep_out(): the next scan reads the folder's files into the library again."""
    preferences.save(session, replace(preferences.load(session), releasomat_area=""))


def overview(session: Session, settings: Settings, prefs: Preferences) -> dict:
    """What Settings → Releasomat shows: the folder, its check, and the numbers before the
    click. ``configured`` False: Settings shows nothing about Releasomat."""
    folder = proposed(settings)
    found = {
        "configured": configured(settings, prefs),
        "music_dir": settings.music_dir.as_posix(),  # for showing full paths: /music/…
        "proposed": folder,
        "confirmed": confirmed(prefs),
        "problem": None,
        "folder": None,  # the proposed folder after its checks
        "precheck": None,
    }
    if not folder:
        return found
    try:
        found["folder"] = check_folder(folder, settings, prefs)
    except FolderProblem as exc:
        found["problem"] = str(exc)
        return found
    if found["folder"] != found["confirmed"]:
        found["precheck"] = precheck(session, settings.music_dir, found["folder"])
    return found


def _count(session: Session, query) -> int:
    return session.exec(query).one() or 0
