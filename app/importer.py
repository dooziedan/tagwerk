"""Importing inbox tracks into the library: write the tags, then move the file.

Per track (ADR 0007):
1. The values come from the review: the owner's value, else Tagwerk's suggestion, else the file.
2. The destination is checked first: an existing file is never overwritten.
3. Tags are written with a snapshot (app/writer.py), exactly like an applied edit.
   MusicBrainz fields holding other values (e.g. Discogs numbers) are fixed (app/ids.py).
   IDs found online fill ID fields that are still empty (app/identify.py, ADR 0032).
4. The file is copied into the library folder, the copy is verified, then the original is
   deleted. **The filename never changes.**
5. The track joins the library database; the import is recorded in the history, and undo
   restores the tags and moves the file back into the inbox.

**Files adopted from Releasomat** (ADR 0044) go the other way round when Navidrome is set up
(ADR 0046): Navidrome knows a moved file as the same song only by tags like title and album, so
changing them in the same step would make a new song and leave the old one (with its plays, stars
and place in playlists) behind as missing. So the file moves first, with the tags it has; then
Navidrome scans (once for all such files of an import) and lists it at its new place; only then
are the new tags written there, and the usual rescan follows. If Navidrome doesn't confirm within
3 minutes, the tags are written anyway: the import never waits for good or fails over it.
"""

import hashlib
import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from sqlalchemy import Engine
from sqlmodel import Session, col, select

from app import (
    analysis,
    area,
    genres,
    identify,
    ids,
    naming,
    navidrome,
    preferences,
    secret,
    writer,
)
from app.changes import WriteProgress, sources_json
from app.config import Settings, get_settings
from app.duplicates import LibraryIndex
from app.images import ImageStore
from app.inbox import add_file, adoptions_for, owner_values, review
from app.models import (
    ChangeEntry,
    ChangeSet,
    InboxTrack,
    SecretInboxTrack,
    SecretTrack,
    Track,
)
from app.rawtags import BINARY
from app.scanner import store_file

log = logging.getLogger(__name__)

REQUIRED = ("title", "artist")  # a track can't be imported without these


@dataclass
class ImportPlan:
    track: InboxTrack
    changes: dict[str, str | None]  # fields that change, with their new values
    old: dict[str, str | None]  # the same fields as they are in the file now
    sources: dict[str, str]  # where each new value came from (app.changes.SOURCES)
    folder: str  # library folder, relative to MUSIC_DIR
    problems: list[str] = field(default_factory=list)  # why it can't be imported
    # The main genre when it has no folder yet: the track goes to _Unsorted, and the Changes
    # page proposes the folder (app/folders.py).
    new_genre: str | None = None
    # Values in MusicBrainz fields that aren't MusicBrainz IDs: fixed on import (app/ids.py).
    wrong_ids: list[ids.WrongId] = field(default_factory=list)
    # IDs found online that the import writes: (field, value, why), ADR 0032.
    found_ids: list[tuple[str, str, str]] = field(default_factory=list)

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
    sources = {
        f.field: "you" if f.origin == "you" else f.suggestion.source
        for f in fields
        if f.field in changes and (f.origin == "you" or f.suggestion)
    }
    mine = owner_values(session, track.id)
    if writer.COVER in mine:  # a new cover, or None to remove it
        changes[writer.COVER] = mine[writer.COVER]
        old[writer.COVER] = writer.current_value(track, writer.COVER)
        sources[writer.COVER] = "you"
    elif cover := identify.cover_suggestion(session, track):  # found online, no cover yet
        changes[writer.COVER] = cover.image_id
        old[writer.COVER] = None
        sources[writer.COVER] = "online"
    if prefs.remove_traktor_on_import and not track.error:
        owners = writer.private_owners(get_settings().import_dir / track.path)
        if writer.TRAKTOR.removeprefix(writer.PRIVATE) in owners:
            changes[writer.TRAKTOR] = None  # removed while importing; undo puts it back
            old[writer.TRAKTOR] = BINARY
            sources[writer.TRAKTOR] = "private-data"
    found = None if track.error else ids.in_file(get_settings().import_dir / track.path)
    if found:  # e.g. Discogs numbers in MusicBrainz fields: they move to their own fields
        for name, new in ids.fixes(found).items():
            changes[name] = writer.normalize(name, new)
            old[name] = getattr(found, name)
            sources[name] = "fix-ids"
    found_ids = _online_ids(session, track, fields, mine, changes)
    for name, (value, source, _why) in found_ids.items():
        changes[name], old[name], sources[name] = value, None, source
    names = naming.values_for(values, genres.of(prefs), prefs.key_notation, added)
    existing = naming.existing_folders(music_dir, area.skipped(prefs))
    folder = naming.folder(
        prefs.folder_layout, prefs.folder_pattern, names, prefs.genre_folders, existing
    )
    result = ImportPlan(track, changes, old, sources, folder)
    result.wrong_ids = ids.wrong_ids(found) if found else []
    result.found_ids = [(name, value, why) for name, (value, _, why) in found_ids.items()]
    if prefs.folder_layout == "genre" and folder == naming.UNSORTED and names["genre"]:
        result.new_genre = names["genre"]
    if track.error:
        result.problems.append("the file can't be read")
    for name in REQUIRED:
        if not values.get(name):
            result.problems.append(f"needs {writer.EDITABLE[name].lower()}")
    if (music_dir / result.destination).exists():
        result.problems.append(f"{result.destination} already exists in the library")
    if area.contains(prefs, result.destination):  # never into the folder kept out (ADR 0044)
        result.problems.append("it would land in the Releasomat folder: change the folder pattern")
    return result


