"""Statistics for the Tag fields page, computed from the ``rawtag`` table."""

from dataclasses import dataclass, field

from sqlalchemy import case, distinct, func
from sqlmodel import Session, col, select

from app.models import RawTag, Track
from app.rawtags import used_as

# Values that mean "unknown" for numeric fields like BPM (Picard writes "0").
ZERO_VALUES = ("0", "0.0", "0.00", "00")


@dataclass
class FieldSummary:
    system: str
    name: str
    used_as: str | None  # the Tagwerk field it feeds, None if ignored
    files: int
    percent: float  # of all tracks
    empty: int  # files where the value is empty
    zero: int  # files where the value is 0
    distinct: int  # different values
    samples: list[tuple[str, int]] = field(default_factory=list)  # most common values


@dataclass
class FieldDetail:
    summary: FieldSummary
    values: list[tuple[str, int]]  # value, files; most common first
    examples: list[tuple[str, str]]  # path, value


def field_overview(session: Session, samples: int = 3) -> list[FieldSummary]:
    tracks = session.exec(select(func.count(Track.id))).one()
    rows = session.exec(_summary_query()).all()

    # The most common values per field, using a window function (one query for all fields).
    n = func.count(RawTag.id)
    ranked = (
        select(
            RawTag.system,
            RawTag.name,
            RawTag.value,
            n.label("n"),
            func.row_number()
            .over(partition_by=(RawTag.system, RawTag.name), order_by=(n.desc(), RawTag.value))
            .label("rank"),
        )
        .group_by(RawTag.system, RawTag.name, RawTag.value)
        .subquery()
    )
    top: dict[tuple[str, str], list[tuple[str, int]]] = {}
    for system, name, value, count in session.exec(
        select(ranked.c.system, ranked.c.name, ranked.c.value, ranked.c.n).where(
            ranked.c.rank <= samples
        )
    ):
        top.setdefault((system, name), []).append((value, count))

    return [_summary(row, tracks, top.get((row[0], row[1]), [])) for row in rows]


def field_detail(
    session: Session, system: str, name: str, limit: int = 100, examples: int = 25
) -> FieldDetail | None:
    row = session.exec(
        _summary_query().where(RawTag.system == system, RawTag.name == name)
    ).one_or_none()
    if row is None:
        return None
    tracks = session.exec(select(func.count(Track.id))).one()
    where = (RawTag.system == system, RawTag.name == name)
    n = func.count(RawTag.id)
    values = session.exec(
        select(RawTag.value, n).where(*where).group_by(RawTag.value).order_by(n.desc()).limit(limit)
    ).all()
    files = session.exec(
        select(Track.path, RawTag.value)
        .join(Track, col(Track.id) == RawTag.track_id)
        .where(*where)
        .order_by(Track.path)
        .limit(examples)
    ).all()
    return FieldDetail(_summary(row, tracks, list(values[:3])), list(values), list(files))


def _summary_query():
    return (
        select(
            RawTag.system,
            RawTag.name,
            func.count(distinct(RawTag.track_id)),
            func.sum(case((RawTag.value == "", 1), else_=0)),
            func.sum(case((col(RawTag.value).in_(ZERO_VALUES), 1), else_=0)),
            func.count(distinct(RawTag.value)),
        )
        .group_by(RawTag.system, RawTag.name)
        .order_by(func.count(distinct(RawTag.track_id)).desc(), RawTag.system, RawTag.name)
    )


def _summary(row, tracks: int, samples: list[tuple[str, int]]) -> FieldSummary:
    system, name, files, empty, zero, distinct_values = row
    return FieldSummary(
        system=system,
        name=name,
        used_as=used_as(system, name),
        files=files,
        percent=round(100 * files / tracks, 1) if tracks else 0.0,
        empty=empty or 0,
        zero=zero or 0,
        distinct=distinct_values,
        samples=samples,
    )
