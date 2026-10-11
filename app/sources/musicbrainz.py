"""MusicBrainz: the open music encyclopedia. Search by artist and title; no account needed.

Rate limit: one request per second, with a User-Agent naming the app (base.py does both).
Good for official releases; edits, bootlegs and promos are usually missing.

Each candidate also carries the MusicBrainz IDs of the recording, its artists and its release
(``mb_trackid`` …); app/identify.py decides whether they are sure enough to suggest (ADR 0032).
"""

import re

from app.sources.base import Candidate, Query, Source, year_or_date

_SPECIAL = re.compile(r'([+\-&|!(){}\[\]^"~*?:\\/])')  # Lucene's special characters
_DISCOGS_RELEASE = re.compile(r"discogs\.com/(?:.*/)?release/(\d+)")


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

    def discogs_release(self, release_id: str) -> str | None:
        """The Discogs release a MusicBrainz release links to (its "discogs" URL), or None."""
        data = self.get_json(
            f"https://musicbrainz.org/ws/2/release/{release_id}", {"inc": "url-rels", "fmt": "json"}
        )
        for relation in data.get("relations") or []:
            url = (relation.get("url") or {}).get("resource", "")
            if relation.get("type") == "discogs" and (match := _DISCOGS_RELEASE.search(url)):
                return match.group(1)
        return None


def _escape(text: str) -> str:
    return _SPECIAL.sub(r"\\\1", text)


def _candidate(recording: dict) -> Candidate:
    artist = "".join(
        c.get("name", "") + c.get("joinphrase", "") for c in recording.get("artist-credit", [])
    )
    values = {"title": recording["title"], "artist": artist.strip(), "mb_trackid": recording["id"]}
    values |= _artist_ids("mb_artistid", recording.get("artist-credit"))
    date = year_or_date(recording.get("first-release-date"))
    if date:
        values["date"] = date
    release = _release(recording)
    if release:
        values["album"] = release["title"]
        values["mb_albumid"] = release["id"]
        values |= _artist_ids("mb_albumartistid", release.get("artist-credit"))
    length = recording.get("length")
    return Candidate(
        source="musicbrainz",
        values=values,
        url=f"https://musicbrainz.org/recording/{recording['id']}",
        duration=length / 1000 if length else None,
    )


def _artist_ids(field: str, credit: list | None) -> dict[str, str]:
    """{"mb_artistid": "id1; id2"} for an artist credit with several artists ({} without)."""
    found = [c["artist"]["id"] for c in credit or [] if (c.get("artist") or {}).get("id")]
    return {field: "; ".join(found)} if found else {}


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