def _online_ids(
    session: Session, track: InboxTrack, fields: list, mine: dict, changes: dict
) -> dict[str, tuple[str, str, str]]:
    """IDs found online for ID fields that are empty once the import's ID fixes are done:
    the owner's ("Use these values") and the sure ones. {field: (value, source, why)}.

    The file is only read when there is an ID to write (inbox tracks don't keep every ID).
    """
    if track.error:
        return {}
    # The album, label and catalog number the track gets, if they can be trusted: its own tags,
    # the owner's values or sure suggestions (identify.id_suggestions).
    context = {}
    for f in fields:
        if f.field in identify.CONTEXT:
            trusted = f.origin in ("file", "you") or (f.suggestion and f.suggestion.sure)
            context[f.field] = f.value if trusted else f.in_file
    wanted = {
        name: (value, "you", "you took this result over")
        for name, value in mine.items()
        if name in writer.IDS and value
    }
    for p in identify.id_suggestions(session, track, {}, context, taken=set(wanted)):
        wanted[p.field] = (p.value, "online", p.reason)
    if not wanted:
        return {}
    in_file = ids.file_ids(get_settings().import_dir / track.path)
    if in_file is None:
        return {}
    now = in_file | {name: changes[name] for name in writer.IDS if name in changes}
    return {name: found for name, found in wanted.items() if not now.get(name)}


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

    Only complete tracks: title, artist, genre, BPM, key and cover (secret tracks need no
    cover, app/secret.py); every suggestion sure;
    nothing that blocks an import; no likely copy in the library (the owner decides those);
    the file unchanged for a while (no half downloads); and its audio analysed.
    """
    if track.error or now - track.mtime < STABLE_AFTER:
        return False
    if analysis.result(session, track.id) is None:
        return False  # wait for BPM and key from the audio (right after the inbox check)
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
    cover_done = has_cover or secret.is_secret(session, track.id, inbox=True)
    values = {f.field: f.value for f in fields}
    if library.matches(track, values["title"], values["artist"], import_dir, music_dir):
        return False
    return cover_done and all(values.get(n) for n in ("title", "artist", "genre", "bpm", "key"))


def import_tracks(
    engine: Engine,
    import_dir: Path,
    music_dir: Path,
    track_ids: list[int],
    progress: WriteProgress,
    images: ImageStore | None = None,
    settings: Settings | None = None,
) -> None:
    """Import inbox tracks. Tracks that can't be imported stay in the inbox with a reason.

    Adopted files with tags to write are moved first; their tags follow one Navidrome scan for
    all of them (see the module docstring).
    """
    settings = settings or get_settings()  # Navidrome, for adopted files
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
        two_steps = _two_steps(session, settings, tracks)
        moved: list[tuple[ImportPlan, ChangeEntry]] = []  # adopted, waiting for Navidrome

        for track in tracks:
            progress.current = track.path
            item = plan(session, track, music_dir)
            entry = ChangeEntry(
                changeset_id=changeset.id,
                path=item.destination,
                changes=json.dumps({k: [item.old[k], v] for k, v in item.changes.items()}),
                sources=sources_json(item.sources),
                moved_from=track.path,
            )
            try:
                if item.problems:
                    raise writer.WriteError(", ".join(item.problems))
                if track.id in two_steps and item.changes:
                    _move_first(item, import_dir, music_dir)
                    moved.append((item, entry))
                    continue  # its tags and its History entry follow Navidrome's scan, below
                _import_one(session, item, import_dir, music_dir, entry, images)
                _done(item, progress, changeset, labels)
            except Exception as exc:
                _failed(session, entry, exc, progress, changeset)
            _save(session, changeset, entry, progress)

        if moved:  # one scan for all of them, then their tags
            progress.current = "Waiting for Navidrome's scan"
            files = [_as_navidrome_sees(item) for item, _ in moved]
            try:
                result, listed = navidrome.wait_until_listed(settings, files)
            except Exception as exc:  # the files are moved: their tags must follow anyway
                log.exception("Waiting for Navidrome failed")
                result, listed = navidrome.Result(False, str(exc)), [None] * len(files)
            log.info("Before tagging %d adopted track(s): %s", len(moved), result.message)
            for (item, entry), seen in zip(moved, listed, strict=True):
                progress.current = item.destination
                entry.details = json.dumps(_navidrome_note(result, seen))
                try:
                    _tags_after_move(session, item, import_dir, music_dir, entry, images)
                    _done(item, progress, changeset, labels)
                except Exception as exc:
                    _failed(session, entry, exc, progress, changeset)
                _save(session, changeset, entry, progress)

        names = [writer.label(f) for f in sorted(labels, key=writer.label_order)]
        changeset.fields = ", ".join(["Import", *names])
        session.add(changeset)
        session.commit()
    progress.current = ""


def _two_steps(session: Session, settings: Settings, tracks: list[InboxTrack]) -> set[int]:
    """The tracks adopted from Releasomat: imported in two steps when Navidrome is set up."""
    if not navidrome.configured(settings):
        return set()
    adopted = adoptions_for(session, [t.path for t in tracks])
    return {t.id for t in tracks if t.path in adopted}


def _done(item: ImportPlan, progress: WriteProgress, changeset: ChangeSet, labels: set) -> None:
    labels.update(item.changes)
    progress.written += 1
    changeset.written += 1


def _failed(
    session: Session, entry: ChangeEntry, exc: Exception, progress: WriteProgress,
    changeset: ChangeSet,
) -> None:  # fmt: skip
    path = entry.moved_from  # the inbox path
    log.warning("Could not import %s: %s", path, exc)
    session.rollback()
    entry.error = str(exc)[:500]
    entry.moved_from = None  # nothing was moved
    progress.failed += 1
    changeset.failed += 1
    progress.errors.append(f"{path}: {entry.error}")


def _save(
    session: Session, changeset: ChangeSet, entry: ChangeEntry, progress: WriteProgress
) -> None:
    session.add(entry)
    session.add(changeset)
    session.commit()
    progress.processed += 1


def _import_one(
    session: Session,
    item: ImportPlan,
    import_dir: Path,
    music_dir: Path,
    entry: ChangeEntry,
    images: ImageStore | None = None,
) -> None:
    """The usual import: write the tags in the inbox, then move the file."""
    source, target = _checked(item, import_dir, music_dir)
    snapshot = writer.write(source, item.changes, images) if item.changes else None
    try:
        move_file(source, target)
    except Exception:
        if snapshot:
            writer.undo(source, snapshot)  # leave the inbox file as it was
        raise
    _into_library(session, item, target, entry, snapshot)


def _move_first(item: ImportPlan, import_dir: Path, music_dir: Path) -> None:
    """Step 1 of an adopted file's import (ADR 0046): it moves with the tags it has."""
    source, target = _checked(item, import_dir, music_dir)
    move_file(source, target)


