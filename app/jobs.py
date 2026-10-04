"""Background jobs.

Long tasks (scanning the library, writing tags, undoing) run in a thread, so the web page
stays responsive and can poll for progress. **Only one of them runs at a time**: they share
one lock, so a scan never reads files while tags are being written, and two writes never
overlap. State lives in memory: after a container restart there is no running job, and the
database keeps the results.
"""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app import navidrome
from app.changes import WriteProgress, apply_pending, undo_changeset
from app.config import Settings
from app.db import get_engine
from app.images import ImageStore
from app.importer import import_tracks
from app.inbox import scan_inbox
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
    """Reads the import inbox (read-only)."""

    def __init__(self) -> None:
        super().__init__("inbox", progress=ScanProgress())

    def start(self, settings: Settings) -> bool:
        progress = ScanProgress()

        def work() -> None:
            if not settings.import_dir.is_dir():
                raise FileNotFoundError(f"Import folder not found: {settings.import_dir}")
            scan_inbox(get_engine(settings.database_url), settings.import_dir, progress)

        return self._start(work, progress)


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
                engine, settings.music_dir, changeset_id, progress, images, settings.import_dir
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


def image_store(settings: Settings) -> ImageStore:
    """Uploaded covers and the covers saved for undo."""
    return ImageStore(settings.config_dir / "images")


scan_job = ScanJob()
inbox_job = InboxJob()
write_job = WriteJob()


def busy() -> bool:
    """True while any job (scan, inbox scan, apply, undo) is running."""
    return scan_job.running or inbox_job.running or write_job.running
