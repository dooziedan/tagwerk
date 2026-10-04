"""Background jobs.

Long tasks (scanning the library, writing tags, undoing) run in a thread, so the web page
stays responsive and can poll for progress. **Only one of them runs at a time**: they share
one lock, so a scan never reads files while tags are being written, and two writes never
overlap. State lives in memory: after a container restart there is no running job, and the
database keeps the results.
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, select

from app import convert, final, folders, identify, navidrome, preferences, trash
from app.changes import WriteProgress, apply_pending, undo_changeset
from app.config import Settings
from app.db import get_engine
from app.duplicates import LibraryIndex
from app.images import ImageStore
from app.importer import import_tracks, ready_for_auto_import
from app.inbox import scan_inbox
from app.models import InboxTrack
from app.scanner import ScanProgress, scan_library

log = logging.getLogger(__name__)

# Held while any job runs. Shared by all jobs on purpose.
_library_lock = threading.Lock()


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
            if not settings.music_dir.is_dir():
                raise FileNotFoundError(f"Music folder not found: {settings.music_dir}")
            scan_library(get_engine(settings.database_url), settings.music_dir, progress)

        return self._start(work, progress)


class InboxJob(Job):
    """Reads the import inbox. With automation "auto" it also imports complete tracks."""

    def __init__(self) -> None:
        super().__init__("inbox", progress=ScanProgress())
        self.auto_import: WriteProgress | None = None  # the last automatic import, if any

    def start(self, settings: Settings) -> bool:
        progress = ScanProgress()

        def work() -> None:
            if not settings.import_dir.is_dir():
                raise FileNotFoundError(f"Import folder not found: {settings.import_dir}")
            engine = get_engine(settings.database_url)
            scan_inbox(engine, settings.import_dir, progress)
            trash.purge(settings.import_dir)  # deleted more than 30 days ago
            self._auto_import(settings, engine)
            identify_job.start(settings)  # new tracks are looked up online, beside other jobs

        return self._start(work, progress)

    def _auto_import(self, settings: Settings, engine) -> None:
        with Session(engine) as session:
            if preferences.load(session).automation != "auto":
                return
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
            return
        progress = WriteProgress(action="import")
        import_tracks(
            engine, settings.import_dir, settings.music_dir, ids, progress, image_store(settings)
        )
        self.auto_import = progress
        log.info("Imported %d complete inbox tracks automatically", progress.written)
        navidrome.rescan_after_write(settings, progress.written)


class WriteJob(Job):
    """Applies pending changes, imports inbox tracks, or undoes an applied change set."""

    def __init__(self) -> None:
        super().__init__("write", progress=WriteProgress())

    def apply(self, settings: Settings) -> bool:
        progress = WriteProgress(action="apply")
        engine = get_engine(settings.database_url)
        images = image_store(settings)

        def work() -> None:
            apply_pending(engine, settings.music_dir, progress, images)
            navidrome.rescan_after_write(settings, progress.written)

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
        work = lambda: convert.convert(engine, settings, track_ids, progress)  # noqa: E731
        return self._start(work, progress)


@dataclass
class IdentifyProgress:
    total: int = 0
    processed: int = 0
    current: str = ""
    library: int = 0  # library tracks done in this run ("Look up online")


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
        are library tracks; their sure values become pending changes."""
        engine = get_engine(settings.database_url)
        if track_ids is None:
            with Session(engine) as session:
                track_ids = list(session.exec(select(InboxTrack.id)))
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
                    return
                (library, track_id), force = self._queue.popitem()
                self._current = (library, track_id)
                self.progress.total = self.progress.processed + 1 + len(self._queue)
            try:
                identify.lookup(
                    engine, settings, track_id, force, image_store(settings), library=library
                )
                if library:
                    self.progress.library += 1
            except Exception:
                log.exception("Online lookup failed for track %s", track_id)
            self.progress.processed += 1

    def queued(self, track_id: int, library: bool = False) -> bool:
        """True while this track waits for (or is in) a lookup."""
        key = (library, track_id)
        return self.running and (key in self._queue or key == self._current)

    def wait(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)


def image_store(settings: Settings) -> ImageStore:
    """Uploaded covers and the covers saved for undo."""
    return ImageStore(settings.config_dir / "images")


scan_job = ScanJob()
inbox_job = InboxJob()
write_job = WriteJob()
identify_job = IdentifyJob()


def check_inbox_regularly(settings: Settings, every: float = 300) -> threading.Thread:
    """Check the inbox every few minutes in the background (new files, automatic imports).

    Skipped while another job runs; the next round tries again.
    """

    def loop() -> None:
        while True:
            time.sleep(every)
            try:
                if settings.import_dir.is_dir():
                    inbox_job.start(settings)
            except Exception:
                log.exception("Background inbox check failed")

    thread = threading.Thread(target=loop, name="inbox-timer", daemon=True)
    thread.start()
    return thread


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
