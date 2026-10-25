"""The Releasomat area: the folder inside the library where Releasomat, the owner's playlist
downloader, saves its downloads (ADR 0044).

**Optional.** Tagwerk works in full without Releasomat: with no ``RELEASOMAT_FOLDER``, no
``RELEASOMAT_URL`` and no confirmed folder, nothing here does anything, and no page mentions
Releasomat.

The folder is ``RELEASOMAT_FOLDER`` when set, else the one Releasomat reports (``info``),
remembered so scans and Settings still know it while Releasomat is down.

The area is a discovery folder, not part of the curated library. Once the owner confirmed it
(Settings → Releasomat, "Keep this folder out of the library"), the library scan skips it: its
files get no ``track`` rows, so nothing in Tagwerk can tag, rename, move, trash or count them.
Only the confirmed folder is skipped. This module never touches a file: it only checks the
folder's name and counts what leaves Tagwerk's lists.
"""

import json
import logging
import unicodedata
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from sqlalchemy import Engine, delete, func, or_
from sqlmodel import Session, col, select

from app import naming, preferences, releasomat, trash
from app.config import Settings
from app.models import (
    AppSetting,
    ChangeEntry,
    ChangeSet,
    DuplicateTrack,
    FinalTrack,
    InboxTrack,
    PendingChange,
    ReleasomatAdoption,
    ReleasomatFile,
    SecretTrack,
    Track,
)
from app.preferences import Preferences
from app.scanner import ScanProgress, find_files, in_folder
from app.tags import FORMATS, read_file

log = logging.getLogger(__name__)

# The pending change that queues a copy for the library trash (app.writer.TRASH).
_TRASH = "trash"
# The folder Releasomat reported last (an ``appsetting`` row, not a preference: the owner
# doesn't choose it).
_REPORTED = "releasomat_reported_folder"


class FolderProblem(Exception):
    """The folder can't be the Releasomat area (the message says why, in plain words)."""


def proposed(settings: Settings, session: Session) -> str:
    """The Releasomat folder as named: ``RELEASOMAT_FOLDER`` (as typed), else the one
    Releasomat reported last; empty when neither is known."""
    return settings.releasomat_folder.strip() or reported(session)


def reported(session: Session) -> str:
    """The folder Releasomat reported last (``GET info``), relative to Navidrome's music folder."""
    row = session.get(AppSetting, _REPORTED)
    return json.loads(row.value) if row else ""


def remember_reported(session: Session, folder: str) -> None:
    folder = unicodedata.normalize("NFC", folder.strip())
    if folder != reported(session):
        session.merge(AppSetting(key=_REPORTED, value=json.dumps(folder)))
        session.commit()


def confirmed(prefs: Preferences) -> str:
    """The folder the owner confirmed to keep out of the library; empty: none."""
    return prefs.releasomat_area


def skipped(prefs: Preferences) -> tuple[str, ...]:
    """The folders the library scan leaves out (relative to MUSIC_DIR): the confirmed one."""
    return (prefs.releasomat_area,) if prefs.releasomat_area else ()


def configured(settings: Settings, prefs: Preferences) -> bool:
    """True when the owner set Releasomat up at all: only then does Settings show it."""
    named = settings.releasomat_folder.strip() or settings.releasomat_url.strip()
    return bool(named or confirmed(prefs))


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
    if name.strip() != proposed(settings, session):
        raise FolderProblem("The Releasomat folder changed meanwhile: check the numbers again.")
    folder = check_folder(name, settings, prefs)
    if folder != prefs.releasomat_area:
        session.exec(delete(ReleasomatFile))  # paths of another folder: read it again
    preferences.save(session, replace(prefs, releasomat_area=folder))
    return folder


def treat_as_library(session: Session) -> None:
    """Undo keep_out(): the next scan reads the folder's files into the library again."""
    session.exec(delete(ReleasomatFile))  # they become library tracks
    preferences.save(session, replace(preferences.load(session), releasomat_area=""))


