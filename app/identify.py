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
4. **IDs** (ADR 0032): MusicBrainz and Discogs IDs follow stricter rules, because a wrong ID is
   worse than none (Navidrome and Picard trust it). Only sure IDs are suggested, only for empty
   ID fields: see id_suggestions().
5. **Versions** (ADR 0034): when the file is longer than the only version some sources have
   (stores often sell the 4:09 radio edit of a 5:26 club mix), longer_version() says so, and
   which sources list this length (Beatport, Discogs tracklists).

Inbox tracks get suggestions on their review page. **Library tracks** ("Look up online") get
the same lookups; their sure values become pending changes (stage_sure), so they go through the
Changes page like any edit, and final tracks stay untouched.

Network only, no files are written here: identification doesn't hold the library lock.
"""

import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import Session, select

from app import changes, genres, notifications, preferences, secret, writer
from app.config import Settings
from app.duplicates import ORIGINAL, VERSION_WORDS, main_artist, normalized
from app.images import MAX_SIZE, ImageError, ImageStore, image_info
from app.models import (
    InboxTrack,
    InboxValue,
    LibraryAnalysis,
    LibraryLookup,
    OnlineLookup,
    PendingChange,
    Track,
)
from app.proposals import Proposal, propose
from app.sources.acoustid import AcoustID
from app.sources.base import (
    TIMEOUT,
    USER_AGENT,
    Candidate,
    KeyRefused,
    Query,
    Source,
    SourceError,
)
from app.sources.beatport import Beatport
from app.sources.deezer import Deezer
from app.sources.discogs import Discogs
from app.sources.itunes import ITunes
from app.sources.musicbrainz import MusicBrainz
from app.tags import MBID_FIELDS, MBID_RE

log = logging.getLogger(__name__)

SOURCES: list[type[Source]] = [AcoustID, MusicBrainz, Discogs, Beatport, Deezer, ITunes]
LABELS = {s.name: s.label for s in SOURCES}
MATCH = 0.75  # candidates scoring at least this are used for suggestions
SURE_FINGERPRINT = 0.9  # AcoustID audio match that counts as sure on its own
KEEP = 5  # candidates stored per source
REFRESH_AFTER = timedelta(days=30)
# Fields online sources may fill (title and artist only when nothing else knows them).
FIELDS = ["title", "artist", "album", "date", "genre", "label", "catalognumber", "bpm"]
# What an ID suggestion needs to know about the track (see id_suggestions()).
CONTEXT = ("album", "label", "catalognumber")


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

    Secret tracks (app/secret.py) are never looked up; a track marked secret while its
    sources are asked keeps none of the answers.
    """
    table = _table(library)
    with Session(engine) as session:
        track = session.get(Track if library else InboxTrack, track_id)
        if track is None or track.error or secret.is_secret(session, track_id, inbox=not library):
            return 0
        prefs = preferences.load(session)
        if library:
            path = settings.music_dir / track.path
            query = Query(track.artist, track.title, track.duration, path)
        else:
            query = query_for(session, track, settings.import_dir)
        asked = 0
        sources = enabled(settings, prefs)
        asked_now = set()
        for source in sources:
            row = _row(session, table, track.id, source.name)
            if not force and row and _fresh(row, query):
                continue
            refused = False
            try:
                found = source.lookup(query)
                error = None
            except SourceError as exc:
                found, error, refused = [], str(exc), isinstance(exc, KeyRefused)
            except Exception as exc:  # a source's odd answer must not stop the others
                log.warning("%s lookup failed for %s: %s", source.label, track.path, exc)
                found, error = [], f"{source.label}: unexpected answer"
            if secret.is_secret(session, track_id, inbox=not library):
                return asked  # marked secret meanwhile: this answer isn't kept, nobody else asked
            _report(engine, source, error, refused)
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
            asked_now.add(source.name)
        if asked_now:
            sources_by_name = {s.name: s for s in sources}
            _look_up_ids(session, track.id, table, sources_by_name, asked_now, query)
        if images is not None and not track.has_cover:
            _fetch_cover(session, track, images, table)
        if library:
            stage_sure(session, track)
        return asked


