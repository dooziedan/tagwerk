"""Beatport: the DJ store. It sells the club versions (Original Mix, Extended Mix) that the
streaming stores often don't have, each with its own length, BPM, key, genre and label.

Beatport's API is only for approved partners, so Tagwerk reads the public search page the way
a browser does: the page carries its results as JSON (``__NEXT_DATA__``). Beatport's terms
allow personal, non-commercial use and its robots.txt allows every page. One request per
lookup, two seconds apart, no account. If Beatport changes the page, the lookup says so
instead of guessing (ADR 0034).
"""

import json
import re

from app.sources.base import Candidate, Query, Source, SourceError, year_or_date

SEARCH = "https://www.beatport.com/search/tracks"
_PAGE_DATA = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
# How Beatport tells artists with the same name apart: "FISHER (OZ)", "HOAX (1)".
_TELL_APART = re.compile(r"\s+\((?:\d+|[A-Z]{2,3})\)$")
RESULTS = 10  # the page has up to 150; the track is nearly always among the first five


class Beatport(Source):
    name = "beatport"
    label = "Beatport"
    about = "DJ store: club versions, BPM, key"
    gap = 2.0

    def lookup(self, query: Query) -> list[Candidate]:
        if not (query.search_artist and query.search_title):
            return []
        page = self.get_text(SEARCH, {"q": f"{query.search_artist} {query.search_title}"})
        found = _PAGE_DATA.search(page)
        try:
            data = json.loads(found.group(1)) if found else None
        except ValueError:
            data = None
        if data is None:
            raise SourceError("Beatport changed its page: Tagwerk can't read it yet")
        return [_candidate(t) for t in _tracks(data)[:RESULTS]]


def _tracks(data) -> list[dict]:
    """Every track on the page, in the page's order, wherever the JSON keeps them."""
    found: dict[int, dict] = {}

    def walk(value) -> None:
        if isinstance(value, dict):
            if "track_id" in value and "track_name" in value:
                found.setdefault(value["track_id"], value)
                return
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(data)
    return list(found.values())


def _candidate(track: dict) -> Candidate:
    name = track["track_name"]
    mix = (track.get("mix_name") or "").strip()  # "Original Mix", "Extended Mix", "Dub"
    artists = [_TELL_APART.sub("", a.get("artist_name") or "") for a in track.get("artists") or []]
    values = {
        "title": f"{name} ({mix})" if mix else name,
        "artist": ", ".join(dict.fromkeys(a for a in artists if a)),
    }
    release = track.get("release") or {}
    if release.get("release_name"):
        values["album"] = release["release_name"]
    date = year_or_date(track.get("release_date") or track.get("publish_date"))
    if date:
        values["date"] = date
    genre = track.get("genre")
    genre = (genre[0] if genre else {}) if isinstance(genre, list) else genre or {}
    if genre.get("genre_name"):
        values["genre"] = genre["genre_name"]
    label = (track.get("label") or {}).get("label_name")
    if label:
        values["label"] = label
    catno = (track.get("catalog_number") or "").strip()
    if catno and not (catno.isdigit() and len(catno) >= 10):  # a barcode isn't a catalog number
        values["catalognumber"] = catno
    if track.get("bpm"):
        values["bpm"] = str(round(float(track["bpm"])))
    if track.get("key_name"):
        values["key"] = track["key_name"]  # "Eb Minor"
    length = track.get("length_ms") or track.get("length")
    cover = release.get("release_image_uri") or ""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "track"
    return Candidate(
        source="beatport",
        values=values,
        url=f"https://www.beatport.com/track/{slug}/{track['track_id']}",
        cover_url=cover if cover.startswith("https://") else "",
        duration=length / 1000 if length else None,
    )
