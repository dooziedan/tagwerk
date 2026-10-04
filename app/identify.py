"""Online identification of inbox tracks (ADR 0014).

1. **Ask**: each switched-on source (app/sources/) is asked about the track, with the artist
   and title Tagwerk already knows (file, owner, filename) and, for AcoustID, the audio itself.
   Answers are stored (``onlinelookup``): pages show them without asking again, and a source
   is asked again only when the owner changed artist or title, or after REFRESH_AFTER.
2. **Score**: how well each candidate matches: title (with the mix name: an "Extended Mix" is
   not the "Radio Edit"), main artist, and length. AcoustID adds how alike the audio is.
3. **Suggest**: candidates that match well fill fields that are still empty. A value is
   **sure** when two sources agree on it, or when AcoustID recognised the audio clearly;
   otherwise the owner should check it. Tags in the file always win.

Inbox tracks get suggestions on their review page. **Library tracks** ("Look up online") get
the same lookups; their sure values become pending changes (stage_sure), so they go through the
Changes page like any edit, and final tracks stay untouched.

Network only, no files are written here: identification doesn't hold the library lock.
"""

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import Session, select

from app import changes, genres, preferences, writer
from app.config import Settings
from app.duplicates import main_artist, normalized
from app.images import MAX_SIZE, ImageError, ImageStore, image_info
from app.models import (
    InboxTrack,
    InboxValue,
    LibraryLookup,
    OnlineLookup,
    PendingChange,
    Track,
)
from app.proposals import Proposal, propose
from app.sources.acoustid import AcoustID
from app.sources.base import TIMEOUT, USER_AGENT, Candidate, Query, Source, SourceError
from app.sources.deezer import Deezer
from app.sources.discogs import Discogs
from app.sources.itunes import ITunes
from app.sources.musicbrainz import MusicBrainz

log = logging.getLogger(__name__)

SOURCES: list[type[Source]] = [AcoustID, MusicBrainz, Discogs, Deezer, ITunes]
LABELS = {s.name: s.label for s in SOURCES}
MATCH = 0.75  # candidates scoring at least this are used for suggestions
SURE_FINGERPRINT = 0.9  # AcoustID audio match that counts as sure on its own
KEEP = 5  # candidates stored per source
REFRESH_AFTER = timedelta(days=30)
# Fields online sources may fill (title and artist only when nothing else knows them).
FIELDS = ["title", "artist", "album", "date", "genre", "label", "catalognumber", "bpm"]


def enabled(settings: Settings, prefs: preferences.Preferences) -> list[Source]:
    """The sources the owner switched on that are set up (keys, tools)."""
    sources = [cls(settings) for cls in SOURCES if cls.name in prefs.online_sources]
    return [s for s in sources if s.configured()]


# --- Asking ---------------------------------------------------------------------------------


def query_for(session: Session, track: InboxTrack, import_dir: Path) -> Query:
    """What Tagwerk knows before asking: the owner's value, else the file's, else the filename."""
    mine = {
        r.field: r.value
        for r in session.exec(select(InboxValue).where(InboxValue.track_id == track.id))
    }
    suggested = {p.field: p.value for p in propose(track, genres.active(session))}

    def value(name: str) -> str | None:
        if name in mine:
            return mine[name]
        return suggested.get(name) or writer.current_value(track, name)

    return Query(value("artist"), value("title"), track.duration, import_dir / track.path)


def _table(library: bool) -> type[OnlineLookup] | type[LibraryLookup]:
    return LibraryLookup if library else OnlineLookup


def _row(session: Session, table, track_id: int, source: str):
    return session.get(table, {"track_id": track_id, "source": source})


def lookup(
    engine: Engine,
    settings: Settings,
    track_id: int,
    force: bool = False,
    images: ImageStore | None = None,
    library: bool = False,
) -> int:
    """Ask every enabled source about one inbox track. Returns how many were asked.

    For a track without cover art, the best matching cover is downloaded once into ``images``
    (kept with the candidate), so the review page can show it as a suggestion.
    """
    table = _table(library)
    with Session(engine) as session:
        track = session.get(Track if library else InboxTrack, track_id)
        if track is None or track.error:
            return 0
        prefs = preferences.load(session)
        if library:
            path = settings.music_dir / track.path
            query = Query(track.artist, track.title, track.duration, path)
        else:
            query = query_for(session, track, settings.import_dir)
        asked = 0
        for source in enabled(settings, prefs):
            row = _row(session, table, track.id, source.name)
            if not force and row and _fresh(row, query):
                continue
            try:
                found = source.lookup(query)
                error = None
            except SourceError as exc:
                found, error = [], str(exc)
            except Exception as exc:  # a source's odd answer must not stop the others
                log.warning("%s lookup failed for %s: %s", source.label, track.path, exc)
                found, error = [], f"{source.label}: unexpected answer"
            for candidate in found:
                candidate.score = score(candidate, query)
            found.sort(key=lambda c: c.score, reverse=True)
            row = row or table(track_id=track.id, source=source.name, query="")
            row.query = query.key()
            row.candidates = json.dumps([c.as_dict() for c in found[:KEEP]])
            row.error = error
            row.looked_up_at = datetime.now(UTC)
            session.add(row)
            session.commit()
            asked += 1
        if images is not None and not track.has_cover:
            _fetch_cover(session, track, images, table)
        if library:
            stage_sure(session, track)
        return asked


