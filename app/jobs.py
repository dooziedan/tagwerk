"""Background jobs.

Long tasks (scanning the library, writing tags, undoing) run in a thread, so the web page
stays responsive and can poll for progress. **Only one of them runs at a time**: they share
one lock, so a scan never reads files while tags are being written, and two writes never
overlap. State lives in memory: after a container restart there is no running job, and the
database keeps the results.
"""

import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, select

from app import (
    analysis,
    area,
    convert,
    duplicates,
    final,
    folders,
    identify,
    loudness,
    navidrome,
    notifications,
    preferences,
    secret,
    trash,
    upgrade,
)
from app.changes import WriteProgress, apply_pending
from app.config import Settings
from app.db import get_engine
from app.duplicates import LibraryIndex
from app.images import ImageStore
from app.importer import import_tracks, ready_for_auto_import
from app.inbox import scan_inbox
from app.library import TrackFilter
from app.models import (
    ChangeEntry,
    InboxAnalysis,
    InboxTrack,
    LibraryLoudness,
    PendingChange,
    Track,
)
from app.scanner import EmptyLibraryError, ScanProgress, scan_library
from app.undo import undo_changeset

log = logging.getLogger(__name__)

# Held while any job runs. Shared by all jobs on purpose.
_library_lock = threading.Lock()


def after_library_change(engine, settings: Settings) -> None:
    """After a scan or write: tags may have changed, so compare with the audio again and find
    duplicates again."""
    analysis.refresh_all(engine)
    duplicates.refresh_library(engine, settings.music_dir)


@dataclass
class Job:
    name: str
    status: str = "idle"  # idle, running, done, failed
    progress: Any = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    _thread: threading.Thread | None = field(default=None, repr=False)

    @property
    def running(self) -> bool:
        return self.status == "running"

    def _start(self, work: Callable[[], None], progress: Any) -> bool:
        """Run ``work`` in a thread. Returns False if any job is already running."""
        if not _library_lock.acquire(blocking=False):
            return False
        self.status = "running"
        self.progress = progress
        self.started_at = datetime.now(UTC)
        self.finished_at = None
        self.error = None
        self._thread = threading.Thread(target=self._run, args=(work,), name=self.name, daemon=True)
        self._thread.start()
        return True

    def _run(self, work: Callable[[], None]) -> None:
        try:
            work()
            self.status = "done"
        except Exception as exc:
            log.exception("%s failed", self.name)
            self.error = str(exc)
            self.status = "failed"
        finally:
            self.finished_at = datetime.now(UTC)
            _library_lock.release()

    def wait(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)


class ScanJob(Job):
    def __init__(self) -> None:
        super().__init__("scan", progress=ScanProgress())

    def start(self, settings: Settings) -> bool:
        progress = ScanProgress()

        def work() -> None:
            engine = get_engine(settings.database_url)
            try:
                if not settings.music_dir.is_dir():
                    raise FileNotFoundError(f"Music folder not found: {settings.music_dir}")
                with Session(engine) as session:
                    skip = area.skipped(preferences.load(session))
                scan_library(engine, settings.music_dir, progress, skip)
                area.sync(engine, settings)  # the Releasomat folder's own list (ADR 0044)
            except (FileNotFoundError, EmptyLibraryError) as exc:
                notifications.problem(
                    "scan",
                    "scan-skipped",
                    "Scan skipped: the music folder looks empty",
                    f"{exc} Tagwerk tells you once more when a scan works again.",
                    "Scan",
                    "/",
                    engine,
                )
                raise
            notifications.solved(
                "scan",
                "scan-skipped",
                "Scans work again",
                "The music folder has its files again; the scan went through.",
                "Scan",
                "/",
                engine,
            )
            report_unreadable(engine)
            report_left_for_area(engine, progress, skip)
            after_library_change(engine, settings)

        return self._start(work, progress)


def report_left_for_area(engine, progress: ScanProgress, skip: tuple[str, ...]) -> bool:
    """After the first scan that kept the Releasomat folder out (ADR 0044): how many tracks
    left the library lists. Once: the next scans find no rows there any more."""
    if not progress.left_for_area:
        return False
    folder = ", ".join(f"/{f}" for f in skip)
    return notifications.notify(
        "releasomat",
        "done",
        f"{notifications.many(progress.left_for_area, 'track')} left the library: they're in "
        "the Releasomat folder",
        f"Tagwerk keeps {folder} out of the library now, as you confirmed in Settings. The files "
        "are untouched; their analysis, pending changes and marks in Tagwerk went with them. "
        "Settings → Releasomat can treat the folder as library again.",
        "Scan",
        "/settings#releasomat",
        engine,
    )


