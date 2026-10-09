"""Library statistics (the Statistics page), computed from the ``track`` table.

Totals, formats, growth, track lengths, labels and artists, BPM, keys, set-readiness and
audio quality: what a DJ needs (Tagwerk is made for DJs, ADR 0024). The heat map crosses any
two of key, tempo, release year, year added, genre and format.

Every number uses the same conditions as the track list (``app.library``), and carries the
URL of the list that shows exactly those tracks.
"""

import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import Integer, and_, cast, distinct, func
from sqlmodel import Session, select

from app import genre_merge
from app import genres as genre_maps
from app.duplicates import group_count
from app.keys import CAMELOT_CODES, display
from app.library import (
    ALBUM_ARTIST,
    FLAGS,
    LOW_BITRATE_KBPS,
    MISSING,
    SET_READY,
    TrackFilter,
    added_period,
    count,
    genre_is,
    is_missing,
)
from app.models import Track
from app.percent import percent
from app.preferences import Preferences

BPM_BUCKET = 5  # BPM histogram bar width
BPM_MIN, BPM_MAX = 60, 200  # tempos outside are grouped as "< 60" / "200+"


# The "Missing tags" checks, in display order: what a DJ needs.
MISSING_CHECKS = ["Title", "Artist", "Genre", "BPM", "Key", "Label", "Comment", "Cover art"]


