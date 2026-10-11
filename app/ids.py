"""MusicBrainz and Discogs IDs: wrong values in MusicBrainz fields, and fixing them (ADR 0018).

Some taggers write Discogs numbers (or links) into the MusicBrainz ID fields. The scan only
flags this (``Track.mbid_invalid``); "Fix IDs" proposes pending changes that

- keep every real MusicBrainz ID,
- move Discogs numbers (also "release-position", e.g. 33199809-10) into their own fields:
  ``DISCOGS_RELEASE_ID`` from the track and album fields, ``DISCOGS_ARTIST_ID`` from the
  artist fields (Mp3tag's names),
- remove anything else (it isn't an ID Tagwerk or Navidrome could use).

Nothing is written before the owner applies the changes; undo restores the old values.
Inbox tracks are fixed while importing (ADR 0030): the review page shows what happens.

Correct IDs come from the online lookup (app/identify.py, ADR 0032); ``links`` gives each ID's
page at MusicBrainz or Discogs, so the owner can check where an ID points.
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from sqlmodel import Session, col, select

from app import changes, writer
from app.models import Track
from app.tags import MBID_FIELDS, MBID_RE, FileInfo, read_file

log = logging.getLogger(__name__)

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
# Release number and position, as some taggers write the track ID: "33199809-10" is track 10
# of release 33199809. Only the release number is kept.
_DISCOGS_POSITION = re.compile(r"^(\d+)-\d+$")
# Where each ID field's IDs have their page.
PAGES = {
    "mb_trackid": "https://musicbrainz.org/recording/{}",
    "mb_albumid": "https://musicbrainz.org/release/{}",
    "mb_artistid": "https://musicbrainz.org/artist/{}",
    "mb_albumartistid": "https://musicbrainz.org/artist/{}",
    "discogs_releaseid": "https://www.discogs.com/release/{}",
    "discogs_artistid": "https://www.discogs.com/artist/{}",
}


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
    if (match := _DISCOGS_POSITION.match(value)) and DISCOGS_FOR[field] == "discogs_releaseid":
        return "discogs_releaseid", match.group(1)
    if match := _DISCOGS_LINK.search(value) or _DISCOGS_MARKUP.match(value):
        kind, number = match.groups()
        kind = kind.lower()[0]  # "release"/"r" or "artist"/"a"
        return ("discogs_releaseid" if kind == "r" else "discogs_artistid"), number
    return None


def _parts(value: str | None) -> list[str]:
    return [p.strip() for p in (value or "").split(";") if p.strip()]


def wrong_ids(track: Track | FileInfo) -> list[WrongId]:
    """Every value in a MusicBrainz field that isn't a MusicBrainz ID."""
    found = []
    for field in MBID_FIELDS:
        for part in _parts(getattr(track, field)):
            if MBID_RE.match(part):
                continue
            discogs = _discogs_number(field, part)
            found.append(WrongId(field, part, *(discogs or (None, None))))
    return found


def fixes(track: Track | FileInfo) -> dict[str, str | None]:
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


def links(field: str, value: str | None) -> list[tuple[str, str | None]]:
    """Each ID in a field's value with its page: [(id, url)], url None for a value that isn't
    a real ID (or a field without pages). Several IDs are separated by ";"."""
    page = PAGES.get(field)
    result = []
    for part in _parts(value):
        real = MBID_RE.match(part) if field.startswith("mb_") else part.isdigit()
        result.append((part, page.format(part.lower()) if page and real else None))
    return result


# Short names for a list of links grouped by service: "MusicBrainz: recording · artist".
SERVICES = {"mb_": "MusicBrainz", "discogs_": "Discogs"}
SHORT = {
    "mb_trackid": "recording",
    "mb_albumid": "release",
    "mb_artistid": "artist",
    "mb_albumartistid": "album artist",
    "discogs_releaseid": "release",
    "discogs_artistid": "artist",
}


def link_groups(found: dict[str, str]) -> list[tuple[str, list[tuple[str, str]]]]:
    """A result's IDs as links grouped by service, for the Online sources card:
    [("MusicBrainz", [("recording", url), ("artist", url)]), ("Discogs", [...])]. Several
    artists get a number each ("artist 1", "artist 2")."""
    groups = []
    for prefix, service in SERVICES.items():
        links_ = []
        for field in PAGES:
            if not field.startswith(prefix):
                continue
            pages = [url for _, url in links(field, found.get(field)) if url]
            for n, url in enumerate(pages, 1):
                links_.append((f"{SHORT[field]} {n}" if len(pages) > 1 else SHORT[field], url))
        if links_:
            groups.append((service, links_))
    return groups


def file_ids(path: Path) -> dict[str, str | None] | None:
    """A file's ID fields as they are now, or None if it can't be read (inbox tracks don't keep
    every ID field)."""
    try:
        info = read_file(path)
    except Exception as exc:  # unreadable files are reported by the inbox check
        log.warning("Could not read the IDs of %s: %s", path, exc)
        return None
    return {name: getattr(info, name) for name in writer.IDS}


def in_file(path: Path) -> FileInfo | None:
    """The tags of a file whose MusicBrainz fields need fixing, else None.

    For inbox tracks: they don't keep every ID field, so the file is read when needed.
    """
    try:
        info = read_file(path)
    except Exception as exc:  # unreadable files are reported by the inbox check
        log.warning("Could not read the IDs of %s: %s", path, exc)
        return None
    return info if info.mbid_invalid else None


def stage_fixes(session: Session, track_ids: list[int]) -> int:
    """Pending changes that fix the IDs of these tracks. Final tracks are skipped (locked).

    Returns how many pending changes were saved.
    """
    saved = 0
    tracks = session.exec(select(Track).where(col(Track.id).in_(track_ids), Track.mbid_invalid))
    for track in tracks.all():
        saved += changes.stage(session, [track.id], fixes(track), "fix-ids")[0]
    return saved
