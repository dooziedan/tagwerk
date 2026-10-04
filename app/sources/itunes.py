"""iTunes Search (Apple Music's store catalogue): no account needed.

Good for current releases: release date, a broad genre and large cover art. Apple asks for
about 20 requests a minute at most, so Tagwerk waits 3 seconds between them.
"""

import re

from app.sources.base import Candidate, Query, Source, year_or_date

_KIND = re.compile(r"\s+-\s+(?:Single|EP)$")  # "Losing It - Single" -> "Losing It"


class ITunes(Source):
    name = "itunes"
    label = "iTunes"
    gap = 3.0

    def lookup(self, query: Query) -> list[Candidate]:
        if not (query.search_artist and query.search_title):
            return []
        term = f"{query.search_artist} {query.search_title}"
        data = self.get_json(
            "https://itunes.apple.com/search",
            {"term": term, "entity": "song", "media": "music", "limit": 5},
        )
        return [_candidate(r) for r in data.get("results", []) if r.get("trackName")]


def _candidate(result: dict) -> Candidate:
    values = {"title": result["trackName"], "artist": result.get("artistName", "")}
    if result.get("collectionName"):
        values["album"] = _KIND.sub("", result["collectionName"])
    date = year_or_date(result.get("releaseDate"))
    if date:
        values["date"] = date
    if result.get("primaryGenreName"):
        values["genre"] = result["primaryGenreName"]
    artwork = result.get("artworkUrl100", "")
    millis = result.get("trackTimeMillis")
    return Candidate(
        source="itunes",
        values=values,
        url=result.get("trackViewUrl", ""),
        cover_url=artwork.replace("100x100bb", "1000x1000bb") if artwork else "",
        duration=millis / 1000 if millis else None,
    )
