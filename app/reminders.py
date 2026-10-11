"""Regular checks that write notifications (ADR 0035), run by the background loop in app/jobs.py.

- **Inbox trash:** deleted inbox files are removed for good after 30 days (app/trash.py). Once a
  day, the files whose day comes within ANNOUNCE_DAYS are announced in one notification, each
  file only once. Afterwards it would be too late to restore them, so nothing is said then.
- **Inbox needs you:** when more inbox tracks need the owner's help than at the last check.
  Only counted while the inbox check, its online lookups and the audio analysis are idle: a new
  track lacks BPM and key until they are done, which isn't a reason to call the owner.

What they remember between runs (the last check, the announced files, the last count) is kept
with ``notifications.remember``.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlmodel import Session

from app import notifications, trash
from app.config import Settings
from app.db import get_engine

log = logging.getLogger(__name__)

ANNOUNCE_DAYS = 3


def run(settings: Settings) -> None:
    """One round of the regular checks. Never raises."""
    if not settings.import_dir.is_dir():
        return
    for check in (announce_inbox_trash, report_inbox_help):
        try:
            check(settings)
        except Exception:
            log.exception("The regular check %s failed", check.__name__)


def announce_inbox_trash(settings: Settings, now: datetime | None = None) -> bool:
    """Once a day: announce inbox-trash files that will be removed for good within
    ANNOUNCE_DAYS (each file once). Returns True if a notification was written."""
    now = now or datetime.now(UTC)
    today = now.date().isoformat()
    if notifications.recall("inbox_trash:checked") == today:
        return False
    in_trash = trash.items(settings.import_dir)
    announced = set(notifications.recall("inbox_trash:announced", []))
    due = [
        item
        for item in in_trash
        if item.id not in announced
        and now < item.removed_for_good <= now + timedelta(ANNOUNCE_DAYS)
    ]
    written = False
    if due:
        due.sort(key=lambda item: item.removed_for_good)
        first = _day(due[0].removed_for_good)
        when = f"on {first}" if _day(due[-1].removed_for_good) == first else f"from {first}"
        files = "\n".join(f"• {item.path} ({_day(item.removed_for_good)})" for item in due)
        written = notifications.notify(
            "inbox_trash",
            "needs_you",
            f"Inbox trash: {notifications.many(len(due), 'file')} will be removed for good {when}",
            f"Files deleted from the inbox wait in its trash for {trash.KEEP_DAYS} days. "
            f"{'This one goes' if len(due) == 1 else 'These go'} for good on the day shown:\n"
            f"{files}\nRestore {'it' if len(due) == 1 else 'them'} from the inbox trash to keep "
            f"{'it' if len(due) == 1 else 'them'}.",
            "Inbox trash",
            "/inbox#trash",
        )
    # Only files still in the trash need remembering; switched off, they count as announced too
    # (switching it on later shouldn't bring up old ones in a heap).
    still_there = {item.id for item in in_trash}
    notifications.remember(
        "inbox_trash:announced", sorted((announced & still_there) | {item.id for item in due})
    )
    notifications.remember("inbox_trash:checked", today)
    return written


def report_inbox_help(settings: Settings) -> bool:
    """When more inbox tracks need help than at the last check, say so. Returns True if a
    notification was written."""
    from app.jobs import analysis_job, identify_job, inbox_job

    if inbox_job.running or identify_job.running or analysis_job.running:
        return False  # the numbers aren't settled yet: next round
    # routes.inbox decides what "needs help" means (the Inbox tab); it imports a lot.
    from app.routes.inbox import counts

    with Session(get_engine(settings.database_url)) as session:
        now = counts(session)["help"]
    before = notifications.recall("inbox_help:count", 0)
    written = False
    if now > before:
        more = now - before
        new = (
            notifications.many(more, "track")
            if not before
            else f"{more} more " + ("track" if more == 1 else "tracks")
        )
        need = "needs" if more == 1 else "need"
        written = notifications.notify(
            "inbox_help",
            "needs_you",
            f"Inbox: {new} {need} your help",
            f"{notifications.many(now, 'track')} in the inbox "
            f"{'needs' if now == 1 else 'need'} your help now: title, artist, genre, BPM, key or "
            "the cover are missing, and neither the filename, the online sources nor the audio "
            "filled them in.",
            "Inbox check",
            "/inbox?show=help",
        )
    notifications.remember("inbox_help:count", now)
    return written


def _day(when: datetime) -> str:
    """'14 Oct', in the container's time zone (TZ; UTC if not set)."""
    local = when.astimezone()
    return f"{local.day} {local:%b}"
