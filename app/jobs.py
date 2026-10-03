"""Background jobs.

Long tasks like a library scan run in a thread, so the web page stays responsive and can
poll for progress. Only one scan runs at a time. State lives in memory: after a container
restart there is simply no running job, and the database keeps the last scan's results.
"""

import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.config import Settings
from app.db import get_engine
from app.scanner import ScanProgress, scan_library

log = logging.getLogger(__name__)


@dataclass
class ScanJob:
    status: str = "idle"  # idle, running, done, failed
    progress: ScanProgress = field(default_factory=ScanProgress)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _thread: threading.Thread | None = field(default=None, repr=False)

    @property
    def running(self) -> bool:
        return self.status == "running"

    def start(self, settings: Settings) -> bool:
        """Start a scan in the background. Returns False if one is already running."""
        with self._lock:
            if self.running:
                return False
            self.status = "running"
            self.progress = ScanProgress()
            self.started_at = datetime.now(UTC)
            self.finished_at = None
            self.error = None
            self._thread = threading.Thread(
                target=self._run, args=(settings,), name="scan", daemon=True
            )
            self._thread.start()
            return True

    def wait(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)

    def _run(self, settings: Settings) -> None:
        try:
            if not settings.music_dir.is_dir():
                raise FileNotFoundError(f"Music folder not found: {settings.music_dir}")
            scan_library(get_engine(settings.database_url), settings.music_dir, self.progress)
            self.status = "done"
        except Exception as exc:
            log.exception("Scan failed")
            self.error = str(exc)
            self.status = "failed"
        finally:
            self.finished_at = datetime.now(UTC)


scan_job = ScanJob()
