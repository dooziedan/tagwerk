"""Jinja2 setup shared by all page routes, including formatting filters for templates."""

import hashlib
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from urllib.parse import urlencode

from fastapi.templating import Jinja2Templates

from app import __version__
from app.charts import key_wheel
from app.keys import NOTATIONS, display, to_camelot

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


@cache
def static_version(name: str) -> str:
    """A short fingerprint of a file in app/static, added to its URL (``app.css?v=…``).

    It changes whenever the file changes, so browsers fetch the new file instead of an old
    cached copy (after an update, and while developing).
    """
    path = Path(__file__).parent / "static" / name
    return hashlib.sha256(path.read_bytes()).hexdigest()[:10]


templates.env.globals.update(
    pending_count=pending_count,
    inbox_count=inbox_count,
    version=__version__,
    key_notations=NOTATIONS,
    key_wheel=key_wheel,
    key_label=display,
    key_code=to_camelot,  # key_code("Am") -> "8A"  # key_label("8A", "musical") -> "Am"
    page_url=page_url,
    static_version=static_version,
)
templates.env.filters.update(
    filesize=filesize,
    duration=duration,
    number=number,
    plural=plural,
    isoutc=isoutc,
    mmss=mmss,
    bpm=bpm,
)