# A source that stops working is reported once (notifications, ADR 0035): a refused key at
# once, other errors after this many failed lookups in a row; and once when it answers again.
FAILING_AFTER = 5
_failures: dict[str, int] = {}  # source name -> failed lookups in a row


def _report(engine: Engine, source: Source, error: str | None, refused: bool) -> None:
    key = f"online:{source.name}"
    if error is None:
        _failures.pop(source.name, None)
        notifications.solved(
            "online", key, f"{source.label} answers again",
            f"Lookups with {source.label} work again.", "Online lookup", "/settings#online", engine,
        )  # fmt: skip
        return
    _failures[source.name] = _failures.get(source.name, 0) + 1
    if refused:
        summary = f"{source.label} refused Tagwerk's key"
    elif _failures[source.name] >= FAILING_AFTER:
        summary = f"{source.label} keeps failing"
    else:
        return
    notifications.problem(
        "online", key, summary,
        f"{error}. Lookups go on with the other sources. Tagwerk tells you once more when "
        f"{source.label} answers again.",
        "Online lookup", "/settings#online", engine,
    )  # fmt: skip


def stage_sure(session: Session, track: Track) -> int:
    """Turn a library track's sure online values into pending changes (for empty fields the
    owner hasn't edited yet). Final tracks are skipped by changes.stage(). Returns how many."""
    staged = {
        c.field: c.new_value
        for c in session.exec(select(PendingChange).where(PendingChange.track_id == track.id))
    }
    pending = set(staged)
    values = {
        p.field: p.value for p in suggestions(session, track, taken=pending, library=True) if p.sure
    }
    if session.get(LibraryAnalysis, track.id):
        # The audio decides the BPM, with online values as hints (analysis.stage_sure): two
        # stores agreeing on 87 doesn't make a drum & bass track 87 BPM.
        values.pop("bpm", None)
    current = {name: writer.current_value(track, name) for name in writer.IDS}
    # The album, label and catalog number the track will have: its tag, else a pending change
    # (the owner's, or a sure value from an earlier lookup), else a sure value found now.
    context = {
        name: writer.current_value(track, name) or staged.get(name) or values.get(name)
        for name in CONTEXT
    }
    for p in id_suggestions(session, track, current, context, taken=pending, library=True):
        values[p.field] = p.value
    count = changes.stage(session, [track.id], values, "online")[0] if values else 0
    cover = cover_suggestion(session, track, library=True)
    if cover and cover.sure and writer.COVER not in pending:
        count += changes.stage_cover(session, [track.id], cover.image_id, "online")
    return count


def _look_up_ids(
    session: Session, track_id: int, table, sources: dict, asked: set[str], query: Query
) -> None:
    """IDs the searches don't give, one request each and only for the best match of a source
    asked just now: the Discogs release's artist IDs and the track's Discogs track ID (from the
    release's tracklist), and the Discogs release a MusicBrainz release links to (with Discogs
    switched on). A failed request only leaves those IDs out."""
    rows = {r.source: r for r in session.exec(select(table).where(table.track_id == track_id))}
    discogs, musicbrainz = sources.get("discogs"), sources.get("musicbrainz")

    def from_discogs(release_id: str) -> dict[str, str | None]:
        release = discogs.release(release_id)
        track = _discogs_track(release.tracks, query)
        return {
            "discogs_artistid": release.artist_ids,
            "discogs_trackid": f"{release_id}-{track}" if track else None,
        }

    def from_musicbrainz(release_id: str) -> dict[str, str | None]:
        return {"discogs_releaseid": musicbrainz.discogs_release(release_id)}

    wanted = []  # (source, the ID it needs, how to ask)
    if discogs and "discogs" in asked:
        wanted.append(("discogs", "discogs_releaseid", from_discogs))
    if musicbrainz and discogs and "musicbrainz" in asked:
        wanted.append(("musicbrainz", "mb_albumid", from_musicbrainz))
    for name, needs, ask in wanted:
        row = rows.get(name)
        stored = json.loads(row.candidates) if row else []
        if not stored or stored[0].get("score", 0) < MATCH or not stored[0]["values"].get(needs):
            continue
        try:
            found = {k: v for k, v in ask(stored[0]["values"][needs]).items() if v}
        except SourceError as exc:
            log.info("No more IDs from %s: %s", name, exc)
            continue
        except Exception as exc:  # an odd answer must not stop the lookup
            log.warning("%s: unexpected answer while asking for IDs: %s", name, exc)
            continue
        if found:
            stored[0]["values"].update(found)
            row.candidates = json.dumps(stored)
            session.add(row)
            session.commit()