def stage_sure(session: Session, track: Track) -> int:
    """Turn a library track's sure online values into pending changes (for empty fields the
    owner hasn't edited yet). Final tracks are skipped by changes.stage(). Returns how many."""
    pending = {
        c.field
        for c in session.exec(select(PendingChange).where(PendingChange.track_id == track.id))
    }
    values = {
        p.field: p.value for p in suggestions(session, track, taken=pending, library=True) if p.sure
    }
    count = changes.stage(session, [track.id], values)[0] if values else 0
    cover = cover_suggestion(session, track, library=True)
    if cover and cover.sure and writer.COVER not in pending:
        count += changes.stage_cover(session, [track.id], cover.image_id)
    return count


def _fetch_cover(session: Session, track, images: ImageStore, table) -> None:
    """Download the cover of the best matching candidate that has one (once)."""
    rows = list(session.exec(select(table).where(table.track_id == track.id)))
    best: tuple[Candidate, OnlineLookup, list[dict]] | None = None
    for row in rows:
        stored = json.loads(row.candidates)
        if stored and any(c.get("cover_image") for c in stored):
            return  # already downloaded
        if stored:
            top = Candidate.from_dict(stored[0])
            if top.cover_url and top.score >= MATCH and (best is None or top.score > best[0].score):
                best = (top, row, stored)
    if best is None:
        return
    candidate, row, stored = best
    try:
        stored[0]["cover_image"] = images.put(download_image(candidate.cover_url))
    except (SourceError, ImageError) as exc:
        log.info("No cover from %s: %s", candidate.source, exc)
        return
    row.candidates = json.dumps(stored)
    session.add(row)
    session.commit()


