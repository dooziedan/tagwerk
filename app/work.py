"""Tagwerk's work: what Tagwerk has done for the library (Statistics page, one line on Home).

Everything comes from the History (``changeset`` and ``changeentry``), so it covers the past
too. Only changes that are still in place count: written without error, and not undone.
Where each value came from (you, the audio, online …) is only known for changes applied
since v0.11; older ones count as "source unknown".
"""

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from sqlmodel import Session, col, select

from app import writer
from app.changes import SOURCES
from app.keys import to_camelot
from app.library import FLAGS, TrackFilter, count
from app.models import ChangeEntry, ChangeSet, Track
from app.percent import percent

# Rows of the "per field" table that stand for several fields.
IDS_ROW = "MusicBrainz & Discogs IDs"
PRIVATE_ROW = "Private data of other programs"
ACTIVITY_MONTHS = 24  # months in the activity chart
HISTORY = "/changes/history"


@dataclass
class FieldWork:
    """How often Tagwerk filled in, corrected or removed one field."""

    label: str
    filled: int = 0  # was empty
    corrected: int = 0  # had another value
    removed: int = 0

    @property
    def total(self) -> int:
        return self.filled + self.corrected + self.removed


@dataclass
class Month:
    label: str  # "2026-10"
    count: int  # files changed (tags written, imported, converted, moved, marked final)
    edited: int = 0
    imported: int = 0
    other: int = 0


@dataclass
class SourceBar:
    label: str
    count: int  # values
    percent: float  # of the values with a known source


@dataclass
class ReadyWork:
    """Set-ready before Tagwerk's first change and now, for one group of tracks."""

    tracks: int
    before: int
    now: int
    url: str


@dataclass
class WorkStats:
    since: datetime | None = None  # the first change still in place
    values: int = 0  # tag values written
    tags_tracks: int = 0  # tracks whose tags Tagwerk wrote
    imported: int = 0
    converted: int = 0
    final: int = 0
    folders: int = 0  # genre folders created
    fields: list[FieldWork] = field(default_factory=list)
    sources: list[SourceBar] = field(default_factory=list)
    unknown_source: int = 0  # values from before sources were recorded
    activity: list[Month] = field(default_factory=list)
    ready_library: ReadyWork | None = None  # tracks that were in the library before
    ready_imported: ReadyWork | None = None  # tracks that came in through the inbox
    # The track lists behind the numbers (same conditions, app/library.py)
    tags_url: str = TrackFilter(flag="tagwerk_tags").url()
    imported_url: str = TrackFilter(flag="tagwerk_imported").url()
    converted_url: str = TrackFilter(flag="tagwerk_converted").url()
    final_url: str = TrackFilter(flag="final").url()
    history_url: str = HISTORY


def _row(name: str) -> str:
    if name in writer.IDS:
        return IDS_ROW
    if name.startswith(writer.PRIVATE):
        return PRIVATE_ROW
    return writer.label(name)


def _counted(session: Session):
    """Every change entry still in place, oldest first, with its change set. Only the columns
    needed here: the undo snapshots can be big."""
    return session.exec(
        select(ChangeEntry.track_id, ChangeEntry.changes, ChangeEntry.sources, ChangeSet)
        .join(ChangeSet, col(ChangeSet.id) == ChangeEntry.changeset_id)
        .where(
            ChangeEntry.error.is_(None),
            col(ChangeEntry.undone).is_(False),
            ChangeSet.undone_at.is_(None),
        )
        .order_by(ChangeSet.applied_at, ChangeEntry.id)
    ).all()


