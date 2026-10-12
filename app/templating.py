"""Jinja2 setup shared by all page routes, including formatting filters for templates."""

import hashlib
import json
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from urllib.parse import urlencode

from fastapi.templating import Jinja2Templates

from app import __version__, secret, writer
from app.charts import camelot_colour, key_wheel
from app.duplicates import quality
from app.keys import NOTATIONS, display, to_camelot
from app.notifications import KINDS
from app.percent import percent, shown

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def filesize(num_bytes: int | None) -> str:
    """1234567890 -> '1.2 GB' (decimal units, like Unraid shows disk sizes)."""
    size = float(num_bytes or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1000 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1000
    raise AssertionError("unreachable")


def duration(seconds: float | None) -> str:
    """Playing time: '45 s', '19 min', '3 h 25 min' or '2 d 3 h'."""
    total = int(seconds or 0)
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    if days:
        return f"{days} d {hours} h"
    if hours:
        return f"{hours} h {minutes} min"
    if minutes:
        return f"{minutes} min"
    return f"{secs} s"


def number(value: int | None) -> str:
    return f"{value or 0:,}"


def plural(count: int, singular: str, plural_form: str | None = None) -> str:
    """'1 file', '3 files'."""
    word = singular if count == 1 else (plural_form or singular + "s")
    return f"{number(count)} {word}"


def mmss(seconds: float | None) -> str:
    """Track length: 245.3 -> '4:05'."""
    if not seconds:
        return "–"
    minutes, secs = divmod(int(round(seconds)), 60)
    return f"{minutes}:{secs:02d}"


def bpm(value: float | None) -> str:
    """126.0 -> '126', 127.5 -> '127.5'."""
    return f"{value:g}" if value else ""


def page_url(params: dict, sort: str, desc: bool, page: int) -> str:
    """Track list URL for another page, keeping filters and sorting."""
    query = {**params, "sort": sort, "page": page}
    if desc:
        query["desc"] = "true"
    return "/tracks?" + urlencode(query)


def isoutc(value: datetime | None) -> str:
    """ISO timestamp for <time datetime="…">; the browser shows it in local time."""
    if value is None:
        return ""
    if value.tzinfo is None:  # SQLite returns naive datetimes; they are stored as UTC
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def pending_count() -> int:
    """Pending (not yet written) changes and proposed genre folders, for the menu badge."""
    try:
        from sqlmodel import Session

        from app.changes import pending_count as count
        from app.config import get_settings
        from app.db import get_engine
        from app.folders import proposal_count

        settings = get_settings()
        with Session(get_engine(settings.database_url)) as session:
            return count(session) + proposal_count(session, settings.music_dir)
    except Exception:  # e.g. database not ready: no badge rather than a broken page
        return 0


def inbox_count() -> int:
    """Number of tracks in the import inbox, for the menu badge."""
    try:
        from sqlmodel import Session

        from app.config import get_settings
        from app.db import get_engine
        from app.inbox import inbox_count as count

        with Session(get_engine(get_settings().database_url)) as session:
            return count(session)
    except Exception:  # e.g. database not ready: no badge rather than a broken page
        return 0


def unread_notifications(kind: str | None = None) -> int:
    """Unread notifications (all, or one kind), for the bell's number."""
    try:
        from sqlmodel import Session

        from app.config import get_settings
        from app.db import get_engine
        from app.notifications import unread_count

        with Session(get_engine(get_settings().database_url)) as session:
            return unread_count(session, kind)
    except Exception:  # e.g. database not ready: no number rather than a broken page
        return 0


# Where a notification's link leads, in words (the first matching start of the address).
_PLACES = [
    ("/inbox#trash", "Open the inbox trash"),
    ("/inbox?show=help", "Show these tracks"),
    ("/inbox", "Open the inbox"),
    ("/changes/history", "Open the History"),
    ("/changes", "Review the changes"),
    ("/settings", "Open Settings"),
    ("/scan", "Open the scan"),
    ("/tracks", "Show the tracks"),
]


def notification_link(url: str | None) -> str:
    """The button text for a notification's link: "Open the inbox trash"."""
    return next((text for start, text in _PLACES if (url or "").startswith(start)), "Open")


@cache
def static_version(name: str) -> str:
    """A short fingerprint of a file in app/static, added to its URL (``app.css?v=…``).

    It changes whenever the file changes, so browsers fetch the new file instead of an old
    cached copy (after an update, and while developing).
    """
    path = Path(__file__).parent / "static" / name
    return hashlib.sha256(path.read_bytes()).hexdigest()[:10]


def source_label(source: str | None) -> str:
    """Where a changed value came from, e.g. "From the audio" ("" when not recorded)."""
    from app.changes import SOURCES  # app.changes needs the database; import when used

    return SOURCES.get(source, source) if source else ""


def id_links(field: str, value: str | None) -> list[tuple[str, str | None]]:
    """Each ID in an ID field's value with its MusicBrainz or Discogs page (app/ids.py)."""
    from app.ids import links  # app.ids needs the database; import when used

    return links(field, value)


def id_link_groups(found: dict[str, str]) -> list:
    """A result's IDs as links grouped by service (app/ids.py)."""
    from app.ids import link_groups

    return link_groups(found)


def change_value(field: str, value: str | None) -> str | None:
    """A change's value as the Changes and History pages show it. Advanced tags keep their
    texts as a JSON list (app/writer.py, RAW): shown joined with "; ", like several artists."""
    if value is None or not field.startswith(writer.RAW):
        return value
    return "; ".join(writer.raw_values(value))


def recent(when: datetime | None, seconds: float) -> bool:
    """True if ``when`` was less than ``seconds`` ago (e.g. "show the last result a while")."""
    if when is None:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return (datetime.now(UTC) - when).total_seconds() < seconds


templates.env.globals.update(
    recent=recent,
    pending_count=pending_count,
    inbox_count=inbox_count,
    unread_notifications=unread_notifications,
    notification_link=notification_link,
    notification_kinds=KINDS,
    version=__version__,
    key_notations=NOTATIONS,
    key_wheel=key_wheel,
    key_colour=lambda code: camelot_colour(int(code[:-1]), code[-1], 1)[0] if code else "",
    key_label=display,
    key_code=to_camelot,  # key_code("Am") -> "8A"  # key_label("8A", "musical") -> "Am"
    page_url=page_url,
    static_version=static_version,
    field_label=writer.label,  # "Cover art", "Private data (TRAKTOR4)", "TXXX:MOOD (ID3)"
    change_value=change_value,
    id_fields=list(writer.IDS),  # MusicBrainz and Discogs ID fields
    id_links=id_links,
    id_link_groups=id_link_groups,
    source_label=source_label,
    secret_folder=secret.FOLDER,  # in the import folder: edits and bootlegs arrive as secret
)
templates.env.filters.update(
    # 3 | percent_of(1500) -> 1; 99.8 | whole_percent -> 99 (never 100 while one is missing)
    percent_of=lambda part, whole: percent(part, whole),
    whole_percent=shown,
    filesize=filesize,
    duration=duration,
    number=number,
    plural=plural,
    isoutc=isoutc,
    mmss=mmss,
    bpm=bpm,
    quality=quality,
    fromjson=lambda text: json.loads(text or "{}"),  # "FLAC · 44.1 kHz · 16 bit", "MP3 · 320 kbps"
)