def _tags_after_move(
    session: Session,
    item: ImportPlan,
    import_dir: Path,
    music_dir: Path,
    entry: ChangeEntry,
    images: ImageStore | None = None,
) -> None:
    """Step 3 of an adopted file's import: the new tags go into the file at its library place.
    If writing fails, the file goes back into the inbox as it was, like a failed import."""
    source = import_dir / item.track.path
    target = music_dir / item.destination
    try:
        snapshot = writer.write(target, item.changes, images)
    except Exception as exc:
        try:
            move_file(target, source)  # same time and size: the inbox list still knows it
        except Exception as back:
            raise writer.WriteError(
                f"{exc}; moving it back into the inbox failed too ({back}): it is in the "
                "library with its old tags"
            ) from exc
        raise
    _into_library(session, item, target, entry, snapshot)


def _as_navidrome_sees(item: ImportPlan) -> navidrome.Moved:
    """The adopted file as Navidrome lists it after step 1: still with the inbox file's tags."""
    name = PurePosixPath(item.track.path)
    title = item.track.title or name.stem  # Navidrome's title for a file without one
    return navidrome.Moved(title, item.track.size, name.suffix.lstrip(".").lower())


def _navidrome_note(result: navidrome.Result, listed: bool | None) -> dict:
    """For the History: how an adopted file's import went (ADR 0046)."""
    if not result.ok:
        return {"navidrome": "unconfirmed", "why": result.message}
    return {"navidrome": {True: "listed", False: "unlisted", None: "scanned"}[listed]}


