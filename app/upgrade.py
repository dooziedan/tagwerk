"""Better copies: an inbox file that sounds better than the same track in the library takes the
library copy's place (ADR 0037).

Finding them (read-only):
- The inbox track must be a likely copy of a library track (app/duplicates.py: same
  MusicBrainz recording, or same artist and title with about the same length). The identical
  file is never better.
- It must sound **clearly** better than every copy it matches: lossless instead of lossy, a
  higher bit depth or sample rate (and neither lower), or for lossy files at least
  MIN_BITRATE_GAIN times the bitrate (256 → 320 kbps counts, 320 → 320 VBR doesn't).
- The copy it replaces is the matching copy with the best sound (then the most tags): the one
  the Duplicates page would keep.

Replacing (a write job, only when the owner presses **Replace**, or on its own when the owner
switched on automatic replacing):
1. The library copy's tags are written into the inbox file (with a snapshot): the library is
   the owner's master. Fields the library copy lacks get the inbox file's values (the same
   values an import would write). ReplayGain isn't copied: it belongs to the old audio.
2. The new file gets the old file's folder and name, with its own extension
   ("Artist - Title.mp3" → "Artist - Title.flac").
3. The old file goes to the library trash (app/trash.py), then the new one is copied into the
   library, verified, and removed from the inbox.
4. The track keeps its database row: its added date, final mark, secret mark and history stay.
   BPM and key from the inbox file's analysis come along; loudness is measured again later.
5. Undo (History) moves the new file back into the inbox with its old tags and restores the old
   file from the trash, as long as the trash wasn't emptied.
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from sqlalchemy import Engine
from sqlmodel import Session, col, delete, select

from app import analysis, navidrome, trash, writer
from app.changes import WriteProgress, sources_json
from app.config import Settings
from app.covers import embedded_cover
from app.duplicates import COMPARED, LibraryIndex, Match, is_lossless, quality, sound
from app.ids import file_ids
from app.images import ImageStore
from app.importer import STABLE_AFTER, move_file
from app.importer import plan as import_plan
from app.inbox import review
from app.models import (
    ChangeEntry,
    ChangeSet,
    FinalTrack,
    InboxTrack,
    LibraryLoudness,
    PendingChange,
    Track,
)
from app.scanner import store_file

log = logging.getLogger(__name__)

# Lossy files: the new bitrate must be at least this much higher (192 → 256 and 256 → 320 count;
# 320 kbps against a 320 kbps VBR file doesn't).
MIN_BITRATE_GAIN = 1.2


def better(new: Track | InboxTrack, old: Track | InboxTrack) -> str | None:
    """Why ``new`` sounds clearly better than ``old``, in words; None when it doesn't."""
    if is_lossless(new) and not is_lossless(old):
        return "lossless instead of lossy"
    if is_lossless(new) and is_lossless(old):
        new_res = (new.bits_per_sample or 0, new.sample_rate or 0)
        old_res = (old.bits_per_sample or 0, old.sample_rate or 0)
        if not all(new_res + old_res):  # an unknown value: no guessing
            return None
        not_lower = all(n >= o for n, o in zip(new_res, old_res, strict=True))
        return "a higher resolution" if not_lower and new_res != old_res else None
    if is_lossless(old) or not (new.bitrate and old.bitrate):
        return None
    return "a higher bitrate" if new.bitrate >= old.bitrate * MIN_BITRATE_GAIN else None


@dataclass
class Upgrade:
    """An inbox track that sounds better than the library copy it would replace."""

    inbox: InboxTrack
    library: Track  # the copy it replaces
    reason: str  # why it's better ("lossless instead of lossy")
    match: str  # why it's the same track (app.duplicates.REASONS)

    @property
    def destination(self) -> str:
        """The new file's library path: the old one's folder and name, its own extension."""
        suffix = PurePosixPath(self.inbox.path).suffix
        return PurePosixPath(self.library.path).with_suffix(suffix).as_posix()

    @property
    def old_quality(self) -> str:
        return quality(self.library)

    @property
    def new_quality(self) -> str:
        return quality(self.inbox)


