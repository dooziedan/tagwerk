"""Discogs: the record collectors' database. Strong for electronic music, vinyl, labels and
catalog numbers. Needs the owner's free personal token (DISCOGS_TOKEN); 60 requests a minute.

The search finds *releases* that contain the track, so a candidate has the release's label,
catalog number, year, styles and cover, but not the track's own title or length. Its Discogs
release ID too; the artist ID needs the release itself (``release_artists``, one request).
"""

from app.sources.base import Candidate, Query, Source, year_or_date


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

    def release_artists(self, release_id: str) -> str | None:
        """The Discogs artist IDs of a release ("1; 2"), or None."""
        data = self.get_json(
            f"https://api.discogs.com/releases/{release_id}",
            headers={"Authorization": f"Discogs token={self.settings.discogs_token}"},
        )
        found = [str(a["id"]) for a in data.get("artists") or [] if a.get("id")]
        return "; ".join(found) or None


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
