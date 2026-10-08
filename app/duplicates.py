"""Duplicates: inbox tracks that may already be in the library, and tracks that are in the
library more than once (ADR 0011, ADR 0022).

Tagwerk only points them out; the owner decides (import anyway, or move the inbox file to the
trash, see app/trash.py; in the library: delete a copy in the file manager, or keep them all).
Library files are never deleted by Tagwerk. A track counts as a likely copy when
- it is the **identical file** (same size and same content), or
- it has the **same MusicBrainz recording ID**, trusted only when every library track with
  that ID has the same artist and title, the artist matches and the lengths are close (wrong
  IDs happen: some taggers copy one ID onto a whole EP), or
- it has the **same artist and title** and about the same length.

Titles are compared *with* the mix name: "Losing It (Extended Mix)" and "Losing It (Jus Ron
Edit)" are different tracks for a DJ. Only spelling is evened out (case, accents, "&"/"and",
"feat." parts, punctuation), and only the first artist counts ("Fisher & Kita Alexander" is
"Fisher"). Tags of an imported file change on import, so a re-downloaded copy is usually found
by artist and title, not by its content.
"""

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path, PurePosixPath

from sqlalchemy import Engine, delete, distinct, func
from sqlmodel import Session, select

from app.models import DuplicateTrack, FinalTrack, InboxTrack, NotDuplicate, Track

# Two versions of a track whose lengths differ more than this are different edits.
LENGTH_TOLERANCE = 3  # seconds

_FEAT = re.compile(r"[(\[]\s*(?:feat|ft|featuring)\b[^)\]]*[)\]]|\s(?:feat|ft|featuring)\b.*$")
_ARTIST_SPLIT = re.compile(r"\s*(?:;|,|&|\band\b|\bx\b|\bvs\b\.?|\bfeat\b|\bft\b|\bfeaturing\b)\s*")


def normalized(text: str | None) -> str:
    """Spelling evened out: "Beyoncé & JAY-Z" -> "beyonce and jay z"."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).casefold()
    text = _FEAT.sub(" ", text)
    text = re.sub(r"[^\w&]+", " ", text).replace("&", " and ")
    return " ".join(text.split())


def main_artist(artist: str | None) -> str:
    """The first artist, normalized: "Fisher; Kita Alexander" -> "fisher"."""
    folded = unicodedata.normalize("NFKD", artist or "").casefold()
    first = _ARTIST_SPLIT.split(folded.strip(), maxsplit=1)[0]
    return normalized(first)


@dataclass
class Match:
    track: Track  # the copy in the library
    reason: str  # why it looks like the same track


REASONS = {
    "file": "identical file",
    "mbid": "same MusicBrainz recording",
    "name": "same artist and title",
}


class LibraryIndex:
    """The library, looked up by artist and title, MusicBrainz ID and file size.

    Built once per page (one query), then each inbox track is a few dictionary lookups.
    """

    def __init__(self, tracks: list[Track]) -> None:
        self.by_name: dict[tuple[str, str], list[Track]] = {}
        self.by_mbid: dict[str, list[Track]] = {}
        self.by_size: dict[int, list[Track]] = {}
        for t in tracks:
            if t.title and t.artist:
                key = (main_artist(t.artist), normalized(t.title))
                self.by_name.setdefault(key, []).append(t)
            if t.mb_trackid:
                self.by_mbid.setdefault(t.mb_trackid.lower(), []).append(t)
            self.by_size.setdefault(t.size, []).append(t)

    @classmethod
    def load(cls, session: Session) -> "LibraryIndex":
        return cls(list(session.exec(select(Track).where(Track.error.is_(None)))))

    def matches(
        self,
        track: InboxTrack,
        title: str | None,
        artist: str | None,
        import_dir: Path,
        music_dir: Path,
    ) -> list[Match]:
        """Library copies of an inbox track. ``title``/``artist``: as they'll be on import."""
        found: dict[int, Match] = {}
        for t in self.by_size.get(track.size, []):  # same size: compare the contents
            if _same_content(import_dir / track.path, music_dir / t.path):
                found[t.id] = Match(t, REASONS["file"])
        if track.mb_trackid:
            # Wrong IDs happen (a tagger copying one ID onto a whole EP), so an ID only counts
            # when the library tracks carrying it agree on one artist and title, the inbox
            # track's artist (if known) is the same, and the lengths are close.
            same_id = self.by_mbid.get(track.mb_trackid.lower(), [])
            names = {(main_artist(t.artist), normalized(t.title)) for t in same_id}
            trusted = len(names) == 1 and (
                not artist or main_artist(artist) == next(iter(names))[0]
            )
            for t in same_id if trusted else []:
                if _same_length(track, t):
                    found.setdefault(t.id, Match(t, REASONS["mbid"]))
        if title and artist:
            for t in self.by_name.get((main_artist(artist), normalized(title)), []):
                if _same_length(track, t):  # else a different edit (e.g. radio vs extended)
                    found.setdefault(t.id, Match(t, REASONS["name"]))
        return sorted(found.values(), key=lambda m: m.track.path)