def _discogs_track(tracks: list[tuple[str, str, float | None]], query: Query) -> str | None:
    """The track's position on a Discogs release ("3", "A1"): the only track with its title
    (another version's title only when the length agrees, within 3 s). Without a length the
    title must be exactly the same: here "(Original Mix)" isn't the plain title (ADR 0033)."""
    found = []
    for position, title, seconds in tracks:
        match = _title_match(query.title, title)
        exact = normalized(query.title or "") == normalized(title)
        known = bool(seconds and query.duration)
        same_length = known and abs(seconds - query.duration) <= 3
        if (same_length and match >= 0.8) or (not known and exact):
            found.append(position)
    return found[0] if len(found) == 1 and found[0] else None


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


_ORIGINAL = ORIGINAL  # "(Original Mix)" is the plain version (app/duplicates.py)


def _title_match(wanted: str | None, found: str | None) -> float:
    if not wanted or not found:
        return 0.0
    a, b = normalized(_ORIGINAL.sub("", wanted)), normalized(_ORIGINAL.sub("", found))
    if a == b:
        return 1.0
    if _base(a) == _base(b):  # "Losing It" vs "Losing It (Extended Mix)": maybe another version
        return 0.8
    if a.startswith(b + " ") or b.startswith(a + " "):  # "Rio" vs "Rio (Hush Remix)": a version
        return 0.8
    return SequenceMatcher(None, a, b).ratio() * 0.9


_VERSION_WORDS = VERSION_WORDS  # the length decides the version (app/duplicates.py)


def _base(text: str) -> str:
    """The title without its version words (normalized() already dropped the brackets' marks):
    "losing it radio mix" -> "losing it". A title that is only such a word ("Radio") stays."""
    return _VERSION_WORDS.sub("", text)


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
    about: str = ""  # what the source is good for (Source.about)
    fields: list[list["Compared"]] = field(default_factory=list)  # per candidate, see review()
    ids: list[dict[str, str]] = field(default_factory=list)  # per candidate: candidate_ids()
    asked: Query | None = None  # what the source was asked (artist, title, length)

    @property
    def best(self) -> Candidate | None:
        return self.candidates[0] if self.candidates and self.candidates[0].score >= MATCH else None


def results(session: Session, track_id: int, library: bool = False) -> list[Found]:
    """What each source found for a track (in SOURCES order).

    Genres come matched against the owner's genre map (iTunes' "Jungle/Drum'n'bass" ->
    "Drum & Bass"), so the page, "Use these values" and pending changes all get the tidy
    genre. The stored answer keeps the source's spelling: a changed map applies right away.
    """
    table = _table(library)
    rows = {r.source: r for r in session.exec(select(table).where(table.track_id == track_id))}
    genre_map = genres.active(session)
    found = []
    for cls in SOURCES:
        row = rows.get(cls.name)
        if row:
            candidates = [Candidate.from_dict(c) for c in json.loads(row.candidates)]
            artist, title, duration = json.loads(row.query)  # what was asked (Query.key)
            asked = Query(artist, title, duration or None)
            for candidate in candidates:
                candidate.why = explain(candidate, asked)
                if candidate.values.get("genre"):
                    candidate.values["genre"] = genre_map.match(candidate.values["genre"])
            found.append(
                Found(
                    cls.name,
                    cls.label,
                    candidates,
                    row.error,
                    row.looked_up_at,
                    cls.about,
                    asked=asked,
                )
            )
    return found


