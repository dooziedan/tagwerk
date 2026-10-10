"""Deezer's public API: no account needed.

The search gives title, artist, album, length and big cover art; the track and album pages
add release date, BPM, label and genre. Those two extra requests are only made for the best
search results (Deezer allows 50 requests per 5 seconds).
"""

from app.sources.base import Candidate, Query, Source, SourceError, year_or_date

DETAILS_FOR = 2  # search results that get the extra track and album requests


class Deezer(Source):
    name = "deezer"
    label = "Deezer"
    about = "Store: BPM, label, cover"
    gap = 0.2

    def lookup(self, query: Query) -> list[Candidate]:
        if not (query.search_artist and query.search_title):
            return []
        data = self.get_json(
            "https://api.deezer.com/search",
            {"q": f"{query.search_artist} {query.search_title}", "limit": 5},
        )
        if "error" in data:
            raise SourceError(f"Deezer: {data['error'].get('message', 'error')}")
        found = [r for r in data.get("data", []) if r.get("title")]
        return [self._candidate(r, details=i < DETAILS_FOR) for i, r in enumerate(found)]

    def _candidate(self, result: dict, details: bool) -> Candidate:
        album = result.get("album") or {}
        values = {"title": result["title"], "artist": (result.get("artist") or {}).get("name", "")}
        if album.get("title"):
            values["album"] = album["title"]
        if details:
            values.update(self._details(result.get("id"), album.get("id")))
        return Candidate(
            source="deezer",
            values=values,
            url=result.get("link", ""),
            cover_url=album.get("cover_xl", ""),
            duration=result.get("duration") or None,
        )

    def _details(self, track_id, album_id) -> dict[str, str]:
        values = {}
        if track_id:
            track = self.get_json(f"https://api.deezer.com/track/{track_id}")
            if track.get("bpm"):  # 0 means "unknown"
                values["bpm"] = str(round(float(track["bpm"])))
            date = year_or_date(track.get("release_date"))
            if date:
                values["date"] = date
        if album_id:
            album = self.get_json(f"https://api.deezer.com/album/{album_id}")
            if album.get("label"):
                values["label"] = album["label"]
            genres = [g["name"] for g in (album.get("genres") or {}).get("data", [])]
            if genres:
                values["genre"] = genres[0]
        return values
