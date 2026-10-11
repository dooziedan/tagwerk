"""Notifications: what Tagwerk did or found while the owner was away (ADR 0035).

Toasts are for what the owner just did and saw on the page. Notifications are for the rest: the
regular inbox check, a scan that stopped, Navidrome not answering, long jobs finishing. They are
kept few on purpose:

- each topic has a switch in Settings → Notifications; a switched-off topic writes nothing;
- one entry per job run, never one per track; a check where nothing happened writes nothing;
- a lasting problem is reported once, and once more when it is fine again (``problem()`` and
  ``solved()``).

Nothing disappears by itself: unread notifications stay "New" until ✓ Read or "Mark all as
read"; read ones stay in the History until "Clear history".

``notify()`` never raises: a notification that can't be written must not stop the scan or
import that wanted to write it.
"""

import json
import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Engine, delete, func, update
from sqlmodel import Session, select

from app.config import get_settings
from app.db import get_engine
from app.models import Notification, NotificationState

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Topic:
    label: str  # Settings → Notifications
    about: str  # what it reports, in a few words (Settings)
    on: bool  # switched on in a fresh install: only what needs the owner or could lose data


# The switches. A later feature that reports something adds its own topic here.
TOPICS = {
    "inbox_trash": Topic(
        "Inbox trash",
        "Deleted inbox files will be removed for good: announced 3 days before, with a link to "
        "restore them.",
        True,
    ),
    "inbox_help": Topic(
        "Inbox needs you",
        "More inbox tracks need your help (only when the number goes up).",
        True,
    ),
    "scan": Topic(
        "Scan problems",
        "A scan was skipped because the music folder looked empty, or files couldn't be read.",
        True,
    ),
    "navidrome": Topic(
        "Navidrome",
        "Navidrome didn't answer a rescan, or the check before renaming a final track.",
        True,
    ),
    "online": Topic(
        "Online sources",
        "A source rejected its key or keeps failing.",
        True,
    ),
    "auto_import": Topic(
        "Automatic imports",
        "Inbox tracks imported on their own (automatic mode), with a link to the History.",
        False,
    ),
    "long_jobs": Topic(
        "Long jobs finished",
        "Audio analysis or online lookups you started for many tracks.",
        False,
    ),
}

# What a notification is about, by its colour: gold, warning, calm.
KINDS = {"needs_you": "Needs you", "problem": "Problem", "done": "Done"}

# Several jobs run side by side (lookups, analysis, the inbox check): one at a time in here, so
# a lasting problem is never reported twice.
_lock = threading.Lock()


def notify(
    topic: str,
    kind: str,
    summary: str,
    message: str = "",
    source: str = "",
    url: str | None = None,
    engine: Engine | None = None,
) -> bool:
    """Write one notification, if the owner switched its topic on. Returns True if written.

    Never raises: a failure is logged, and the job that called carries on.
    """
    try:
        with _lock, Session(engine or _engine()) as session:
            return _write(session, topic, kind, summary, message, source, url)
    except Exception:
        log.exception("Could not write the notification %r", summary)
        return False


def problem(
    topic: str,
    key: str,
    summary: str,
    message: str = "",
    source: str = "",
    url: str | None = None,
    engine: Engine | None = None,
) -> bool:
    """Report a problem that may last (e.g. Navidrome not answering) once while it lasts.

    ``key`` names the problem (e.g. "navidrome"); until ``solved(key)`` it isn't reported
    again. Never raises. Returns True if written."""
    try:
        with _lock, Session(engine or _engine()) as session:
            if not enabled(session, topic) or _recall(session, f"problem:{key}"):
                return False
            _remember(session, f"problem:{key}", summary)
            return _write(session, topic, "problem", summary, message, source, url)
    except Exception:
        log.exception("Could not write the notification %r", summary)
        return False


