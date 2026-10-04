"""Duplicates: inbox tracks that may already be in the library.

Tagwerk only points them out; the owner decides (import anyway, or move the inbox file to the
trash, see app/trash.py). A library track counts as a likely copy when
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
from pathlib import Path

from sqlmodel import Session, select

from app.models import InboxTrack, Track

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


def _same_length(a: InboxTrack, b: Track) -> bool:
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