def _same_length(a: InboxTrack | Track, b: Track) -> bool:
    """About the same length; True when a length is unknown."""
    if not a.duration or not b.duration:
        return True
    return abs(a.duration - b.duration) <= LENGTH_TOLERANCE


def _same_content(a: Path, b: Path) -> bool:
    try:
        sa, sb = a.stat(), b.stat()
        return _sha256(str(a), sa.st_mtime, sa.st_size) == _sha256(str(b), sb.st_mtime, sb.st_size)
    except OSError:  # moved or removed in the meantime
        return False


@lru_cache(maxsize=256)
def _sha256(path: str, mtime: float, size: int) -> str:
    """Content hash; cached per file version (mtime and size are part of the key)."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


# --- Duplicates inside the library (ADR 0022) ----------------------------------------------
# The same three rules, applied to every pair of library tracks. Results are stored in the
# DuplicateTrack table, so pages and counts don't redo the work.

STRENGTH = {"file": 3, "mbid": 2, "name": 1}  # for a track's strongest link


def library_links(
    tracks: list[Track], music_dir: Path, apart: set[tuple[int, int]]
) -> list[tuple[int, int, str]]:
    """Pairs of library tracks that look like the same track: (smaller id, larger id, reason).

    ``apart``: pairs the owner keeps apart; they are never linked. Only small buckets are
    compared pairwise (same size, same ID, same artist and title), so this stays fast.
    """
    links: dict[tuple[int, int], str] = {}

    def link(a: Track, b: Track, reason: str) -> None:
        pair = (min(a.id, b.id), max(a.id, b.id))
        if pair not in apart and STRENGTH[reason] > STRENGTH.get(links.get(pair, ""), 0):
            links[pair] = reason

    index = LibraryIndex(tracks)
    for same_size in index.by_size.values():
        if len(same_size) > 1:  # rare for different files: then compare the contents
            hashes: dict[str, list[Track]] = {}
            for t in same_size:
                digest = _file_hash(music_dir / t.path)
                if digest:
                    hashes.setdefault(digest, []).append(t)
            for copies in hashes.values():
                for i, a in enumerate(copies):
                    for b in copies[i + 1 :]:
                        link(a, b, "file")
    for same_id in index.by_mbid.values():
        names = {(main_artist(t.artist), normalized(t.title)) for t in same_id}
        if len(same_id) > 1 and len(names) == 1:  # an ID only counts when its tracks agree
            for i, a in enumerate(same_id):
                for b in same_id[i + 1 :]:
                    if _same_length(a, b):
                        link(a, b, "mbid")
    for same_name in index.by_name.values():
        for i, a in enumerate(same_name):
            for b in same_name[i + 1 :]:
                if _same_length(a, b):  # else a different edit (e.g. radio vs extended)
                    link(a, b, "name")
    return [(a, b, reason) for (a, b), reason in links.items()]


def library_groups(links: list[tuple[int, int, str]]) -> dict[int, tuple[int, str]]:
    """Tracks linked directly or through another copy form one group.

    Returns {track id: (group id, strongest reason)}; the group id is its smallest track id.
    """
    parent: dict[int, int] = {}

    def root(x: int) -> int:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]  # shorten the path on the way
            x = parent[x]
        return x

    reason: dict[int, str] = {}
    for a, b, why in links:
        ra, rb = root(a), root(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
        for t in (a, b):
            if STRENGTH[why] > STRENGTH.get(reason.get(t, ""), 0):
                reason[t] = why
    return {t: (root(t), reason[t]) for t in reason}


def refresh_library(engine: Engine, music_dir: Path) -> int:
    """Work out the library's duplicate groups again and store them. Returns the group count."""
    with Session(engine) as session:
        tracks = list(session.exec(select(Track).where(Track.error.is_(None))))
        apart = {(n.track_a, n.track_b) for n in session.exec(select(NotDuplicate))}
        groups = library_groups(library_links(tracks, music_dir, apart))
        session.exec(delete(DuplicateTrack))
        session.add_all(
            DuplicateTrack(track_id=t, group_id=g, reason=why) for t, (g, why) in groups.items()
        )
        session.commit()
        return len({g for g, _ in groups.values()})