def _checked(item: ImportPlan, import_dir: Path, music_dir: Path) -> tuple[Path, Path]:
    """(inbox file, library place), after checking that the move can be done."""
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
    return source, target


def _into_library(
    session: Session, item: ImportPlan, target: Path, entry: ChangeEntry, snapshot: dict | None
) -> None:
    """The moved file joins the library database; the inbox track goes."""
    track = item.track
    entry.snapshot = json.dumps(snapshot) if snapshot else None
    stat = target.stat()
    library_track = store_file(session, target, item.destination, stat, False, None)
    # The file keeps its download date; the library counts it from now (library growth).
    library_track.added_at = datetime.now(UTC)
    entry.track_id = library_track.id
    entry.mtime_after = stat.st_mtime
    analysis.copy_to_library(session, track.id, library_track.id)  # same sound, no new analysis
    if secret.is_secret(session, track.id, inbox=True):  # the mark moves with the track
        session.add(SecretTrack(track_id=library_track.id))
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
    """Undo of an import: the file goes back to where it was in the inbox.

    A secret track is read into the inbox list at once and keeps its mark, so the inbox
    check that follows doesn't take it for a new file and look it up online.
    """
    source = music_dir / entry.path
    target = import_dir / entry.moved_from
    if target.exists():
        raise writer.WriteError(f"{entry.moved_from} already exists in the inbox")
    move_file(source, target)
    track = session.get(Track, entry.track_id) if entry.track_id else None
    if track and secret.is_secret(session, track.id):
        inbox_track = add_file(session, import_dir, entry.moved_from)
        session.add(SecretInboxTrack(track_id=inbox_track.id))
    if track:
        session.delete(track)
    entry.track_id = None