def find(track: InboxTrack, matches: list[Match]) -> Upgrade | None:
    """The upgrade an inbox track offers, given its likely library copies (LibraryIndex)."""
    if track.error:
        return None
    if any(m.reason == "identical file" for m in matches):
        return None  # the same file again: nothing to gain
    if not matches:
        return None
    best = max(matches, key=lambda m: (sound(m.track), _tags(m.track), -m.track.id))
    if any(better(track, m.track) is None for m in matches):
        return None  # another copy sounds as good: the Duplicates page is the place for that
    return Upgrade(track, best.track, better(track, best.track), best.reason)


def _tags(track: Track) -> int:
    return sum(1 for f in COMPARED if writer.current_value(track, f) not in (None, "")) + int(
        track.has_cover
    )


# --- What replacing would do -----------------------------------------------------------------


@dataclass
class Plan:
    upgrade: Upgrade
    changes: dict[str, str | None]  # tags written into the new file
    old: dict[str, str | None]  # the same fields as they are in the inbox file now
    sources: dict[str, str]  # where each value came from (app.changes.SOURCES)
    cover: bool  # the library copy's cover is written too (worked out when replacing)
    problems: list[str] = field(default_factory=list)  # why it can't be replaced

    @property
    def destination(self) -> str:
        return self.upgrade.destination


def plan(session: Session, upgrade: Upgrade, settings: Settings) -> Plan:
    """The tags the new file gets, and what blocks the replacement."""
    inbox, library = upgrade.inbox, upgrade.library
    base = import_plan(session, inbox, settings.music_dir)  # the inbox's values fill the gaps
    changes, old, sources = dict(base.changes), dict(base.old), dict(base.sources)
    in_file = {f.field: f.in_file for f in review(session, inbox, list(writer.EDITABLE))}
    for name in writer.EDITABLE:
        _take(changes, old, sources, name, writer.current_value(library, name), in_file[name])
    ids_now = {}
    if any(getattr(library, name) for name in writer.IDS):  # inbox rows don't keep every ID
        ids_now = file_ids(settings.import_dir / inbox.path) or {}
    for name in writer.IDS:
        _take(changes, old, sources, name, getattr(library, name), ids_now.get(name))
    cover = library.has_cover
    if cover:  # the library copy's cover wins; the inbox's choice is only for tracks without
        for d in (changes, old, sources):
            d.pop(writer.COVER, None)
    result = Plan(upgrade, changes, old, sources, cover)
    if inbox.error or library.error:
        result.problems.append("the file can't be read")
    if session.exec(select(PendingChange).where(PendingChange.track_id == library.id)).first():
        result.problems.append("the library copy has pending changes: apply or discard them first")
    if upgrade.destination != library.path and (settings.music_dir / upgrade.destination).exists():
        result.problems.append(f"{upgrade.destination} already exists in the library")
    return result


def _take(changes, old, sources, name: str, library_value, inbox_value) -> None:
    """The library copy's value wins; without one, the inbox's value (already in ``changes``)."""
    if library_value in (None, ""):
        return
    if library_value == inbox_value:  # already in the file: nothing to write
        for d in (changes, old, sources):
            d.pop(name, None)
    else:
        changes[name], old[name], sources[name] = library_value, inbox_value, "library"


# --- Automatic replacing ---------------------------------------------------------------------


def ready_for_auto_upgrade(
    session: Session, upgrade: Upgrade, settings: Settings, now: float
) -> bool:
    """True when Tagwerk may replace this library copy without asking (Settings → Import).

    The file must be unchanged for a while (no half downloads), nothing may block the
    replacement, and nothing may rest on guesses: an artist and title only count when they are
    the file's own, the owner's or sure suggestions, and a field the library copy lacks is only
    filled with a sure suggestion.
    """
    track = upgrade.inbox
    if track.error or now - track.mtime < STABLE_AFTER:
        return False
    item = plan(session, upgrade, settings)
    for f in review(session, track, list(writer.EDITABLE)):
        guessed = f.origin == "suggested" and not f.suggestion.sure
        if guessed and f.field in ("title", "artist") and upgrade.match == "same artist and title":
            return False  # the match itself rests on a guess
        if guessed and item.sources.get(f.field) != "library" and f.field in item.changes:
            return False  # a gap would be filled with a guess: the owner checks that
    return not item.problems