@dataclass
class Bar:
    label: str
    count: int
    percent: float  # share of the relevant total, 0-100
    size: int | None = None  # bytes, for formats
    url: str = ""  # the track list behind this number
    total: int | None = None  # what the percent is of, when it's not the whole library


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
    duplicates: int = 0  # files that are copies of another library track (ADR 0022)
    duplicate_groups: int = 0  # how many tracks have copies
    growth: list[Bar] = field(default_factory=list)  # tracks added per month (recent months)
    growth_years: list[Bar] = field(default_factory=list)  # tracks added per year
    lengths: list[Bar] = field(default_factory=list)
    labels: list[Bar] = field(default_factory=list)  # top labels
    top_artists: list[Bar] = field(default_factory=list)
    set_ready: int = 0  # title, artist, genre, BPM, key and cover tagged
    set_ready_genres: list[Bar] = field(default_factory=list)  # set-ready share per genre
    genre_spellings: int = 0  # genres written in several ways (the Genre spellings page)
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

    checks = list(MISSING_CHECKS)
    if prefs.show_musicbrainz:
        checks.append("MusicBrainz IDs")

    stats = LibraryStats(
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
    stats.duplicates = _flag(session, "duplicate")
    stats.duplicate_groups = group_count(session)
    stats.growth, stats.growth_years = _growth(session)
    stats.lengths = _lengths(session)
    stats.labels = _top(session, Track.label, "label")
    stats.top_artists = _top(session, ALBUM_ARTIST, "albumartist")
    _add_dj(session, stats, prefs)
    return stats


def _flag(session: Session, name: str) -> int:
    return count(session, FLAGS[name][1])


def _add_dj(session: Session, stats: LibraryStats, prefs: Preferences) -> None:
    stats.bpm = _bpm_histogram(session)
    stats.keys = _key_cells(session, prefs.key_notation)
    stats.with_bpm_and_key = _flag(session, "bpm_and_key")
    stats.set_ready = _flag(session, "set_ready")
    stats.set_ready_genres = _set_ready_genres(session)
    stats.genre_spellings = len(genre_merge.groups(session))
    stats.unrecognized_keys = _flag(session, "key_unrecognized")
    stats.bpm_zero = _flag(session, "bpm_zero")
    stats.lossless = _flag(session, "lossless")
    stats.low_bitrate = _flag(session, "low_bitrate")
    stats.audio_bpm_octave = _flag(session, "audio_bpm_octave")
    stats.audio_bpm_differs = _flag(session, "audio_bpm_differs")
    stats.audio_key_differs = _flag(session, "audio_key_differs")
    stats.not_analysed = _flag(session, "not_analysed")


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
    """Most common genres. A track tagged "House; Tech House" counts for both.

    Spellings of one genre count together, like the genre filter finds them: upper/lower case
    ("Drum and Bass", "Drum And Bass") and the genre map's variants ("DnB" -> "Drum & Bass").
    The tags stay as they are; the Changes page proposes unifying them.
    """
    genre_map = genre_maps.active(session)
    counter: Counter[str] = Counter()  # per genre (lower case)
    spellings: dict[str, Counter[str]] = {}  # how each genre is written, to pick a label
    for genre, n in session.exec(
        select(Track.genre, func.count(Track.id))
        .where(Track.genre.is_not(None))
        .group_by(Track.genre)
    ):
        names = {genre_map.canonical(g) for g in genre.split(";") if g.strip()}
        for key in {genre_map.key(name) for name in names}:
            counter[key] += n
        for name in names:
            spellings.setdefault(genre_map.key(name), Counter())[name] += n
    bars = []
    for key, n in counter.most_common(limit):
        label = spellings[key].most_common(1)[0][0]  # the most used spelling
        bars.append(Bar(label, n, _pct(n, tracks), url=TrackFilter(genre=label).url()))
    return bars


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
    return float(percent(part, whole, 1))  # never 100.0 while one is missing


# --- Growth, lengths, labels, artists, set-ready ---------------------------------------------

GROWTH_MONTHS = 24  # months shown in the growth chart; the years list covers everything


def _growth(session: Session) -> tuple[list[Bar], list[Bar]]:
    """Tracks added per month (the last 24 months with any, gaps filled) and per year."""
    month = added_period(7)
    rows = dict(
        session.exec(
            select(month, func.count(Track.id)).where(Track.added_at.is_not(None)).group_by(month)
        ).all()
    )
    if not rows:
        return [], []
    first, last = min(rows), max(rows)
    months = []
    year, mon = int(last[:4]), int(last[5:])
    while len(months) < GROWTH_MONTHS:
        key = f"{year}-{mon:02d}"
        months.append(key)
        if key <= first:
            break
        year, mon = (year, mon - 1) if mon > 1 else (year - 1, 12)
    months.reverse()
    most = max(rows.get(m, 0) for m in months) or 1
    growth = [
        Bar(m, rows.get(m, 0), _pct(rows.get(m, 0), most), url=TrackFilter(added=m).url())
        for m in months
    ]
    per_year: Counter[str] = Counter()
    for m, n in rows.items():
        per_year[m[:4]] += n
    total = sum(per_year.values())
    years = [
        Bar(y, n, _pct(n, total), url=TrackFilter(added=y).url())
        for y, n in sorted(per_year.items(), reverse=True)
    ]
    return growth, years


# Track lengths in minutes: radio edits are short, extended mixes 5-8 minutes.
LENGTHS = [(None, 3), (3, 4), (4, 5), (5, 6), (6, 7), (7, 8), (8, 10), (10, None)]


def _lengths(session: Session) -> list[Bar]:
    known = count(session, Track.duration.is_not(None))
    bars = []
    for low, high in LENGTHS:
        f = TrackFilter(length_min=low, length_max=high)
        n = count(session, *f.conditions())
        label = (
            f"< {high} min"
            if low is None
            else f"{low}+ min"
            if high is None
            else f"{low}–{high} min"
        )
        bars.append(Bar(label, n, _pct(n, known), url=f.url() if n else ""))
    return bars


def _top(session: Session, column, param: str, limit: int = 15) -> list[Bar]:
    """The most common values of a column (label, album artist), each linking to its tracks."""
    rows = session.exec(
        select(column, func.count(Track.id))
        .where(column.is_not(None), column != "")
        .group_by(column)
        .order_by(func.count(Track.id).desc(), column)
        .limit(limit)
    ).all()
    tracks = count(session)
    return [Bar(v, n, _pct(n, tracks), url=TrackFilter(**{param: v}).url()) for v, n in rows]


def _set_ready_genres(session: Session, limit: int = 12) -> list[Bar]:
    """Set-ready share of the most common genres: count = set-ready tracks, of ``total``."""
    genre_map = genre_maps.active(session)
    bars = []
    for genre in _genres(session, 1, limit):
        total = count(session, Track.error.is_(None), genre_is(genre.label, genre_map))
        ready = count(session, SET_READY, genre_is(genre.label, genre_map))
        url = TrackFilter(genre=genre.label, flag="set_ready").url()
        bars.append(Bar(genre.label, ready, _pct(ready, total), url=url, total=total))
    return bars


# --- Heat map ---------------------------------------------------------------------------------

HEAT_AXES = {
    "key": "Key",
    "tempo": "Tempo",
    "year": "Release year",
    "added": "Year added",
    "genre": "Genre",
    "format": "Format",
}
HEAT_LEVELS = 6  # shades of the one heat-map colour (theme.css --tw-heat-1..6)
_TEMPO = cast(Track.bpm / BPM_BUCKET, Integer) * BPM_BUCKET
_TEMPO_RANGE = and_(Track.bpm >= BPM_MIN, Track.bpm < BPM_MAX)


@dataclass
class HeatValue:
    value: object  # what the database groups by (e.g. "8A", 170, 2019)
    label: str
    params: dict  # TrackFilter fields that select it


@dataclass
class HeatCell:
    count: int
    level: int  # 0 = none, 1..HEAT_LEVELS = few..most
    url: str
    title: str  # hover text


@dataclass
class HeatMap:
    rows: str  # axis names (keys of HEAT_AXES)
    cols: str
    row_values: list[HeatValue]
    col_values: list[HeatValue]
    cells: list[list[HeatCell]]  # [row][col]
    total: int  # tracks in the grid
    most: int
    note: str = ""


def _axis(session: Session, name: str, notation: str) -> tuple[object, list[HeatValue]]:
    """The column to group by (None for genre: a track can have several) and its values."""
    if name == "key":
        return Track.key_camelot, [
            HeatValue(code, display(code, notation), {"key": code}) for code in CAMELOT_CODES
        ]
    if name == "tempo":
        present = session.exec(select(distinct(_TEMPO)).where(_TEMPO_RANGE)).all()
        steps = range(min(present), max(present) + 1, BPM_BUCKET) if present else []
        return _TEMPO, [
            HeatValue(k, str(k), {"bpm_min": k, "bpm_max": k + BPM_BUCKET}) for k in steps
        ]
    if name == "year":
        years = session.exec(select(distinct(Track.year)).where(Track.year.is_not(None))).all()
        span = range(min(years), max(years) + 1) if years else []
        return Track.year, [HeatValue(y, str(y), {"year": y}) for y in span]
    if name == "added":
        period = added_period(4)
        years = sorted(session.exec(select(distinct(period)).where(period.is_not(None))).all())
        return period, [HeatValue(y, y, {"added": y}) for y in years]
    if name == "format":
        formats = session.exec(
            select(Track.format).group_by(Track.format).order_by(func.count(Track.id).desc())
        ).all()
        return Track.format, [HeatValue(f, f.upper(), {"format": f}) for f in formats]
    genres = _genres(session, 1, 10)
    return None, [HeatValue(g.label, g.label, {"genre": g.label}) for g in genres]


def heatmap(session: Session, rows: str, cols: str, notation: str = "camelot") -> HeatMap:
    """How many tracks have each combination, e.g. key x tempo. Every cell links to its list."""
    if rows not in HEAT_AXES:
        rows = "key"
    if cols not in HEAT_AXES or cols == rows:
        cols = "tempo" if rows != "tempo" else "key"
    row_expr, row_values = _axis(session, rows, notation)
    col_expr, col_values = _axis(session, cols, notation)
    extra = [_TEMPO_RANGE] if "tempo" in (rows, cols) else []

    counts: dict[tuple, int] = {}
    if row_expr is not None and col_expr is not None:
        query = (
            select(row_expr, col_expr, func.count(Track.id))
            .where(row_expr.is_not(None), col_expr.is_not(None), *extra)
            .group_by(row_expr, col_expr)
        )
        counts = {(r, c): n for r, c, n in session.exec(query)}
    else:  # one axis is the genre: one query per genre
        genre_first = row_expr is None
        other = col_expr if genre_first else row_expr
        genre_map = genre_maps.active(session)
        for g in row_values if genre_first else col_values:
            query = (
                select(other, func.count(Track.id))
                .where(genre_is(g.value, genre_map), other.is_not(None), *extra)
                .group_by(other)
            )
            for v, n in session.exec(query):
                counts[(g.value, v) if genre_first else (v, g.value)] = n

    most = max(counts.values(), default=0)
    grid = []
    for r in row_values:
        line = []
        for c in col_values:
            n = counts.get((r.value, c.value), 0)
            # Square root: small counts stay visible next to big ones; only the biggest is darkest.
            level = 1 + int((HEAT_LEVELS - 1) * math.sqrt(n / most)) if n else 0
            url = TrackFilter(**r.params, **c.params).url() if n else ""
            line.append(HeatCell(n, level, url, f"{r.label} · {c.label}: {n:,} tracks"))
        grid.append(line)
    note = ""
    if "tempo" in (rows, cols):
        note = f"Tempo in {BPM_BUCKET}-BPM steps from {BPM_MIN} to {BPM_MAX}."
    if "genre" in (rows, cols):
        note += " The 10 most common genres; a track with two genres counts in both."
    return HeatMap(
        rows, cols, row_values, col_values, grid, sum(counts.values()), most, note.strip()
    )