def area_dir(settings: Settings, prefs: Preferences) -> Path | None:
    """The folder kept out of the library, on disk; None while there is none."""
    return settings.music_dir / prefs.releasomat_area if prefs.releasomat_area else None


def sync(engine: Engine, settings: Settings, paths: list[str] | None = None) -> ScanProgress:
    """Keep the ``releasomatfile`` table in step with the area folder (like the inbox check):
    new and changed files are read, files that are gone are forgotten. ``paths``: only these
    (relative to the area), e.g. after a Delete. Read-only for the files."""
    progress = ScanProgress()
    with Session(engine) as session:
        root = area_dir(settings, preferences.load(session))
        if root is None:
            return progress
        if not root.is_dir():  # unmounted or removed: keep what is known, change nothing
            log.warning("Releasomat folder not found: %s", root)
            return progress
        query = select(ReleasomatFile)
        if paths is None:
            files = find_files(root)[0]
        else:
            files = [root / p for p in paths if (root / p).is_file()]
            query = query.where(col(ReleasomatFile.path).in_(paths))
        known = {row.path: row for row in session.exec(query)}
        progress.total = len(files)
        seen = set()
        for path in files:
            rel = path.relative_to(root).as_posix()
            seen.add(rel)
            try:
                stat = path.stat()
            except OSError:  # removed while reading
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
    if progress.added or progress.updated or progress.removed:
        log.info("Releasomat folder: %d added, %d updated, %d removed", progress.added,
                 progress.updated, progress.removed)  # fmt: skip
    return progress


@dataclass
class Adopted:
    """One adoption and where its file is now (the Releasomat page's Adopted tab)."""

    record: ReleasomatAdoption
    where: str  # inbox, library, discarded, returned, gone
    link: str | None = None  # its inbox or library page
    path: str | None = None  # where it is now, if known

    @property
    def playlists(self) -> list[str]:
        return json.loads(self.record.playlists or "[]")


WHERE = {
    "inbox": "In the Inbox",
    "library": "In your library",
    "discarded": "Thrown away in the Inbox",
    "returned": "Back in the Releasomat folder (the move failed)",
    "gone": "Gone from the Inbox",
}


def adopted(session: Session, settings: Settings) -> list[Adopted]:
    """Every adoption, newest first, with where the file is now: thrown away or back in the
    area (stored), in the inbox (the file is there: also after an import was undone, before the
    inbox check lists it again), imported into the library (an import or better copy from its
    inbox path after the adoption, not undone), else gone (removed by hand). A few queries for
    all of them."""
    records = list(session.exec(select(ReleasomatAdoption).order_by(
        ReleasomatAdoption.adopted_at.desc(), ReleasomatAdoption.id.desc())))  # fmt: skip
    paths = list({r.inbox_path for r in records})
    in_inbox: dict[str, int] = {}
    imported: dict[str, list[tuple]] = {}
    for start in range(0, len(paths), 500):  # SQLite limits the number of parameters
        part = paths[start : start + 500]
        for track_id, path in session.exec(
            select(InboxTrack.id, InboxTrack.path).where(col(InboxTrack.path).in_(part))
        ):
            in_inbox[path] = track_id
        moves = (
            select(
                ChangeEntry.moved_from, ChangeEntry.track_id, ChangeEntry.path,
                ChangeSet.applied_at,
            )
            .join(ChangeSet, ChangeSet.id == ChangeEntry.changeset_id)
            .where(
                col(ChangeEntry.moved_from).in_(part),
                col(ChangeSet.kind).in_(["import", "upgrade"]),
                col(ChangeEntry.undone).is_(False),
                ChangeEntry.error.is_(None),
            )
        )  # fmt: skip
        for moved_from, track_id, path, applied_at in session.exec(moves):
            imported.setdefault(moved_from, []).append((applied_at, track_id, path))
    found = []
    for record in records:
        if record.state in ("discarded", "returned"):
            found.append(Adopted(record, record.state))
        elif (settings.import_dir / record.inbox_path).is_file():
            track_id = in_inbox.get(record.inbox_path)
            link = f"/inbox/{track_id}" if track_id else "/inbox"
            found.append(Adopted(record, "inbox", link, record.inbox_path))
        elif later := [m for m in imported.get(record.inbox_path, [])
                       if _utc(m[0]) >= _utc(record.adopted_at)]:  # fmt: skip
            _at, track_id, path = max(later, key=lambda m: _utc(m[0]))
            link = f"/tracks/{track_id}" if track_id else None
            found.append(Adopted(record, "library", link, path))
        else:
            found.append(Adopted(record, "gone"))
    return found