def download_image(url: str) -> bytes:
    """An image from a source's cover URL (https only, at most MAX_SIZE)."""
    if not url.startswith("https://"):
        raise SourceError("not an https address")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            data = response.read(MAX_SIZE + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SourceError(f"cover download failed ({getattr(exc, 'reason', exc)})") from None
    if len(data) > MAX_SIZE:
        raise SourceError("the cover is too big")
    image_info(data)  # raises ImageError if it isn't a JPEG or PNG
    return data


def _fresh(row: OnlineLookup, query: Query) -> bool:
    looked_up = row.looked_up_at
    if looked_up.tzinfo is None:  # SQLite returns naive datetimes; they are stored as UTC
        looked_up = looked_up.replace(tzinfo=UTC)
    recent = datetime.now(UTC) - looked_up < REFRESH_AFTER
    return row.query == query.key() and recent and not row.error


# --- Scoring --------------------------------------------------------------------------------


def score(candidate: Candidate, query: Query) -> float:
    """How well a candidate matches the track, 0..1."""
    title = candidate.values.get("title")
    if title:
        title_match = _title_match(query.title, title)
    else:  # Discogs finds releases containing the track: the release title may be the track's
        title_match = max(_title_match(query.title, candidate.values.get("album")), 0.8)
    artist_match = _artist_match(query.artist, candidate.values.get("artist"))
    names = (title_match + artist_match) / 2
    if candidate.fingerprint_score is not None:  # AcoustID: the audio itself matched
        names = names if query.title and query.artist else 1.0
        return round(candidate.fingerprint_score * (0.6 + 0.4 * names), 3)
    return round(names * _length_match(query.duration, candidate.duration), 3)


def _title_match(wanted: str | None, found: str | None) -> float:
    if not wanted or not found:
        return 0.0
    a, b = normalized(wanted), normalized(found)
    if a == b:
        return 1.0
    if _base(a) == _base(b):  # "Losing It" vs "Losing It (Extended Mix)": maybe another version
        return 0.8
    if a.startswith(b + " ") or b.startswith(a + " "):  # "Rio" vs "Rio (Hush Remix)": a version
        return 0.8
    return SequenceMatcher(None, a, b).ratio() * 0.9


def _base(text: str) -> str:
    """The title without its version words (normalized() already dropped the brackets' marks)."""
    for word in ("original mix", "extended mix", "radio edit", "extended", "original", "mix"):
        text = text.replace(word, "")
    return " ".join(text.split())


def _artist_match(wanted: str | None, found: str | None) -> float:
    if not wanted or not found:
        return 0.0
    a, b = main_artist(wanted), main_artist(found)
    if a == b:
        return 1.0
    if a and b and (a in normalized(found) or b in normalized(wanted)):
        return 0.9
    return SequenceMatcher(None, a, b).ratio() * 0.9


def _length_match(wanted: float | None, found: float | None) -> float:
    if not wanted or not found:
        return 0.85  # unknown: a little less trust
    difference = abs(wanted - found)
    return 1.0 if difference <= 3 else 0.6 if difference <= 10 else 0.2


def explain(candidate: Candidate, query: Query) -> str:
    """Why a candidate scored as it did, in words: "same title and artist, but 3:49 long
    (this file: 0:01)". Uses the same comparisons as score()."""
    if candidate.values.get("title"):
        title = _title_match(query.title, candidate.values["title"])
        title_words = _words(title, "title", "another version of the title")
    else:
        title_words = "a release with this track"
    artist = _artist_match(query.artist, candidate.values.get("artist"))
    artist_words = _words(artist, "artist", "partly the same artist")
    if title_words == "same title" and artist_words == "same artist":
        names = "same title and artist"
    else:
        names = f"{title_words}, {artist_words}"
    if candidate.fingerprint_score is not None:
        return f"the sound matches ({candidate.fingerprint_score:.0%}); {names}"
    if not query.duration or not candidate.duration:
        return f"{names}; length unknown"
    if abs(query.duration - candidate.duration) <= 3:
        return f"{names}, same length"
    joiner = ", but" if names == "same title and artist" else ";"
    return f"{names}{joiner} {_mmss(candidate.duration)} long (this file: {_mmss(query.duration)})"


def _words(match: float, what: str, close: str) -> str:
    if match == 1.0:
        return f"same {what}"
    if match >= 0.8:
        return close
    return f"a similar {what}" if match >= 0.6 else f"a different {what}"


def _mmss(seconds: float) -> str:
    seconds = round(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


# --- Suggestions ----------------------------------------------------------------------------


@dataclass
class Found:
    """One source's answer for the review page."""

    source: str
    label: str
    candidates: list[Candidate] = field(default_factory=list)
    error: str | None = None
    looked_up_at: datetime | None = None

    @property
    def best(self) -> Candidate | None:
        return self.candidates[0] if self.candidates and self.candidates[0].score >= MATCH else None


def results(session: Session, track_id: int, library: bool = False) -> list[Found]:
    """What each source found for a track (in SOURCES order)."""
    table = _table(library)
    rows = {r.source: r for r in session.exec(select(table).where(table.track_id == track_id))}
    found = []
    for cls in SOURCES:
        row = rows.get(cls.name)
        if row:
            candidates = [Candidate.from_dict(c) for c in json.loads(row.candidates)]
            artist, title, duration = json.loads(row.query)  # what was asked (Query.key)
            asked = Query(artist, title, duration or None)
            for candidate in candidates:
                candidate.why = explain(candidate, asked)
            found.append(Found(cls.name, cls.label, candidates, row.error, row.looked_up_at))
    return found


def suggestions(session: Session, track, taken: set[str], library: bool = False) -> list[Proposal]:
    """Online suggestions for fields the file leaves empty and nothing else fills (``taken``)."""
    best = [f.best for f in results(session, track.id, library) if f.best]
    if not best:
        return []
    genre_map = genres.active(session)
    proposals = []
    for name in FIELDS:
        if name in taken or writer.current_value(track, name):
            continue
        groups: dict[str, list[tuple[Candidate, str]]] = {}
        for candidate in best:
            value = _value(name, candidate.values.get(name), genre_map)
            if value:
                groups.setdefault(_same(name, value), []).append((candidate, value))
        if not groups:
            continue
        group = max(groups.values(), key=lambda g: sum(c.score for c, _ in g))
        values = [v for _, v in group]
        # A full date beats a year, and the earliest is the original release.
        value = min(values, key=lambda v: (-len(v), v)) if name == "date" else max(values, key=len)
        sources = list(dict.fromkeys(c.source for c, _ in group))
        clear_audio = any(
            (c.fingerprint_score or 0) >= SURE_FINGERPRINT for c, _ in group
        ) and name in ("title", "artist", "album")
        sure = len(sources) >= 2 or clear_audio
        reason = " + ".join(LABELS[s] for s in sources) + (" agree" if len(sources) > 1 else "")
        if len(sources) == 1:
            reason += f" ({group[0][0].score:.0%} match)"
        proposals.append(Proposal(name, value, None, "online", sure, reason))
    return proposals


@dataclass
class CoverSuggestion:
    image_id: str
    source: str
    sure: bool
    reason: str


def cover_suggestion(session: Session, track, library: bool = False) -> CoverSuggestion | None:
    """The downloaded online cover for a track without one, and whether it's sure: two
    sources found the track, or AcoustID recognised the audio clearly."""
    if track.has_cover:
        return None
    found = results(session, track.id, library)
    matched = [f.best for f in found if f.best]
    for f in found:
        best = f.best
        if best and best.cover_image:
            clear = (best.fingerprint_score or 0) >= SURE_FINGERPRINT
            sure = len(matched) >= 2 or clear
            reason = f"{f.label} ({best.score:.0%} match)"
            return CoverSuggestion(best.cover_image, f.source, sure, reason)
    return None


def _value(name: str, value: str | None, genre_map) -> str | None:
    if not value:
        return None
    if name == "genre":
        value = "; ".join(genre_map.tidy([value]))
    try:
        return writer.normalize(name, value)
    except ValueError:
        return None


def _same(name: str, value: str) -> str:
    """When two sources say the same: compare dates by year, text without case/spelling."""
    if name == "date":
        return value[:4]
    return normalized(value)