def report_unreadable(engine) -> bool:
    """After a scan: library files that couldn't be read, once each (they are tried again on
    every scan, but only new ones are reported). Returns True if a notification was written."""
    with Session(engine) as session:
        broken = sorted(session.exec(select(Track.path).where(Track.error.is_not(None))))
    told = set(notifications.recall("scan:unreadable", [], engine))
    new = [path for path in broken if path not in told]
    written = False
    if new:
        listed = "\n".join(f"• {path}" for path in new[:10])
        if len(new) > 10:
            listed += f"\n… and {len(new) - 10:,} more"
        written = notifications.notify(
            "scan",
            "problem",
            f"Scan: {notifications.many(len(new), 'file')} couldn't be read",
            f"{listed}\nThey may be damaged or still being copied. Tagwerk tries them again on "
            "every scan.",
            "Scan",
            TrackFilter(flag="unreadable").url(),
            engine,
        )
    notifications.remember("scan:unreadable", broken, engine)  # fixed ones drop out
    return written


class InboxJob(Job):
    """Reads the import inbox. With automation "auto" it also imports complete tracks."""

    def __init__(self) -> None:
        super().__init__("inbox", progress=ScanProgress())
        self.auto_import: WriteProgress | None = None  # the last automatic import, if any
        self.auto_upgrade: WriteProgress | None = None  # the last automatic replacing, if any
        # The last check changed what the Inbox shows: only then is the page built again
        # when the check is done (building it takes a while with hundreds of tracks).
        self.changed = False

    def start(self, settings: Settings) -> bool:
        progress = ScanProgress()

        def work() -> None:
            self.changed = False
            if not settings.import_dir.is_dir():
                raise FileNotFoundError(f"Import folder not found: {settings.import_dir}")
            engine = get_engine(settings.database_url)
            scan_inbox(engine, settings.import_dir, progress)
            purged = trash.purge(settings.import_dir)  # deleted more than 30 days ago
            self.changed = bool(progress.added or progress.updated or progress.removed or purged)
            if self._auto_upgrade(settings, engine):
                self.changed = True
            if self._auto_import(settings, engine):
                self.changed = True
            identify_job.start(settings)  # new tracks are looked up online, beside other jobs
            analysis_job.start(settings)  # and their BPM and key measured from the audio

        return self._start(work, progress)

    def _auto_upgrade(self, settings: Settings, engine) -> bool:
        """Automatic replacing (Settings → Import): better copies replace their library copy.
        Returns True if it tried to replace any."""
        with Session(engine) as session:
            if not preferences.load(session).replace_automatically:
                return False
            now = time.time()
            ids = [
                u.inbox.id
                for u in upgrade.upgrades(session, settings)
                if upgrade.ready_for_auto_upgrade(session, u, settings, now)
            ]
        if not ids:
            return False
        progress = WriteProgress(action="upgrade")
        upgrade.replace(engine, settings, ids, progress, image_store(settings))
        after_library_change(engine, settings)
        self.auto_upgrade = progress
        log.info("Replaced %d library tracks with better copies automatically", progress.written)
        report_auto_upgrade(engine, progress)
        navidrome.rescan_after_write(settings, progress.written)
        return True

    def _auto_import(self, settings: Settings, engine) -> bool:
        """Automatic mode: complete tracks are imported. Returns True if it tried to import any."""
        with Session(engine) as session:
            if preferences.load(session).automation != "auto":
                return False
            now = time.time()
            library = LibraryIndex.load(session)
            ids = [
                t.id
                for t in session.exec(select(InboxTrack))
                if ready_for_auto_import(
                    session, t, settings.import_dir, settings.music_dir, now, library
                )
            ]
        if not ids:
            return False
        progress = WriteProgress(action="import")
        import_tracks(
            engine, settings.import_dir, settings.music_dir, ids, progress, image_store(settings)
        )
        after_library_change(engine, settings)
        self.auto_import = progress
        log.info("Imported %d complete inbox tracks automatically", progress.written)
        report_auto_import(engine, progress)
        navidrome.rescan_after_write(settings, progress.written)
        return True