def _utc(when: datetime) -> datetime:
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def _store(session: Session, path: Path, rel: str, stat, row: ReleasomatFile | None) -> None:
    """Read one area file's tags (what the Releasomat page shows) into its row."""
    try:
        columns = read_file(path).as_columns()
        values = {k: v for k, v in columns.items() if k in ReleasomatFile.model_fields}
        values["error"] = None
    except Exception as exc:  # a broken file is listed as unreadable, not skipped
        log.warning("Could not read %s: %s", rel, exc)
        values = {"format": FORMATS[path.suffix.lower()], "error": str(exc)[:500] or "unreadable"}
    if row is None:
        row = ReleasomatFile(path=rel, size=stat.st_size, mtime=stat.st_mtime, **values)
    else:
        for name in ReleasomatFile.model_fields:
            if name not in ("id", "path", "found_at"):
                setattr(row, name, values.get(name, ReleasomatFile.model_fields[name].default))
        row.size, row.mtime = stat.st_size, stat.st_mtime
        row.scanned_at = datetime.now(UTC)
    session.add(row)


def overview(session: Session, settings: Settings, prefs: Preferences) -> dict:
    """What Settings → Releasomat shows: the folder, its check, and the numbers before the
    click. ``configured`` False: Settings shows nothing about Releasomat."""
    folder = proposed(settings, session)
    found = {
        "configured": configured(settings, prefs),
        "music_dir": settings.music_dir.as_posix(),  # for showing full paths: /music/…
        "proposed": folder,
        "named_by": "RELEASOMAT_FOLDER" if settings.releasomat_folder.strip() else "Releasomat",
        "url": settings.releasomat_url.strip(),
        "connected": releasomat.configured(settings),
        "last": releasomat.last,
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


def test_connection(session: Session, settings: Settings) -> releasomat.Result:
    """Settings → Releasomat → Test: ask Releasomat who it is and which files it has, remember
    the folder it reports, and check that Tagwerk finds those files in the folder."""
    try:
        about = releasomat.info(settings)
        folder, found = releasomat.files(settings)
    except releasomat.ReleasomatError as exc:
        return releasomat.remember(releasomat.Result(False, exc.message))
    remember_reported(session, folder or about.folder)
    message = f"Connected to Releasomat {about.version}. It saves into “{about.folder}”."
    named = proposed(settings, session)
    try:
        here = check_folder(named, settings, preferences.load(session))
    except FolderProblem as exc:
        return releasomat.remember(releasomat.Result(False, f"{message} {exc}"))
    seen, total = file_match(settings.music_dir / here, found)
    where = f"{settings.music_dir.as_posix()}/{here}"
    if total and not seen:
        return releasomat.remember(releasomat.Result(False, (
            f"{message} None of its {releasomat_files(total)} are in {where}: if Tagwerk's music "
            "folder maps somewhere else than Navidrome's, set RELEASOMAT_FOLDER."
        )))  # fmt: skip
    return releasomat.remember(
        releasomat.Result(True, f"{message} {seen} of {releasomat_files(total)} found in {where}.")
    )


def file_match(folder: Path, found: list[releasomat.AreaFile]) -> tuple[int, int]:
    """How many of Releasomat's files are in ``folder`` with the size Releasomat reports."""
    seen = 0
    for item in found:
        try:
            seen += (folder / item.path).stat().st_size == item.size
        except OSError:
            continue
    return seen, len(found)


def releasomat_files(count: int) -> str:
    return f"{count:,} Releasomat file{'' if count == 1 else 's'}"


def _count(session: Session, query) -> int:
    return session.exec(query).one() or 0
