"""Library statistics for the dashboard, computed from the ``track`` table."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import ColumnElement, and_, distinct, func, or_
from sqlmodel import Session, col, select

from app.models import Track

# An album belongs to its album artist; files without one fall back to the track artist.
# That's also how Navidrome groups its artist list.
_album_artist = func.coalesce(func.nullif(Track.albumartist, ""), Track.artist)


def _missing(column) -> ColumnElement[bool]:
    return or_(column.is_(None), column == "")


# (label, condition) in display order. Only files that were read successfully count.
MISSING_CHECKS: list[tuple[str, ColumnElement[bool]]] = [
    ("Title", _missing(Track.title)),
    ("Artist", _missing(Track.artist)),
    ("Album", _missing(Track.album)),
    ("Album artist", _missing(Track.albumartist)),
    ("Track number", Track.tracknumber.is_(None)),
    ("Year", Track.year.is_(None)),
    ("Genre", _missing(Track.genre)),
    ("Cover art", col(Track.has_cover).is_(False)),
    ("MusicBrainz IDs", or_(_missing(Track.mb_albumid), col(Track.mbid_invalid).is_(True))),
]


@dataclass
class Bar:
    label: str
    count: int
    percent: float  # of all tracks (formats) or readable tracks (missing tags)
    size: int | None = None  # bytes, for formats


@dataclass
class LibraryStats:
    tracks: int
    artists: int
    albums: int
    total_size: int
    total_duration: float
    formats: list[Bar]
    missing: list[Bar]
    untagged: int  # readable files without any tags
    invalid_mbids: int  # MusicBrainz fields holding something else, e.g. Discogs IDs
    unreadable: int
    last_scan: datetime | None


def library_stats(session: Session) -> LibraryStats:
    tracks, size, duration, last_scan = session.exec(
        select(
            func.count(Track.id),
            func.coalesce(func.sum(Track.size), 0),
            func.coalesce(func.sum(Track.duration), 0),
            func.max(Track.scanned_at),
        )
    ).one()
    artists = session.exec(select(func.count(distinct(_album_artist)))).one()
    albums = session.exec(
        select(func.count()).select_from(
            select(_album_artist, Track.album).where(~_missing(Track.album)).distinct().subquery()
        )
    ).one()

    formats = [
        Bar(fmt.upper(), count, _pct(count, tracks), size=fmt_size)
        for fmt, count, fmt_size in session.exec(
            select(Track.format, func.count(Track.id), func.sum(Track.size))
            .group_by(Track.format)
            .order_by(func.count(Track.id).desc(), Track.format)
        )
    ]

    readable = Track.error.is_(None)
    readable_count = session.exec(select(func.count(Track.id)).where(readable)).one()
    missing = [
        Bar(label, count, _pct(count, readable_count))
        for label, condition in MISSING_CHECKS
        for count in [_count(session, and_(readable, condition))]
    ]

    return LibraryStats(
        tracks=tracks,
        artists=artists,
        albums=albums,
        total_size=size,
        total_duration=duration,
        formats=formats,
        missing=missing,
        untagged=_count(session, and_(readable, Track.tag_format.is_(None))),
        invalid_mbids=_count(session, col(Track.mbid_invalid).is_(True)),
        unreadable=tracks - readable_count,
        last_scan=last_scan,
    )


def _count(session: Session, condition: ColumnElement[bool]) -> int:
    return session.exec(select(func.count(Track.id)).where(condition)).one()


def _pct(part: int, whole: int) -> float:
    return round(100 * part / whole, 1) if whole else 0.0