def report_auto_import(engine, progress: WriteProgress) -> bool:
    """Automatic mode: one notification for the tracks imported on their own."""
    if not progress.written:
        return False
    with Session(engine) as session:
        imported = select(ChangeEntry.path).where(
            ChangeEntry.changeset_id == progress.changeset_id, ChangeEntry.error.is_(None)
        )
        paths = list(session.exec(imported))
    names = "\n".join(f"• {path.rsplit('/', 1)[-1]}" for path in paths[:10])
    if len(paths) > 10:
        names += f"\n… and {len(paths) - 10:,} more"
    if progress.failed:
        names += f"\n{notifications.many(progress.failed, 'track')} couldn't be imported; "
        names += "they stay in the inbox."
    history = f"/changes/history/{progress.changeset_id}" if progress.changeset_id else "/changes"
    return notifications.notify(
        "auto_import",
        "done",
        f"Inbox: {notifications.many(progress.written, 'track')} imported automatically",
        "Complete inbox tracks went into the library on their own (automatic mode):\n"
        f"{names}\nThe History can undo it.",
        "Inbox check",
        history,
        engine,
    )


def report_auto_upgrade(engine, progress: WriteProgress) -> bool:
    """Automatic replacing: one notification for the library tracks replaced on their own."""
    if not progress.written:
        return False
    with Session(engine) as session:
        replaced = select(ChangeEntry.path, ChangeEntry.details).where(
            ChangeEntry.changeset_id == progress.changeset_id, ChangeEntry.error.is_(None)
        )
        rows = list(session.exec(replaced))
    lines = []
    for path, details in rows[:10]:
        sound = json.loads(details or "{}")
        lines.append(f"• {path.rsplit('/', 1)[-1]}: {sound.get('old')} → {sound.get('new')}")
    if len(rows) > 10:
        lines.append(f"… and {len(rows) - 10:,} more")
    names = "\n".join(lines)
    if progress.failed:
        names += f"\n{notifications.many(progress.failed, 'file')} couldn't replace their copy; "
        names += "they stay in the inbox."
    return notifications.notify(
        "auto_upgrade",
        "done",
        f"Inbox: {notifications.many(progress.written, 'library track')} replaced by better copies",
        "Inbox files that sound better took the place of their library copy (automatic "
        f"replacing), with its tags, folder and name:\n{names}\nThe old files are in the library "
        "trash; the History can undo it.",
        "Inbox check",
        f"/changes/history/{progress.changeset_id}",
        engine,
    )


class WriteJob(Job):
    """Applies pending changes, imports inbox tracks, or undoes an applied change set."""

    def __init__(self) -> None:
        super().__init__("write", progress=WriteProgress())

    def apply(self, settings: Settings, change_ids: list[int] | None = None) -> bool:
        """Write the pending changes: all, or only ``change_ids``."""
        progress = WriteProgress(action="apply", change_ids=change_ids)
        engine = get_engine(settings.database_url)
        images = image_store(settings)

        def work() -> None:
            apply_pending(engine, settings.music_dir, progress, images, change_ids)
            after_library_change(engine, settings)
            navidrome.rescan_after_write(settings, progress.written + progress.trashed)

        return self._start(work, progress)

    def undo(self, settings: Settings, changeset_id: int) -> bool:
        progress = WriteProgress(action="undo")
        engine = get_engine(settings.database_url)
        images = image_store(settings)

        def work() -> None:
            undo_changeset(
                engine,
                settings.music_dir,
                changeset_id,
                progress,
                images,
                settings.import_dir,
                settings,
            )
            after_library_change(engine, settings)
            navidrome.rescan_after_write(settings, progress.written)

        return self._start(work, progress)

    def import_tracks(self, settings: Settings, track_ids: list[int]) -> bool:
        """Import inbox tracks into the library (see app/importer.py)."""
        progress = WriteProgress(action="import")
        engine = get_engine(settings.database_url)
        images = image_store(settings)

        def work() -> None:
            import_tracks(
                engine, settings.import_dir, settings.music_dir, track_ids, progress, images
            )
            after_library_change(engine, settings)
            navidrome.rescan_after_write(settings, progress.written)

        return self._start(work, progress)

    def upgrade(self, settings: Settings, track_ids: list[int]) -> bool:
        """Replace library copies with better inbox files (see app/upgrade.py)."""
        progress = WriteProgress(action="upgrade")
        engine = get_engine(settings.database_url)
        images = image_store(settings)

        def work() -> None:
            upgrade.replace(engine, settings, track_ids, progress, images)
            after_library_change(engine, settings)
            navidrome.rescan_after_write(settings, progress.written)

        return self._start(work, progress)

    def create_folder(self, settings: Settings, genre: str) -> bool:
        """Create a proposed genre folder and move its tracks in (see app/folders.py)."""
        progress = WriteProgress(action="folder")
        engine = get_engine(settings.database_url)

        def work() -> None:
            folders.create_folder(engine, settings.music_dir, genre, progress)
            navidrome.rescan_after_write(settings, progress.written)

        return self._start(work, progress)

    def mark_final(self, settings: Settings, track_id: int) -> bool:
        """Mark a track as final (renaming it if switched on, see app/final.py)."""
        progress = WriteProgress(action="final")
        engine = get_engine(settings.database_url)
        return self._start(lambda: final.mark(engine, settings, track_id, progress), progress)

    def unmark_final(self, settings: Settings, track_id: int, name: str | None) -> bool:
        """Remove the final mark; ``name``: a new filename, or None to keep it."""
        progress = WriteProgress(action="unfinal")
        engine = get_engine(settings.database_url)
        work = lambda: final.unmark(engine, settings, track_id, name, progress)  # noqa: E731
        return self._start(work, progress)

    def convert(self, settings: Settings, track_ids: list[int]) -> bool:
        """Convert library tracks to AIFF (see app/convert.py)."""
        progress = WriteProgress(action="convert")
        engine = get_engine(settings.database_url)

        def work() -> None:
            convert.convert(engine, settings, track_ids, progress)
            duplicates.refresh_library(engine, settings.music_dir)  # a copy may have gone

        return self._start(work, progress)