def upgrades(
    session: Session, settings: Settings, track_ids: list[int] | None = None
) -> list[Upgrade]:
    """Inbox tracks (all, or these) that are better copies of library tracks."""
    library = LibraryIndex.load(session)
    query = select(InboxTrack).where(InboxTrack.error.is_(None))
    if track_ids is not None:
        query = query.where(col(InboxTrack.id).in_(track_ids))
    found = []
    for track in session.exec(query):
        values = {f.field: f.value for f in review(session, track, ["title", "artist"])}
        matches = library.matches(
            track, values["title"], values["artist"], settings.import_dir, settings.music_dir
        )
        if upgrade := find(track, matches):
            found.append(upgrade)
    return found


# --- Replacing (a background job) -------------------------------------------------------------


def replace(
    engine: Engine,
    settings: Settings,
    track_ids: list[int],
    progress: WriteProgress,
    images: ImageStore | None = None,
) -> None:
    """Replace library copies with these better inbox files. Tracks that aren't (or can't be
    replaced) stay in the inbox with a reason."""
    with Session(engine) as session:
        found = {u.inbox.id: u for u in upgrades(session, settings, track_ids)}
        tracks = session.exec(
            select(InboxTrack).where(col(InboxTrack.id).in_(track_ids)).order_by(InboxTrack.path)
        ).all()
        progress.total = len(tracks)
        changeset = ChangeSet(
            kind="upgrade", tracks=len(tracks), fields="Replaced with a better copy"
        )
        session.add(changeset)
        session.commit()
        progress.changeset_id = changeset.id

        for track in tracks:
            progress.current = track.path
            upgrade = found.get(track.id)
            item = plan(session, upgrade, settings) if upgrade else None
            entry = ChangeEntry(
                changeset_id=changeset.id,
                track_id=upgrade.library.id if upgrade else None,
                path=item.destination if item else track.path,
                changes="{}",
                moved_from=track.path,
            )
            if item:
                _record(entry, item)
            try:
                if item is None:
                    raise writer.WriteError("no library copy that sounds worse")
                if item.problems:
                    raise writer.WriteError(", ".join(item.problems))
                _replace_one(session, settings, item, entry, images)
                progress.written += 1
                changeset.written += 1
            except Exception as exc:
                log.warning("Could not replace with %s: %s", track.path, exc)
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


