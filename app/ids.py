"""MusicBrainz and Discogs IDs: wrong values in MusicBrainz fields, and fixing them (ADR 0018).

Some taggers write Discogs numbers (or links) into the MusicBrainz ID fields. The scan only
flags this (``Track.mbid_invalid``); "Fix IDs" proposes pending changes that

- keep every real MusicBrainz ID,
- move Discogs numbers into their own fields: ``DISCOGS_RELEASE_ID`` from the track and
  album fields, ``DISCOGS_ARTIST_ID`` from the artist fields (Mp3tag's names),
- remove anything else (it isn't an ID Tagwerk or Navidrome could use).

Nothing is written before the owner applies the changes; undo restores the old values.
"""

import re
from dataclasses import dataclass

from sqlmodel import Session, col, select

from app import changes, writer
from app.models import Track
from app.tags import MBID_FIELDS, MBID_RE

# Where a Discogs number found in a MusicBrainz field belongs.
DISCOGS_FOR = {
    "mb_trackid": "discogs_releaseid",  # Discogs has no track IDs: it's the release
    "mb_albumid": "discogs_releaseid",
    "mb_artistid": "discogs_artistid",
    "mb_albumartistid": "discogs_artistid",
}
# Discogs links and the short forms in Discogs' own markup: [r123] release, [a123] artist.
_DISCOGS_LINK = re.compile(r"discogs\.com/(?:.*/)?(release|artist)/(\d+)", re.I)
_DISCOGS_MARKUP = re.compile(r"^\[([ra])=?(\d+)\]$", re.I)


@dataclass
class WrongId:
    field: str  # the MusicBrainz field, e.g. "mb_albumid"
    value: str  # the value that isn't a MusicBrainz ID
    moves_to: str | None  # the Discogs field it moves to, or None: it is removed
    number: str | None = None  # the Discogs number

    @property
    def label(self) -> str:
        return writer.label(self.field)

    @property
    def explanation(self) -> str:
        if self.moves_to:
            return f"Discogs number {self.number}: moves to {writer.label(self.moves_to)}"
        return "not an ID Tagwerk knows: removed"


def _discogs_number(field: str, value: str) -> tuple[str, str] | None:
    """(Discogs field, number) if the value is a Discogs number or link."""
    if value.isdigit():
        return DISCOGS_FOR[field], value
    if match := _DISCOGS_LINK.search(value) or _DISCOGS_MARKUP.match(value):
        kind, number = match.groups()
        kind = kind.lower()[0]  # "release"/"r" or "artist"/"a"
        return ("discogs_releaseid" if kind == "r" else "discogs_artistid"), number
    return None


def _parts(value: str | None) -> list[str]:
    return [p.strip() for p in (value or "").split(";") if p.strip()]


def wrong_ids(track: Track) -> list[WrongId]:
    """Every value in a MusicBrainz field that isn't a MusicBrainz ID."""
    found = []
    for field in MBID_FIELDS:
        for part in _parts(getattr(track, field)):
            if MBID_RE.match(part):
                continue
            discogs = _discogs_number(field, part)
            found.append(WrongId(field, part, *(discogs or (None, None))))
    return found


def fixes(track: Track) -> dict[str, str | None]:
    """The new values that fix a track's IDs (only fields that change)."""
    wrong = wrong_ids(track)
    if not wrong:
        return {}
    result: dict[str, str | None] = {}
    for field in {w.field for w in wrong}:
        kept = [p for p in _parts(getattr(track, field)) if MBID_RE.match(p)]
        result[field] = "; ".join(kept) or None
    for target in {w.moves_to for w in wrong if w.moves_to}:
        numbers = _parts(getattr(track, target)) + [w.number for w in wrong if w.moves_to == target]
        result[target] = "; ".join(dict.fromkeys(numbers))
    return result


def stage_fixes(session: Session, track_ids: list[int]) -> int:
    """Pending changes that fix the IDs of these tracks. Final tracks are skipped (locked).

    Returns how many pending changes were saved.
    """
    saved = 0
    tracks = session.exec(select(Track).where(col(Track.id).in_(track_ids), Track.mbid_invalid))
    for track in tracks.all():
        saved += changes.stage(session, [track.id], fixes(track), "fix-ids")[0]
    return saved