# A run that went through at least this many library tracks is a long job: when it is done, the
# owner can be told (Settings → Notifications → Long jobs finished, ADR 0035).
LONG_JOB = 10


@dataclass
class IdentifyProgress:
    total: int = 0
    processed: int = 0
    current: str = ""
    library: int = 0  # library tracks done in this run ("Look up online")
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class IdentifyJob:
    """Asks online sources about inbox tracks (app/identify.py).

    Network and database only, no files are written, so it doesn't take the library lock: it
    runs beside scans and imports. Tracks asked for while it runs are queued.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # (library?, track id) -> force (ask again even if fresh)
        self._queue: dict[tuple[bool, int], bool] = {}
        self._current: tuple[bool, int] | None = None  # the track being looked up now
        self._thread: threading.Thread | None = None
        self.progress = IdentifyProgress()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(
        self,
        settings: Settings,
        track_ids: list[int] | None = None,
        force=False,
        library: bool = False,
    ) -> None:
        """Look up these tracks (default: every inbox track that needs it). ``library``: they
        are library tracks; their sure values become pending changes. Secret tracks are left
        out (app/secret.py)."""
        engine = get_engine(settings.database_url)
        with Session(engine) as session:
            if track_ids is None:  # the inbox check: only tracks with something to ask
                track_ids = identify.needing_lookup(session, settings)
            hidden = secret.secret_ids(session, track_ids, inbox=not library)
        track_ids = [i for i in track_ids if i not in hidden]
        if not track_ids:
            return
        with self._lock:
            for track_id in track_ids:
                key = (library, track_id)
                self._queue[key] = self._queue.get(key, False) or force
            if self.running:
                return
            self.progress = IdentifyProgress()
            self._thread = threading.Thread(
                target=self._run, args=(settings, engine), name="identify", daemon=True
            )
            self._thread.start()

    def _run(self, settings: Settings, engine) -> None:
        while True:
            with self._lock:
                self._current = None
                if not self._queue:
                    self.progress.current = ""
                    break
                (library, track_id), force = self._queue.popitem()
                self._current = (library, track_id)
                self.progress.total = self.progress.processed + 1 + len(self._queue)
            try:
                identify.lookup(
                    engine, settings, track_id, force, image_store(settings), library=library
                )
                if library:
                    self.progress.library += 1
                    with Session(engine) as session:  # online BPMs may settle the audio's BPM
                        if track := session.get(Track, track_id):
                            analysis.stage_sure(session, track)
            except Exception:
                log.exception("Online lookup failed for track %s", track_id)
            self.progress.processed += 1
        report_lookups(engine, self.progress)

    def queued(self, track_id: int, library: bool = False) -> bool:
        """True while this track waits for (or is in) a lookup."""
        key = (library, track_id)
        return self.running and (key in self._queue or key == self._current)

    def wait(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)


@dataclass
class AnalysisProgress:
    total: int = 0
    processed: int = 0
    current: str = ""
    failed: int = 0  # files that couldn't be analysed (error stored with the result)
    skipped: int = 0  # already analysed, file unchanged ("Analyse all" doesn't redo them)
    library: int = 0  # library tracks analysed in this run (the owner asked for them)
    loudness: int = 0  # of these, only the loudness measured (the ReplayGain page)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None


class AnalysisJob:
    """Measures BPM and key from the audio, several tracks at once (app/analysis.py).

    Only reads files, so like the online lookups it doesn't take the library lock and runs
    beside scans and imports. Each track is analysed in its own low-priority process; as many
    run side by side as the container has CPU cores (and memory) for, see
    ``analysis.worker_count``. Inbox tracks go before library tracks: they are waiting for
    review. Tracks asked for while it runs are queued; ``stop`` empties the queue (tracks
    being analysed finish).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # (library?, track id) -> force (analyse again even if the result is fresh), in order
        self._queue: dict[tuple[bool, int], bool] = {}
        # Being analysed now -> True if only its loudness is measured
        self._current: dict[tuple[bool, int], bool] = {}
        # Library tracks that only get their loudness measured (the ReplayGain page)
        self._loudness_only: set[tuple[bool, int]] = set()
        self._threads: list[threading.Thread] = []
        self.workers = 0  # how many run side by side in this run
        self.progress = AnalysisProgress()

    @property
    def running(self) -> bool:
        return any(t.is_alive() for t in self._threads)

    def start(
        self,
        settings: Settings,
        track_ids: list[int] | None = None,
        force: bool = False,
        library: bool = False,
        loudness_only: bool = False,
    ) -> None:
        """Analyse these tracks (default: every inbox track without a fresh result).

        ``loudness_only``: library tracks only get the quick loudness pass (app/loudness.py),
        not BPM and key; asking for a full analysis later still does both."""
        engine = get_engine(settings.database_url)
        if track_ids is None:  # the inbox check: all results in one query, not one per track
            with Session(engine) as session:
                rows = session.exec(
                    select(InboxTrack, InboxAnalysis)
                    .join(InboxAnalysis, isouter=True)
                    .where(InboxTrack.error.is_(None))
                )
                track_ids = [t.id for t, row in rows if not analysis.fresh(row, t)]
        with self._lock:
            for track_id in track_ids:
                key = (library, track_id)
                if loudness_only and key not in self._queue:
                    self._loudness_only.add(key)
                elif not loudness_only:
                    self._loudness_only.discard(key)
                self._queue[key] = self._queue.get(key, False) or force
            if self.running or not self._queue:
                return
            self.progress = AnalysisProgress()
            self.workers = min(analysis.worker_count(settings), len(self._queue))
            self._threads = [
                threading.Thread(
                    target=self._run, args=(settings, engine), name=f"analysis-{n}", daemon=True
                )
                for n in range(self.workers)
            ]
            for thread in self._threads:
                thread.start()

    def _next(self) -> tuple[tuple[bool, int], bool] | None:
        """The next track: inbox first, otherwise in the order they were asked for."""
        if not self._queue:
            return None
        key = next((k for k in self._queue if not k[0]), next(iter(self._queue)))
        return key, self._queue.pop(key)

    def _run(self, settings: Settings, engine) -> None:
        """One worker: takes tracks from the queue until it is empty."""
        while True:
            with self._lock:
                picked = self._next()
                if picked is None:
                    if not self._current:
                        self.progress.current = ""
                    return
                (library, track_id), force = picked
                only_loudness = (library, track_id) in self._loudness_only
                self._loudness_only.discard((library, track_id))
                self._current[(library, track_id)] = only_loudness
                self.progress.total = (
                    self.progress.processed + len(self._current) + len(self._queue)
                )
            failed = skipped = False
            try:
                with Session(engine) as session:
                    track = session.get(Track if library else InboxTrack, track_id)
                    self.progress.current = track.path if track else ""
                if only_loudness:
                    if loudness.measure_track(engine, settings.music_dir, track_id, force):
                        with Session(engine) as session:
                            found = session.get(LibraryLoudness, track_id)
                            failed = bool(found and found.error)
                    else:
                        skipped = True
                elif analysis.analyse_track(engine, settings, track_id, library, force):
                    with Session(engine) as session:
                        found = analysis.result(session, track_id, library)
                        failed = bool(found and found.error)
                else:
                    skipped = True
            except Exception:
                log.exception("Audio analysis failed for track %s", track_id)
                failed = True
            with self._lock:
                self._current.pop((library, track_id), None)
                self.progress.processed += 1
                self.progress.failed += failed
                self.progress.skipped += skipped
                self.progress.library += library and not skipped
                self.progress.loudness += library and only_loudness and not skipped
                finished = not self._queue and not self._current
                if finished:
                    self.progress.finished_at = datetime.now(UTC)
            if finished:
                report_analysis(engine, self.progress)

    def queued(self, track_id: int, library: bool = False) -> bool:
        """True while this track waits for (or is in) an analysis."""
        key = (library, track_id)
        return self.running and (key in self._queue or key in self._current)

    def measuring_loudness(self, track_id: int) -> bool:
        """True while this library track waits for (or is in) a pass that measures only its
        loudness, and no full analysis: its page keeps showing BPM and key meanwhile."""
        key = (True, track_id)
        if not self.running:
            return False
        if key in self._queue:
            return key in self._loudness_only
        return self._current.get(key, False)

    def stop(self) -> int:
        """Forget the waiting tracks; the ones being analysed finish. Returns how many."""
        with self._lock:
            count = len(self._queue)
            self._queue.clear()
            self._loudness_only.clear()
            return count

    def wait(self, timeout: float | None = None) -> None:
        for thread in list(self._threads):
            thread.join(timeout)