def _replace_one(
    session: Session, settings: Settings, item: Plan, entry: ChangeEntry, images: ImageStore | None
) -> None:
    upgrade = item.upgrade
    inbox, library = upgrade.inbox, upgrade.library
    source = settings.import_dir / inbox.path
    old = settings.music_dir / library.path
    target = settings.music_dir / item.destination
    stat = source.stat()
    if stat.st_mtime != inbox.mtime or stat.st_size != inbox.size:
        raise writer.WriteError("the inbox file changed since the inbox was checked; check again")
    old_stat = old.stat()
    if old_stat.st_mtime != library.mtime or old_stat.st_size != library.size:
        raise writer.WriteError("the library copy changed since the last scan; scan again")
    if target != old and target.exists():
        raise writer.WriteError(f"{item.destination} already exists in the library")
    # Navidrome keeps play counts and ratings when it has the old file's current tags.
    ready = navidrome.scanned_since(settings, old_stat.st_mtime)
    if not ready.ok:
        raise writer.WriteError(f"Not replaced: {ready.message}")

    if item.cover:  # the library copy's cover, unless the inbox file has the very same
        picture = embedded_cover(old)
        if picture and picture != embedded_cover(source):
            if images is None:
                raise writer.WriteError("cover art needs an image store")
            item.changes[writer.COVER] = images.put(picture[0])
            item.old[writer.COVER] = writer.current_value(inbox, writer.COVER)
            item.sources[writer.COVER] = "library"
            _record(entry, item)

    old_path = library.path
    changes = item.changes
    snapshot = writer.write(source, changes, images) if changes else None
    try:
        trashed = trash.delete(settings.music_dir, old_path)
        try:
            move_file(source, target)  # copy → verify → delete from the inbox
        except Exception:
            trash.restore(settings.music_dir, trashed)  # the old file comes back
            raise
    except Exception:
        if snapshot:
            writer.undo(source, snapshot, images)  # leave the inbox file as it was
        raise
    entry.snapshot = json.dumps(snapshot) if snapshot else None
    entry.details = json.dumps(
        {
            "replaced": old_path,
            "trash": trashed,
            "old": upgrade.old_quality,
            "new": upgrade.new_quality,
        }
    )

    new_stat = target.stat()
    store_file(session, target, item.destination, new_stat, target.with_suffix(".lrc").exists(),
               library.id)  # fmt: skip
    _after_file_change(session, library.id, new_stat.st_mtime)
    analysis.copy_to_library(session, inbox.id, library.id)  # the new file's BPM and key
    entry.mtime_after = new_stat.st_mtime
    session.delete(inbox)
    log.info("Replaced %s (%s) with %s (%s)", old_path, upgrade.old_quality, inbox.path,
             upgrade.new_quality)  # fmt: skip


def _record(entry: ChangeEntry, item: Plan) -> None:
    """The tags written, for the History (and the Statistics' "Tagwerk's work")."""
    entry.changes = json.dumps({k: [item.old.get(k), v] for k, v in item.changes.items()})
    entry.sources = sources_json(item.sources)


def _after_file_change(session: Session, track_id: int, mtime: float) -> None:
    """The track's file is another one now: the final mark protects the new file, and its
    loudness is measured again (it belongs to the audio)."""
    final = session.get(FinalTrack, track_id)
    if final:
        final.mtime = mtime
        session.add(final)
    session.exec(delete(LibraryLoudness).where(LibraryLoudness.track_id == track_id))


# --- Undo ------------------------------------------------------------------------------------


def check_undo(entry: ChangeEntry, settings: Settings) -> None:
    """Before anything is undone: the old file must still be in the library trash, and both
    places must be free. Raises WriteError otherwise."""
    details = json.loads(entry.details or "{}")
    if not settings.import_dir.is_dir():
        raise writer.WriteError("the import folder isn't available")
    if not any(d.id == details.get("trash") for d in trash.items(settings.music_dir)):
        raise writer.WriteError(
            "the old file is no longer in the library trash (restored or emptied); not undone"
        )
    if (settings.import_dir / entry.moved_from).exists():
        raise writer.WriteError(f"{entry.moved_from} already exists in the inbox")
    replaced = details.get("replaced")
    if replaced != entry.path and (settings.music_dir / replaced).exists():
        raise writer.WriteError(f"{replaced} exists again in the library")


def undo(session: Session, entry: ChangeEntry, settings: Settings) -> None:
    """The new file goes back into the inbox (its tags are already restored from the snapshot);
    the old file comes back from the library trash into the same track row."""
    details = json.loads(entry.details or "{}")
    move_file(settings.music_dir / entry.path, settings.import_dir / entry.moved_from)
    rel = trash.restore(settings.music_dir, details["trash"])
    track = session.get(Track, entry.track_id) if entry.track_id else None
    path = settings.music_dir / rel
    stat = path.stat()
    track = store_file(session, path, rel, stat, path.with_suffix(".lrc").exists(),
                       track.id if track else None)  # fmt: skip
    entry.track_id = track.id
    _after_file_change(session, track.id, stat.st_mtime)