def keep_apart(session: Session, track_ids: list[int]) -> None:
    """The owner says these tracks are not duplicates (or wants every copy): every pair of
    them is kept apart from now on. The caller refreshes the groups."""
    ids = sorted(set(track_ids))
    known = {(n.track_a, n.track_b) for n in session.exec(select(NotDuplicate))}
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            if (a, b) not in known:
                session.add(NotDuplicate(track_a=a, track_b=b))
    session.commit()


def show_again(session: Session) -> int:
    """Forget every "not duplicates" choice. Returns how many pairs were kept apart."""
    pairs = list(session.exec(select(NotDuplicate)))
    for pair in pairs:
        session.delete(pair)
    session.commit()
    return len(pairs)


# Fields compared side by side on the Duplicates page, and counted for "most tags".
TAG_FIELDS = ["title", "artist", "album", "genre", "bpm", "key", "year", "label", "catalognumber"]
LOSSLESS = {"flac", "wav", "aiff"}


@dataclass
class Copy:
    track: Track
    final: bool
    reason: str
    best_sound: bool = False  # strictly the best audio of its group
    most_tags: bool = False  # strictly the most tags filled in

    @property
    def tags(self) -> int:
        return sum(1 for f in TAG_FIELDS if getattr(self.track, f) not in (None, "")) + int(
            self.track.has_cover
        )

    @property
    def sound(self) -> tuple:
        t = self.track
        lossless = t.format in LOSSLESS or (t.format == "m4a" and (t.bits_per_sample or 0) > 0)
        return (lossless, t.sample_rate or 0, t.bits_per_sample or 0, t.bitrate or 0)


@dataclass
class Group:
    id: int
    copies: list[Copy]

    @property
    def reasons(self) -> list[str]:
        """Why they are grouped, strongest first."""
        found = {c.reason for c in self.copies}
        return sorted(found, key=lambda r: -STRENGTH[r])

    @property
    def name(self) -> str:
        t = max(self.copies, key=lambda c: c.tags).track
        if t.title:
            return f"{t.artist} – {t.title}" if t.artist else t.title
        return PurePosixPath(t.path).name

    @property
    def extra_size(self) -> int:
        """Bytes beyond the largest copy: what deleting the other copies would free."""
        sizes = [c.track.size for c in self.copies]
        return sum(sizes) - max(sizes)

    def differs(self, field: str) -> bool:
        """Do the copies have different values (lengths: to the second)?"""
        if field == "duration":
            return len({round(c.track.duration or 0) for c in self.copies}) > 1
        return len({_shown(getattr(c.track, field)) for c in self.copies}) > 1


def _shown(value) -> str:
    return "" if value is None else str(value).strip().casefold()


def load_groups(session: Session, reason: str = "") -> list[Group]:
    """The stored duplicate groups with their copies, by name. ``reason``: only groups with it."""
    rows = session.exec(
        select(DuplicateTrack, Track).where(DuplicateTrack.track_id == Track.id)
    ).all()
    final = set(session.exec(select(FinalTrack.track_id)).all())
    groups: dict[int, Group] = {}
    for dup, track in rows:
        group = groups.setdefault(dup.group_id, Group(dup.group_id, []))
        group.copies.append(Copy(track, track.id in final, dup.reason))
    result = []
    for group in groups.values():
        if len(group.copies) < 2:  # a copy was removed since the last refresh
            continue
        if reason and reason not in group.reasons:
            continue
        group.copies.sort(key=lambda c: c.track.path)
        for attr, key in (("best_sound", lambda c: c.sound), ("most_tags", lambda c: c.tags)):
            values = sorted((key(c) for c in group.copies), reverse=True)
            if values[0] != values[1]:  # only a clear winner gets the badge
                setattr(max(group.copies, key=key), attr, True)
        result.append(group)
    return sorted(result, key=lambda g: g.name.casefold())


def group_count(session: Session) -> int:
    """How many tracks have copies in the library (the number on Home and Statistics)."""
    return session.exec(select(func.count(distinct(DuplicateTrack.group_id)))).one()


def group_of(session: Session, track_id: int) -> int | None:
    """The duplicate group a track belongs to, if any (the track page links to it)."""
    row = session.get(DuplicateTrack, track_id)
    if not row:
        return None
    others = session.exec(
        select(DuplicateTrack.track_id).where(DuplicateTrack.group_id == row.group_id).limit(2)
    ).all()
    return row.group_id if len(others) > 1 else None


def _file_hash(path: Path) -> str | None:
    try:
        st = path.stat()
        return _sha256(str(path), st.st_mtime, st.st_size)
    except OSError:  # moved or removed in the meantime
        return None