def report_analysis(engine, progress: AnalysisProgress) -> bool:
    """A long audio analysis the owner started is done: one notification (if switched on)."""
    n = progress.library
    if n < LONG_JOB:
        return False
    tracks = notifications.many(n, "track")
    if progress.loudness == n:  # the ReplayGain page measures only the loudness
        summary, details, url = (
            f"Loudness measured for {tracks}",
            f"{tracks} measured.",
            "/replaygain",
        )
    else:
        summary, url = f"BPM and key analysed for {tracks}", "/changes"
        details = f"{tracks} analysed. " + _waiting(
            _staged_since(engine, "audio", progress.started_at)
        )
    if progress.failed:
        details += f" {notifications.many(progress.failed, 'file')} couldn't be analysed."
    return notifications.notify(
        "long_jobs", "done", summary, details, "Audio analysis", url, engine
    )


def report_lookups(engine, progress: IdentifyProgress) -> bool:
    """Online lookups the owner started for many library tracks are done: one notification."""
    n = progress.library
    if n < LONG_JOB:
        return False
    found = _staged_since(engine, "online", progress.started_at)
    return notifications.notify(
        "long_jobs",
        "done",
        f"Looked up {n:,} tracks online",
        f"{n:,} tracks looked up online. {_waiting(found)}",
        "Online lookup",
        "/changes",
        engine,
    )


