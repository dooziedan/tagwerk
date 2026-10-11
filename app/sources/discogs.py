"""Discogs: the record collectors' database. Strong for electronic music, vinyl, labels and
catalog numbers. Needs the owner's free personal token (DISCOGS_TOKEN); 60 requests a minute.

The search finds *releases* that contain the track, so a candidate has the release's label,
catalog number, year, styles and cover, but not the track's own title or length. Its Discogs
release ID too; the artist IDs and the tracklist need the release itself (``release``, one
request): app/identify.py finds the track there for its Discogs track ID ("release-position").
"""

from dataclasses import dataclass, field

from app.sources.base import Candidate, Query, Source, year_or_date


@dataclass
class Release:
    """What Discogs says about one release beyond the search answer."""

    artist_ids: str | None = None  # "1; 2"
    tracks: list[tuple[str, str, float | None]] = field(default_factory=list)  # position, title, s


class Discogs(Source):
    name = "discogs"
    label = "Discogs"
    about = "Labels and catalog numbers"
    gap = 1.1
    needs = "DISCOGS_TOKEN"

    def configured(self) -> bool:
        return bool(self.settings.discogs_token)

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
            headers={"Authorization": f"Discogs token={self.settings.discogs_token}"},
        )
        return [_candidate(r) for r in data.get("results", []) if r.get("title")]

    def release(self, release_id: str) -> Release:
        """A release's artist IDs and its tracks (headings and index entries left out)."""
        data = self.get_json(
            f"https://api.discogs.com/releases/{release_id}",
            headers={"Authorization": f"Discogs token={self.settings.discogs_token}"},
        )
        found = [str(a["id"]) for a in data.get("artists") or [] if a.get("id")]
        tracks = [
            (str(t.get("position") or "").strip(), t["title"], _seconds(t.get("duration")))
            for t in data.get("tracklist") or []
            if t.get("type_", "track") == "track" and t.get("title")
        ]
        return Release("; ".join(found) or None, tracks)


def _candidate(result: dict) -> Candidate:
    artist, _, release = result["title"].partition(" - ")
    values = {"artist": artist.strip()}
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
