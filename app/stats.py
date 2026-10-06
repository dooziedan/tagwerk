"""Library statistics for the dashboard, computed from the ``track`` table.

Both modes share the totals and formats. DJ mode adds BPM, keys and audio quality;
Collector mode adds decades and lyrics. "Missing tags" checks differ per mode.

Every number uses the same conditions as the track list (``app.library``), and carries the
URL of the list that shows exactly those tracks.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import distinct, func
from sqlmodel import Session, select

from app.keys import CAMELOT_CODES, display
from app.library import (
    ALBUM_ARTIST,
    FLAGS,
    LOW_BITRATE_KBPS,
    MISSING,
    TrackFilter,
    count,
    is_missing,
)
from app.models import Track
from app.preferences import Preferences

BPM_BUCKET = 5  # BPM histogram bar width
BPM_MIN, BPM_MAX = 60, 200  # tempos outside are grouped as "< 60" / "200+"


# Which checks each mode shows, in display order.
MISSING_BY_MODE = {
    "dj": ["Title", "Artist", "Genre", "BPM", "Key", "Label", "Comment", "Cover art"],
    "collector": [
        "Title",
        "Artist",
        "Album",
        "Album artist",
        "Track number",
        "Year",
        "Genre",
        "Cover art",
        "Lyrics",
        "ReplayGain",
    ],
}


@dataclass
class Bar:
    label: str
    count: int
    percent: float  # share of the relevant total, 0-100
    size: int | None = None  # bytes, for formats
    url: str = ""  # the track list behind this number


@dataclass
class KeyCell:
    camelot: str  # "8A"
    label: str  # in the chosen notation: "8A", "1m" or "Am"
    count: int
    percent: float  # of tracks with a recognized key
    intensity: int  # 0-100, for shading relative to the most common key
    url: str = ""


@dataclass
class LibraryStats:
    mode: str
    tracks: int
    artists: int
    albums: int
    total_size: int
    total_duration: float
    formats: list[Bar]
    genres: list[Bar]
    missing: list[Bar]
    untagged: int  # readable files without any tags
    invalid_mbids: int  # MusicBrainz fields holding something else, e.g. Discogs IDs
    unreadable: int
    last_scan: datetime | None
    # DJ mode
    bpm: list[Bar] = field(default_factory=list)
    keys: list[KeyCell] = field(default_factory=list)
    with_bpm_and_key: int = 0
    unrecognized_keys: int = 0  # key tag present but not a key Tagwerk understands
    bpm_zero: int = 0  # files that store BPM as 0 ("unknown")
    lossless: int = 0
    low_bitrate: int = 0
    low_bitrate_kbps: int = LOW_BITRATE_KBPS
    # BPM and key from the audio (app/analysis.py)
    audio_bpm_octave: int = 0  # tagged at half or double the tempo the audio has
    audio_bpm_differs: int = 0
    audio_key_differs: int = 0
    not_analysed: int = 0
    # Collector mode
    decades: list[Bar] = field(default_factory=list)
    unknown_year: int = 0
    with_lyrics: int = 0


def library_stats(session: Session, prefs: Preferences) -> LibraryStats:
    tracks, size, duration, last_scan = session.exec(
        select(
            func.count(Track.id),
            func.coalesce(func.sum(Track.size), 0),
            func.coalesce(func.sum(Track.duration), 0),
            func.max(Track.scanned_at),
        )
    ).one()
    readable = Track.error.is_(None)
    readable_count = count(session, readable)

    checks = list(MISSING_BY_MODE[prefs.mode])
    if prefs.show_musicbrainz:
        checks.append("MusicBrainz IDs")

    stats = LibraryStats(
        mode=prefs.mode,
        tracks=tracks,
        artists=session.exec(select(func.count(distinct(ALBUM_ARTIST)))).one(),
        albums=_album_count(session),
        total_size=size,
        total_duration=duration,
        formats=_formats(session, tracks),
        genres=_genres(session, tracks),
        missing=[
            Bar(name, n, _pct(n, readable_count), url=TrackFilter(missing=name).url())
            for name in checks
            for n in [count(session, readable, MISSING[name])]
        ],
        untagged=_flag(session, "untagged"),
        invalid_mbids=_flag(session, "invalid_mbid"),
        unreadable=tracks - readable_count,
        last_scan=last_scan,
    )
    if prefs.mode == "dj":
        _add_dj(session, stats, prefs)
    else:
        _add_collector(session, stats)
    return stats


def _flag(session: Session, name: str) -> int:
    return count(session, FLAGS[name][1])


def _add_dj(session: Session, stats: LibraryStats, prefs: Preferences) -> None:
    stats.bpm = _bpm_histogram(session)
    stats.keys = _key_cells(session, prefs.key_notation)
    stats.with_bpm_and_key = _flag(session, "bpm_and_key")
    stats.unrecognized_keys = _flag(session, "key_unrecognized")
    stats.bpm_zero = _flag(session, "bpm_zero")
    stats.lossless = _flag(session, "lossless")
    stats.low_bitrate = _flag(session, "low_bitrate")
    stats.audio_bpm_octave = _flag(session, "audio_bpm_octave")
    stats.audio_bpm_differs = _flag(session, "audio_bpm_differs")
    stats.audio_key_differs = _flag(session, "audio_key_differs")
    stats.not_analysed = _flag(session, "not_analysed")


def _add_collector(session: Session, stats: LibraryStats) -> None:
    decade = (Track.year // 10) * 10
    rows = session.exec(
        select(decade, func.count(Track.id))
        .where(Track.year.is_not(None))
        .group_by(decade)
        .order_by(decade)
    ).all()
    dated = sum(n for _, n in rows)
    stats.decades = [
        Bar(f"{d}s", n, _pct(n, dated), url=TrackFilter(decade=d).url()) for d, n in rows
    ]
    stats.unknown_year = stats.tracks - dated
    stats.with_lyrics = _flag(session, "has_lyrics")


def _formats(session: Session, tracks: int) -> list[Bar]:
    return [
        Bar(fmt.upper(), n, _pct(n, tracks), size=fmt_size, url=TrackFilter(format=fmt).url())
        for fmt, n, fmt_size in session.exec(
            select(Track.format, func.count(Track.id), func.sum(Track.size))
            .group_by(Track.format)
            .order_by(func.count(Track.id).desc(), Track.format)
        )
    ]


def _genres(session: Session, tracks: int, limit: int = 12) -> list[Bar]:
    """Most common genres. A track tagged "House; Tech House" counts for both."""
    counter: Counter[str] = Counter()
    for genre, n in session.exec(
        select(Track.genre, func.count(Track.id))
        .where(Track.genre.is_not(None))
        .group_by(Track.genre)
    ):
        for name in {g.strip() for g in genre.split(";") if g.strip()}:
            counter[name] += n
    return [
        Bar(name, n, _pct(n, tracks), url=TrackFilter(genre=name).url())
        for name, n in counter.most_common(limit)
    ]


def _bpm_histogram(session: Session) -> list[Bar]:
    bpms = session.exec(select(Track.bpm).where(Track.bpm.is_not(None))).all()
    if not bpms:
        return []
    counter = Counter(
        BPM_MIN - 1
        if b < BPM_MIN
        else BPM_MAX
        if b >= BPM_MAX
        else int(b // BPM_BUCKET) * BPM_BUCKET
        for b in bpms
    )
    # Show every bucket between the slowest and fastest one, so gaps are visible.
    inner = [k for k in counter if BPM_MIN <= k < BPM_MAX]
    buckets = list(range(min(inner), max(inner) + 1, BPM_BUCKET)) if inner else []
    if BPM_MIN - 1 in counter:
        buckets.insert(0, BPM_MIN - 1)
    if BPM_MAX in counter:
        buckets.append(BPM_MAX)

    def label_and_url(k: int) -> tuple[str, str]:
        if k < BPM_MIN:
            return f"< {BPM_MIN}", TrackFilter(bpm_max=BPM_MIN).url()
        if k >= BPM_MAX:
            return f"{BPM_MAX}+", TrackFilter(bpm_min=BPM_MAX).url()
        return f"{k}–{k + BPM_BUCKET - 1}", TrackFilter(bpm_min=k, bpm_max=k + BPM_BUCKET).url()

    total = len(bpms)
    bars: list[Bar] = []
    for k in buckets:
        # Merge runs of empty buckets into one row, e.g. "135–169" between house and DnB.
        if counter[k] == 0 and bars and bars[-1].count == 0 and "–" in bars[-1].label:
            bars[-1].label = f"{bars[-1].label.split('–')[0]}–{k + BPM_BUCKET - 1}"
        else:
            label, url = label_and_url(k)
            bars.append(
                Bar(label, counter[k], _pct(counter[k], total), url=url if counter[k] else "")
            )
    return bars


def _key_cells(session: Session, notation: str) -> list[KeyCell]:
    counts = dict(
        session.exec(
            select(Track.key_camelot, func.count(Track.id))
            .where(Track.key_camelot.is_not(None))
            .group_by(Track.key_camelot)
        ).all()
    )
    total = sum(counts.values())
    most = max(counts.values(), default=0)
    return [
        KeyCell(
            camelot=code,
            label=display(code, notation),
            count=counts.get(code, 0),
            percent=_pct(counts.get(code, 0), total),
            intensity=round(100 * counts.get(code, 0) / most) if most else 0,
            url=TrackFilter(key=code).url() if counts.get(code) else "",
        )
        for code in CAMELOT_CODES
    ]


def _album_count(session: Session) -> int:
    albums = select(ALBUM_ARTIST, Track.album).where(~is_missing(Track.album)).distinct()
    return session.exec(select(func.count()).select_from(albums.subquery())).one()


def _pct(part: int, whole: int) -> float:
    return round(100 * part / whole, 1) if whole else 0.0
