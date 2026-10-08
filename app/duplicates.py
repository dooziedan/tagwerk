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
from sqlmodel import Session, col, select

from app import trash, writer
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


# --- Which copy to keep ----------------------------------------------------------------------
# Tagwerk suggests keeping the copy with the best sound: lossless before lossy, then the higher
# sample rate, bit depth and bitrate. Its tags may be the poorer ones, so the page compares them
# with the other copies, and the owner takes over what's missing or better (pending changes).

LOSSLESS = {"flac", "wav", "aiff"}
# Compared side by side and counted for "most tags": the edit form's fields, then the cover.
COMPARED = list(writer.EDITABLE)


@dataclass
class Copy:
    track: Track
    final: bool
    reason: str
    most_tags: bool = False  # clearly the most tags of its group

    def value(self, field: str) -> str | None:
        """A tag as the edit form shows it ("3/12" for the track number, "Am" for the key)."""
        return writer.current_value(self.track, field)

    @property
    def tags(self) -> int:
        filled = sum(1 for f in COMPARED if self.value(f) not in (None, ""))
        return filled + int(self.track.has_cover)

    @property
    def lossless(self) -> bool:
        t = self.track
        return t.format in LOSSLESS or (t.format == "m4a" and (t.bits_per_sample or 0) > 0)

    @property
    def sound(self) -> tuple:
        """For comparing audio quality: bigger is better."""
        t = self.track
        return (self.lossless, t.sample_rate or 0, t.bits_per_sample or 0, t.bitrate or 0)

    @property
    def quality(self) -> str:
        """The audio in words: "FLAC · 44.1 kHz · 16 bit", "MP3 · 320 kbps"."""
        t = self.track
        parts = [t.format.upper()]
        if self.lossless:
            if t.sample_rate:
                parts.append(f"{t.sample_rate / 1000:g} kHz")
            if t.bits_per_sample:
                parts.append(f"{t.bits_per_sample} bit")
        elif t.bitrate:
            parts.append(f"{round(t.bitrate / 1000)} kbps")
        return " · ".join(parts)


@dataclass
class Group:
    id: int
    copies: list[Copy]
    chosen: int | None = None  # track id of a copy the owner picks instead of the suggestion

    @property
    def reasons(self) -> list[str]:
        """Why they are grouped, strongest first."""
        found = {c.reason for c in self.copies}
        return sorted(found, key=lambda r: -STRENGTH[r])

    @property
    def suggested(self) -> Copy:
        """The copy to keep: the best sound; with the same sound, the most tags."""
        return max(self.copies, key=lambda c: (c.sound, c.tags, c.final, -c.track.id))

    @property
    def keeper(self) -> Copy:
        picked = [c for c in self.copies if c.track.id == self.chosen]
        return picked[0] if picked else self.suggested

    @property
    def ordered(self) -> list[Copy]:
        """The copy to keep first, then the others, best sound first."""
        others = [c for c in self.copies if c is not self.keeper]
        return [self.keeper, *sorted(others, key=lambda c: c.sound, reverse=True)]

    @property
    def why(self) -> str:
        """Why this copy is suggested, in plain words."""
        keeper = self.keeper
        if keeper is not self.suggested:
            return "Your choice."
        others = [c for c in self.copies if c is not keeper]
        if all(keeper.sound > c.sound for c in others):
            return f"The best sound: {keeper.quality}."
        if all(keeper.tags > c.tags for c in others):
            return "They sound the same; this one has the most tags."
        return "They sound the same and are tagged alike: any of them will do."

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
        return len({_shown(c.value(field)) for c in self.copies}) > 1

    def has(self, field: str) -> bool:
        """Does any copy have this tag?"""
        return any(c.value(field) not in (None, "") for c in self.copies)

    def offers(self, copy: Copy, field: str) -> bool:
        """Can the keeper take this copy's value? It has one, and the keeper's is different."""
        value = copy.value(field)
        return (
            copy is not self.keeper
            and value not in (None, "")
            and (_shown(value) != _shown(self.keeper.value(field)))
        )

    @property
    def missing(self) -> dict[str, str]:
        """Tags the keeper lacks where the other copies agree on one value: taken in one go."""
        found = {}
        for field in COMPARED:
            if self.keeper.value(field) in (None, ""):
                values = {c.value(field) for c in self.copies if c is not self.keeper} - {None, ""}
                if len(values) == 1:
                    found[field] = values.pop()
        return found


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
        tags = sorted((c.tags for c in group.copies), reverse=True)
        if tags[0] != tags[1]:  # only a clear winner gets the badge
            max(group.copies, key=lambda c: c.tags).most_tags = True
        result.append(group)
    return sorted(result, key=lambda g: g.name.casefold())


def same_group(session: Session, *track_ids: int) -> bool:
    """Are these tracks copies of each other (in one stored group)?"""
    rows = session.exec(select(DuplicateTrack).where(col(DuplicateTrack.track_id).in_(track_ids)))
    groups = {r.group_id for r in rows}
    found = session.exec(
        select(func.count())
        .select_from(DuplicateTrack)
        .where(col(DuplicateTrack.track_id).in_(track_ids))
    ).one()
    return len(groups) == 1 and found == len(set(track_ids))


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


# --- The library trash (ADR 0023) ------------------------------------------------------------
# The owner moves copies they don't want into /music/.tagwerk-trash from the Duplicates page.
# They stay there, restorable, until the owner empties the trash: Tagwerk never removes a
# library file on its own.


def trash_copy(session: Session, music_dir: Path, track_id: int, keep_id: int) -> str:
    """Move one copy of a duplicate group into the library trash; its row goes with it.

    Never the copy to keep (so one always stays) and never a final (locked) track. Returns the
    trash entry's id. The caller refreshes the groups and tells Navidrome.
    """
    group = next((g for g in load_groups(session) if track_id in {c.track.id for c in g.copies}),
                 None)  # fmt: skip
    if group is None or track_id == keep_id or keep_id not in {c.track.id for c in group.copies}:
        raise trash.TrashError("Only a copy other than the one you keep can go to the trash")
    if session.get(FinalTrack, track_id):
        raise trash.TrashError("It's final (locked): remove the mark on its track page first")
    track = session.get(Track, track_id)
    entry = trash.delete(music_dir, track.path)
    session.delete(track)  # its analysis, pending changes and duplicate rows go with it
    session.commit()
    return entry


def restore_copy(session: Session, music_dir: Path, entry: str) -> Track:
    """Move a trashed copy back to where it was and read it into the library again."""
    from app.scanner import store_file  # the scanner is only needed here

    rel = trash.restore(music_dir, entry)
    path = music_dir / rel
    track = store_file(session, path, rel, path.stat(), path.with_suffix(".lrc").exists(), None)
    session.commit()
    return track