def _waiting(found: int) -> str:
    """How many sure values a long job staged, in words."""
    if not found:
        return "No new values to review."
    return (
        f"{notifications.many(found, 'sure value')} {'waits' if found == 1 else 'wait'} in Changes."
    )


def _staged_since(engine, source: str, since: datetime) -> int:
    """Pending changes from one source (e.g. "audio") saved since a job run started."""
    with Session(engine) as session:
        query = select(PendingChange).where(PendingChange.source == source)
        return sum(1 for c in session.exec(query) if _utc(c.created_at) >= since)


def _utc(when: datetime) -> datetime:
    return when if when.tzinfo else when.replace(tzinfo=UTC)  # SQLite gives naive UTC


def image_store(settings: Settings) -> ImageStore:
    """Uploaded covers and the covers saved for undo."""
    return ImageStore(settings.config_dir / "images")


scan_job = ScanJob()
inbox_job = InboxJob()
write_job = WriteJob()
identify_job = IdentifyJob()
analysis_job = AnalysisJob()


def run_now(work: Callable[[], Any]) -> tuple[bool, Any]:
    """Run a quick file operation right away (e.g. moving one file to the inbox trash), but
    never while a job runs: it takes the same lock. Returns (ran, result)."""
    if not _library_lock.acquire(blocking=False):
        return False, None
    try:
        return True, work()
    finally:
        _library_lock.release()


def busy() -> bool:
    """True while any job (scan, inbox scan, apply, undo) is running."""
    return scan_job.running or inbox_job.running or write_job.running