def solved(
    topic: str,
    key: str,
    summary: str,
    message: str = "",
    source: str = "",
    url: str | None = None,
    engine: Engine | None = None,
) -> bool:
    """The problem ``key`` is over: say so once, if it was reported. Never raises."""
    try:
        with _lock, Session(engine or _engine()) as session:
            if _recall(session, f"problem:{key}") is None:
                return False
            _forget(session, f"problem:{key}")
            return _write(session, topic, "done", summary, message, source, url)
    except Exception:
        log.exception("Could not write the notification %r", summary)
        return False


def many(count: int, noun: str) -> str:
    """The number with its noun, for summaries and messages: "1 file", "3 files"."""
    return f"{count:,} {noun}" if count == 1 else f"{count:,} {noun}s"


def enabled(session: Session, topic: str) -> bool:
    """True if the owner wants notifications about ``topic`` (Settings → Notifications)."""
    from app import preferences  # preferences reads TOPICS from here

    return bool(preferences.load(session).notifications.get(topic))


def _write(session, topic, kind, summary, message, source, url) -> bool:
    if topic not in TOPICS or kind not in KINDS:
        raise ValueError(f"Unknown notification topic or kind: {topic}, {kind}")
    if not enabled(session, topic):
        return False
    session.add(
        Notification(
            topic=topic,
            kind=kind,
            source=source or TOPICS[topic].label,
            summary=summary,
            message=message,
            url=url,
        )
    )
    session.commit()
    log.info("Notification: %s", summary)
    return True


def _engine() -> Engine:
    return get_engine(get_settings().database_url)


# --- Reading and marking (the bell, the page, the API) ------------------------------------------


def unread_count(session: Session, kind: str | None = None) -> int:
    query = select(func.count(Notification.id)).where(Notification.read_at.is_(None))
    if kind:
        query = query.where(Notification.kind == kind)
    return session.exec(query).one()


def unread(session: Session) -> list[Notification]:
    """New notifications, newest first."""
    query = select(Notification).where(Notification.read_at.is_(None))
    return list(
        session.exec(query.order_by(Notification.created_at.desc(), Notification.id.desc()))
    )


def history(session: Session) -> list[Notification]:
    """Read notifications, the latest read first."""
    query = select(Notification).where(Notification.read_at.is_not(None))
    return list(session.exec(query.order_by(Notification.read_at.desc(), Notification.id.desc())))


def mark_read(session: Session, notification_id: int) -> Notification | None:
    """✓ Read: the notification moves to the History. None if there is no such notification."""
    note = session.get(Notification, notification_id)
    if note is not None and note.read_at is None:
        note.read_at = datetime.now(UTC)
        session.add(note)
        session.commit()
        session.refresh(note)
    return note


def mark_all_read(session: Session) -> int:
    """Mark all as read: every New notification moves to the History. Returns how many."""
    result = session.exec(
        update(Notification).where(Notification.read_at.is_(None)).values(read_at=datetime.now(UTC))
    )
    session.commit()
    return result.rowcount


def clear_history(session: Session) -> int:
    """Clear history: removes the read notifications for good (New ones stay). Returns how many."""
    result = session.exec(delete(Notification).where(Notification.read_at.is_not(None)))
    session.commit()
    return result.rowcount


# --- What the checks remember between runs (NotificationState) ---------------------------------


def recall(key: str, default=None, engine: Engine | None = None):
    """A value a check remembered (e.g. the last inbox count). Never raises."""
    try:
        with Session(engine or _engine()) as session:
            found = _recall(session, key)
            return default if found is None else found
    except Exception:
        log.exception("Could not read the notification state %s", key)
        return default


def remember(key: str, value, engine: Engine | None = None) -> None:
    """Remember a value for the next run of a check. Never raises."""
    try:
        with _lock, Session(engine or _engine()) as session:
            _remember(session, key, value)
    except Exception:
        log.exception("Could not save the notification state %s", key)


def _recall(session: Session, key: str):
    row = session.get(NotificationState, key)
    return json.loads(row.value) if row else None


def _remember(session: Session, key: str, value) -> None:
    session.merge(NotificationState(key=key, value=json.dumps(value)))
    session.commit()


def _forget(session: Session, key: str) -> None:
    if row := session.get(NotificationState, key):
        session.delete(row)
        session.commit()