# What the "Online sources" card shows of each candidate, beside title and artist.
SHOWN = {
    "album": "Album",
    "date": "Released",
    "label": "Label",
    "catalognumber": "Catalog no.",
    "genre": "Genre",
    "bpm": "BPM",
    "key": "Key",
}


@dataclass
class Compared:
    """One value a source found, next to what the file says: "same", "new" (the file has
    nothing there) or "differs" (``yours`` is the file's value)."""

    name: str
    label: str
    value: str
    state: str
    yours: str | None = None


def review(session: Session, track, library: bool = False) -> list[Found]:
    """results() for the track and inbox pages: each candidate's values compared with the
    file's tags, so the owner sees what "Use these values" would change."""
    found = results(session, track.id, library)
    genre_map = genres.active(session)
    for f in found:
        f.fields = [compare(c, track, genre_map) for c in f.candidates]
        f.ids = [candidate_ids(c) for c in f.candidates]
    return found


def compare(candidate: Candidate, track, genre_map) -> list[Compared]:
    out = []
    for name, label in SHOWN.items():
        value = candidate.values.get(name)
        if not value:
            continue
        yours = writer.current_value(track, name)
        if not yours:
            state = "new"
        else:
            # Like suggestions: dates by year, text without case or spelling differences.
            mine, theirs = _value(name, yours, genre_map), _value(name, value, genre_map)
            same = mine and theirs and _same(name, mine) == _same(name, theirs)
            state = "same" if same else "differs"
        out.append(Compared(name, label, value, state, yours))
    return out


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


def candidate_ids(candidate: Candidate) -> dict[str, str]:
    """The valid MusicBrainz and Discogs IDs a candidate carries, normalized; odd values
    (not an MBID, not a number) are left out."""
    found = {}
    for name in writer.IDS:
        try:
            value = writer.normalize(name, candidate.values.get(name))
        except ValueError:
            continue
        if value:
            found[name] = value
    return found


def ids_to_take(candidate: Candidate, current: dict[str, str | None]) -> dict[str, str]:
    """The IDs "Use these values" takes from one result: only for empty ID fields, and no
    MusicBrainz IDs while a MusicBrainz field holds something else (Fix IDs first)."""
    wrong = _wrong_mbid(current)
    return {
        name: value
        for name, value in candidate_ids(candidate).items()
        if not current.get(name) and not (wrong and name in MBID_FIELDS)
    }


def id_suggestions(
    session: Session,
    track,
    current: dict[str, str | None],
    context: dict[str, str | None],
    taken: set[str] = frozenset(),
    library: bool = False,
) -> list[Proposal]:
    """Sure MusicBrainz and Discogs IDs for the track's empty ID fields (ADR 0032).

    ``current``: the ID fields as the file has them now (only empty ones are filled, and no
    MusicBrainz ID is suggested while a MusicBrainz field holds something else: Fix IDs first).
    ``context``: the album, label and catalog number the track has or gets (its own tags or
    sure suggestions). ``taken``: fields the owner already edited. Everything else a source
    found waits on the page, where "Use these values" takes it over.
    """
    found = {f.source: f for f in results(session, track.id, library)}
    sure = {} if _wrong_mbid(current) else _musicbrainz_ids(found, context)
    sure |= _discogs_ids(found, context)
    return [
        Proposal(name, value, None, "online", True, reason)
        for name, (value, reason) in sure.items()
        if name not in taken and not current.get(name)
    ]


def _matches(found: dict[str, Found], source: str) -> list[Candidate]:
    """A source's candidates that match well enough to be used, best first."""
    return [c for c in found[source].candidates if c.score >= MATCH] if source in found else []


