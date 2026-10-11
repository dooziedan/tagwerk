"""Discogs: the record collectors' database. Strong for electronic music, vinyl, labels and
catalog numbers. Needs the owner's free personal token (DISCOGS_TOKEN); 60 requests a minute.

The search finds *releases* that contain the track: label, catalog number, year, styles,
cover and the Discogs release ID. The release itself (``release``, one request) adds the
artist IDs and the tracklist. It is read for the best releases right away, because one
release often holds several versions of the track (Original Mix 4:08, Extended Mix 6:41):
each version becomes its own candidate with its title and length, so the version of the file
can be recognised (ADR 0034). app/identify.py finds the track's Discogs track ID
("release-position") in the same answer; each release is asked once per lookup.
"""

import re
from dataclasses import dataclass, field, replace

from app.duplicates import normalized
from app.sources.base import Candidate, Query, Source, SourceError, year_or_date

DETAILS_FOR = 2  # search results whose tracklist is read (one request each)
# How Discogs tells artists with the same name apart: "Fisher (16)".
_TELL_APART = re.compile(r"\s+\(\d+\)$")


@dataclass
class Release:
    """What Discogs says about one release beyond the search answer."""

    artist_ids: str | None = None  # "1; 2"
    tracks: list[tuple[str, str, float | None]] = field(default_factory=list)  # position, title, s


class Discogs(Source):
    name = "discogs"
    label = "Discogs"
    about = "Labels, catalog numbers, versions"
    gap = 1.1
    needs = "DISCOGS_TOKEN"

    def __init__(self, settings) -> None:
        super().__init__(settings)
        self._releases: dict[str, Release] = {}  # asked during this lookup

    def configured(self) -> bool:
        return bool(self.settings.discogs_token)

    def _headers(self) -> dict:
        return {"Authorization": f"Discogs token={self.settings.discogs_token}"}

    def lookup(self, query: Query) -> list[Candidate]:
        if not (query.search_artist and query.search_title):
            return []
        data = self.get_json(
            "https://api.discogs.com/database/search",
            {
                "artist": query.search_artist,
                "track": query.search_title,
                "type": "release",
                "per_page": 5,
            },
            headers=self._headers(),
        )
        found = []
        for i, result in enumerate(r for r in data.get("results", []) if r.get("title")):
            release = _candidate(result)
            versions = self._versions(release, query) if i < DETAILS_FOR else []
            found.extend(versions or [release])
        return found

    def _versions(self, release: Candidate, query: Query) -> list[Candidate]:
        """The release's tracks whose title starts like the file's ("Losing It", "Losing It
        (Extended Mix)"), each as its own candidate with its title and length."""
        release_id = release.values.get("discogs_releaseid")
        wanted = normalized(query.base_title)
        if not (release_id and wanted):
            return []
        try:
            tracks = self.release(release_id).tracks
        except SourceError:  # the release's search answer is still good, just without versions
            return []
        return [
            replace(release, values={**release.values, "title": title}, duration=seconds)
            for _, title, seconds in tracks
            if normalized(title).startswith(wanted)
        ]

    def release(self, release_id: str) -> Release:
        """A release's artist IDs and its tracks (headings and index entries left out)."""
        if release_id in self._releases:  # the versions and the IDs need the same answer
            return self._releases[release_id]
        data = self.get_json(
            f"https://api.discogs.com/releases/{release_id}", headers=self._headers()
        )
        found = [str(a["id"]) for a in data.get("artists") or [] if a.get("id")]
        tracks = [
            (str(t.get("position") or "").strip(), t["title"], _seconds(t.get("duration")))
            for t in data.get("tracklist") or []
            if t.get("type_", "track") == "track" and t.get("title")
        ]
        self._releases[release_id] = Release("; ".join(found) or None, tracks)
        return self._releases[release_id]


def _candidate(result: dict) -> Candidate:
    artist, _, release = result["title"].partition(" - ")
    values = {"artist": _TELL_APART.sub("", artist.strip())}
    if result.get("id"):
        values["discogs_releaseid"] = str(result["id"])
    if release:
        values["album"] = release.strip()
    labels = result.get("label") or []
    if labels:
        values["label"] = labels[0]
    catno = (result.get("catno") or "").strip()
    if catno and catno.lower() != "none":
        values["catalognumber"] = catno
    date = year_or_date(str(result.get("year") or ""))
    if date:
        values["date"] = date
    styles = result.get("style") or result.get("genre") or []
    if styles:
        values["genre"] = styles[0]  # the most specific: "Tech House" rather than "Electronic"
    cover = result.get("cover_image", "")
    return Candidate(
        source="discogs",
        values=values,
        url=f"https://www.discogs.com{result['uri']}" if result.get("uri") else "",
        cover_url="" if cover.endswith("spacer.gif") else cover,
    )


def _seconds(text: str | None) -> float | None:
    """ "6:43" -> 403.0, "1:09:54" -> 4194.0; empty or odd -> None."""
    try:
        parts = [int(p) for p in (text or "").split(":")]
    except ValueError:
        return None
    if not parts or len(parts) > 3:
        return None
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + part
    return float(seconds) or None
