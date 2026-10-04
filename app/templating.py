"""Jinja2 setup shared by all page routes, including formatting filters for templates."""

from datetime import UTC, datetime
from pathlib import Path

from fastapi.templating import Jinja2Templates

from app import __version__
from app.keys import NOTATIONS

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.globals["version"] = __version__
templates.env.globals["key_notations"] = NOTATIONS


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


def isoutc(value: datetime | None) -> str:
    """ISO timestamp for <time datetime="…">; the browser shows it in local time."""
    if value is None:
        return ""
    if value.tzinfo is None:  # SQLite returns naive datetimes; they are stored as UTC
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


templates.env.filters.update(
    filesize=filesize, duration=duration, number=number, plural=plural, isoutc=isoutc
)