def _musicbrainz_ids(found: dict[str, Found], context: dict) -> dict[str, tuple[str, str]]:
    """The recording is sure when AcoustID recognised the sound clearly, or when AcoustID and
    MusicBrainz name the same recording; two sources agreeing on the title is not enough. Its
    artist IDs come with it; the album IDs only from MusicBrainz' release of that recording,
    and only when that release is the track's album (never a compilation)."""
    heard = next(iter(_matches(found, "acoustid")), None)
    recording = candidate_ids(heard).get("mb_trackid") if heard else None
    if not recording:
        return {}
    named = [c for c in _matches(found, "musicbrainz") if candidate_ids(c).get("mb_trackid")]
    same = next((c for c in named if candidate_ids(c)["mb_trackid"] == recording), None)
    clear = (heard.fingerprint_score or 0) >= SURE_FINGERPRINT
    if same is None and not clear:
        return {}
    if same is not None:
        reason = "AcoustID + MusicBrainz agree"
    else:
        reason = f"AcoustID recognised the sound ({heard.fingerprint_score:.0%})"
    ids = {"mb_trackid": recording}
    from_mb = candidate_ids(same) if same is not None else {}
    if artists := from_mb.get("mb_artistid") or candidate_ids(heard).get("mb_artistid"):
        ids["mb_artistid"] = artists
    if from_mb.get("mb_albumid") and _same_text(same.values.get("album"), context.get("album")):
        ids["mb_albumid"] = from_mb["mb_albumid"]
        if from_mb.get("mb_albumartistid"):
            ids["mb_albumartistid"] = from_mb["mb_albumartistid"]
    return {name: (value, reason) for name, value in ids.items()}


def _discogs_ids(found: dict[str, Found], context: dict) -> dict[str, tuple[str, str]]:
    """Discogs is the only source with Discogs IDs, so "two sources agree" means: the
    MusicBrainz release links to this Discogs release, or the Discogs release is the track's
    album and its label or catalog number agrees too. Of several pressings (vinyl, digital,
    reissue) the one matching label and catalog number wins; if none clearly does, no ID."""
    releases: dict[str, Candidate] = {}  # Discogs release ID -> its best candidate
    for candidate in _matches(found, "discogs"):
        if release := candidate_ids(candidate).get("discogs_releaseid"):
            releases.setdefault(release, candidate)
    if not releases:
        return {}
    linked = {candidate_ids(c).get("discogs_releaseid") for c in _matches(found, "musicbrainz")}
    if len(hits := [r for r in releases if r in linked]) == 1:
        chosen, reason = releases[hits[0]], "MusicBrainz links to this Discogs release"
    else:
        if len(releases) == 1:
            chosen = next(iter(releases.values()))
        else:
            fitting = [
                c
                for c in releases.values()
                if _same_text(c.values.get("label"), context.get("label"))
                and _same_catno(c.values.get("catalognumber"), context.get("catalognumber"))
            ]
            if len(fitting) != 1:
                return {}
            chosen = fitting[0]
        same_label = _same_text(chosen.values.get("label"), context.get("label"))
        same_catno = _same_catno(chosen.values.get("catalognumber"), context.get("catalognumber"))
        if not _same_text(chosen.values.get("album"), context.get("album")):
            return {}
        if not (same_label or same_catno):
            return {}
        reason = "Discogs: same album and " + ("label" if same_label else "catalog number")
    ids = {"discogs_releaseid": candidate_ids(chosen)["discogs_releaseid"]}
    track = candidate_ids(chosen).get("discogs_trackid")  # found in this release's tracklist
    if track and track.startswith(ids["discogs_releaseid"] + "-"):
        ids["discogs_trackid"] = track
    # The artist IDs are only asked for Discogs' best match: take them from a release by the
    # same artist.
    artist = chosen.values.get("artist")
    for c in [chosen, *releases.values()]:
        artists = candidate_ids(c).get("discogs_artistid")
        if artists and c.values.get("artist") == artist:
            ids["discogs_artistid"] = artists
            break
    return {name: (value, reason) for name, value in ids.items()}


def _wrong_mbid(current: dict[str, str | None]) -> bool:
    """A MusicBrainz field holds something that isn't an MBID (e.g. a Discogs number)."""
    return any(
        not all(MBID_RE.match(part.strip()) for part in value.split(";") if part.strip())
        for value in (current.get(name) for name in MBID_FIELDS)
        if value
    )