def work_stats(session: Session) -> WorkStats:
    stats = WorkStats()
    rows = _counted(session)
    if not rows:
        return stats
    stats.since = rows[0][3].applied_at

    per_field: dict[str, FieldWork] = {}
    sources: Counter[str] = Counter()
    months: dict[str, Month] = {}
    # Per track: each field's value before Tagwerk first changed it, and whether it was imported
    before: dict[int, dict[str, str | None]] = defaultdict(dict)
    imported_ids: set[int] = set()
    folders: set[int] = set()

    for track_id, entry_changes, entry_sources, changeset in rows:
        month = changeset.applied_at.strftime("%Y-%m")
        m = months.setdefault(month, Month(month, 0))
        m.count += 1
        if changeset.kind == "edit":
            m.edited += 1
        elif changeset.kind == "import":
            m.imported += 1
        else:
            m.other += 1
        if changeset.kind == "folder" and json.loads(changeset.details or "{}").get("created"):
            folders.add(changeset.id)
        if changeset.kind not in ("edit", "import"):
            continue  # moved, converted or marked final: no tag values

        changes = json.loads(entry_changes)
        known = json.loads(entry_sources or "{}")
        for name, (old, new) in changes.items():
            work = per_field.setdefault(_row(name), FieldWork(_row(name)))
            if new is None:
                work.removed += 1
            elif old in (None, ""):
                work.filled += 1
            else:
                work.corrected += 1
            stats.values += 1
            if name in known:
                sources[known[name]] += 1
            else:
                stats.unknown_source += 1
            if track_id is not None:
                before[track_id].setdefault(name, old)
        if changeset.kind == "import" and track_id is not None:
            imported_ids.add(track_id)
            before[track_id]  # counts for set-ready even without tag changes

    order = [writer.label(f) for f in writer.LABELS if f not in writer.IDS]
    order += [IDS_ROW, PRIVATE_ROW]
    stats.fields = sorted(per_field.values(), key=lambda w: order.index(w.label))
    total_known = sum(sources.values())
    stats.sources = [
        SourceBar(SOURCES.get(s, s), n, float(percent(n, total_known, 1)))
        for s, n in sources.most_common()
    ]
    stats.activity = _activity(months)
    stats.folders = len(folders)

    stats.tags_tracks = count(session, FLAGS["tagwerk_tags"][1])
    stats.imported = count(session, FLAGS["tagwerk_imported"][1])
    stats.converted = count(session, FLAGS["tagwerk_converted"][1])
    stats.final = count(session, FLAGS["final"][1])
    stats.ready_library, stats.ready_imported = _set_ready(session, before, imported_ids)
    return stats


def _activity(months: dict[str, Month]) -> list[Month]:
    """The last months with changes, gaps filled with empty months."""
    first, last = min(months), max(months)
    result = []
    year, mon = int(last[:4]), int(last[5:])
    while len(result) < ACTIVITY_MONTHS:
        key = f"{year}-{mon:02d}"
        result.append(months.get(key, Month(key, 0)))
        if key <= first:
            break
        year, mon = (year, mon - 1) if mon > 1 else (year - 1, 12)
    return result[::-1]


# What set-ready asks for (app.library.SET_READY), checked on values as the form shows them.
_READY_TEXT = ("title", "artist", "genre")


def _ready(track: Track, values: dict[str, str | None]) -> bool:
    """Set-ready, with ``values`` (field -> value as in the form) instead of the track's own."""

    def value(name: str) -> str | None:
        return values[name] if name in values else writer.current_value(track, name)

    return (
        track.error is None
        and all(value(name) for name in _READY_TEXT)
        and bool(value("bpm"))
        and to_camelot(value("key") or "") is not None
        and value(writer.COVER) is not None
    )


def _set_ready(
    session: Session, before: dict[int, dict[str, str | None]], imported_ids: set[int]
) -> tuple[ReadyWork | None, ReadyWork | None]:
    """Set-ready before Tagwerk's first change and now: library tracks Tagwerk wrote tags to,
    and tracks that came in through the inbox (before = as they arrived)."""
    groups = {"library": [0, 0, 0], "imported": [0, 0, 0]}  # tracks, before, now
    ids = list(before)
    for start in range(0, len(ids), 500):  # SQLite limits the number of parameters
        for track in session.exec(select(Track).where(col(Track.id).in_(ids[start : start + 500]))):
            group = groups["imported" if track.id in imported_ids else "library"]
            group[0] += 1
            group[1] += _ready(track, before[track.id])
            group[2] += _ready(track, {})
    library, imported = groups["library"], groups["imported"]
    return (
        ReadyWork(*library, url=TrackFilter(flag="tagwerk_edited").url()) if library[0] else None,
        ReadyWork(*imported, url=TrackFilter(flag="tagwerk_imported").url())
        if imported[0]
        else None,
    )


def home_line(session: Session) -> tuple[int, int] | None:
    """For Home: (tag values written, tracks), or None before Tagwerk changed anything."""
    values = 0
    for _, changes, _, changeset in _counted(session):
        if changeset.kind in ("edit", "import"):
            values += len(json.loads(changes))
    if not values:
        return None
    return values, count(session, FLAGS["tagwerk_tags"][1])
