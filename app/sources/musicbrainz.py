"""MusicBrainz: the open music encyclopedia. Search by artist and title; no account needed.

Rate limit: one request per second, with a User-Agent naming the app (base.py does both).
Good for official releases; edits, bootlegs and promos are usually missing.
"""

import re

from app.sources.base import Candidate, Query, Source, year_or_date

_SPECIAL = re.compile(r'([+\-&|!(){}\[\]^"~*?:\\/])')  # Lucene's special characters


class MusicBrainz(Source):
    name = "musicbrainz"
    label = "MusicBrainz"
    about = "Open music encyclopedia"
    gap = 1.1

    def lookup(self, query: Query) -> list[Candidate]:
        if not (query.search_artist and query.search_title):
            return []
        search = (
            f'artist:"{_escape(query.search_artist)}" AND recording:"{_escape(query.search_title)}"'
        )
        data = self.get_json(
            "https://musicbrainz.org/ws/2/recording", {"query": search, "fmt": "json", "limit": 5}
        )
        return [_candidate(r) for r in data.get("recordings", []) if r.get("title")]


def _escape(text: str) -> str:
    return _SPECIAL.sub(r"\\\1", text)


def _candidate(recording: dict) -> Candidate:
    artist = "".join(
        c.get("name", "") + c.get("joinphrase", "") for c in recording.get("artist-credit", [])
    )
    values = {"title": recording["title"], "artist": artist.strip()}
    date = year_or_date(recording.get("first-release-date"))
    if date:
        values["date"] = date
    release = _release(recording)
    if release:
        values["album"] = release["title"]
    length = recording.get("length")
    return Candidate(
        source="musicbrainz",
        values=values,
        url=f"https://musicbrainz.org/recording/{recording['id']}",
        duration=length / 1000 if length else None,
    )


def _release(recording: dict) -> dict | None:
    """The track's own release (official, earliest), or None when it's only on compilations:
    "The Annual 2019" isn't the album of a club track."""
    releases = [
        r
        for r in recording.get("releases") or []
        if r.get("status", "Official") == "Official"
        and "Compilation" not in ((r.get("release-group") or {}).get("secondary-types") or [])
    ]
    return min(releases, key=lambda r: r.get("date") or "9999", default=None)