def _same_text(a: str | None, b: str | None) -> bool:
    return bool(a and b) and normalized(a) == normalized(b)


def _same_catno(a: str | None, b: str | None) -> bool:
    """Catalog numbers alike without spaces, dashes and case: "CATCH 109" = "catch-109"."""

    def plain(text: str | None) -> str:
        return "".join(ch for ch in (text or "").lower() if ch.isalnum())

    return bool(plain(a)) and plain(a) == plain(b)


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
        value = genre_map.match(value)
    try:
        return writer.normalize(name, value)
    except ValueError:
        return None


def _same(name: str, value: str) -> str:
    """When two sources say the same: compare dates by year, text without case/spelling."""
    if name == "date":
        return value[:4]
    return normalized(value)


# --- Versions -------------------------------------------------------------------------------

LONGER = 10  # seconds: a version this much shorter is another edit (as in _length_match)
_MIX = re.compile(r"[(\[]([^()\[\]]+)[)\]]\s*$")  # "Take Me to Church (Original Mix)"


@dataclass
class LongerVersion:
    """The file is longer than the only version some sources have: streaming stores often
    sell the 4:09 radio edit of a 5:26 club mix. ``confirmed`` names the sources that list a
    version of this length (DJ stores, Discogs tracklists)."""

    length: float  # the file's, seconds
    shorter: list[str]  # sources with only shorter versions (labels)
    shorter_length: float  # the longest of those versions
    confirmed: list[str] = field(default_factory=list)  # sources listing this length
    mix: str = ""  # the confirming version's mix name ("Original Mix"), if it has one

    @property
    def text(self) -> str:
        has = "has" if len(self.shorter) == 1 else "have"
        text = f"{_and(self.shorter)} only {has} a {_mmss(self.shorter_length)} version. "
        if not self.confirmed:
            return text + (
                f"This file is {_mmss(self.length)}: maybe an extended or club mix. "
                "No source lists this length yet."
            )
        lists = "lists" if len(self.confirmed) == 1 else "list"
        mix = f" ({self.mix})" if self.mix else ""
        return text + f"{_and(self.confirmed)} {lists} this {_mmss(self.length)} version{mix}."


def longer_version(found: list[Found]) -> LongerVersion | None:
    """Is the file a longer version than some sources know? Only versions of the same track
    count (same title apart from the version words, same artist), not other remixes."""
    result: LongerVersion | None = None
    confirming: list[tuple[str, Candidate]] = []
    for f in found:
        asked = f.asked
        if f.error or not asked or not asked.duration:
            continue
        versions = [c for c in f.candidates if c.duration and _same_track(c, asked)]
        same = [c for c in versions if abs(c.duration - asked.duration) <= 3]
        if same:
            confirming.append((f.label, same[0]))
            continue
        # Only shorter versions: a source that also has a longer one doesn't count (the file
        # may be an edit between the two).
        if versions and all(asked.duration - c.duration > LONGER for c in versions):
            result = result or LongerVersion(asked.duration, [], 0.0)
            result.shorter.append(f.label)
            result.shorter_length = max([result.shorter_length] + [c.duration for c in versions])
    if result:
        result.confirmed = [label for label, _ in confirming]
        mixes = [m.group(1) for _, c in confirming if (m := _MIX.search(c.values["title"]))]
        mixes = [m for m in mixes if not m.lower().startswith(("feat", "ft.", "with "))]
        result.mix = mixes[0] if mixes else ""
    return result


def _same_track(candidate: Candidate, asked: Query) -> bool:
    title = candidate.values.get("title")
    return (
        bool(title and asked.title)
        and _base(normalized(title)) == _base(normalized(asked.title))
        and _artist_match(asked.artist, candidate.values.get("artist")) >= 0.9
    )


def _and(names: list[str]) -> str:
    """["Deezer", "iTunes", "MusicBrainz"] -> "Deezer, iTunes and MusicBrainz"."""
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"
