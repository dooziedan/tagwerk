"""Finding tracks: the filters behind the track list, the dashboard links and the API.

The dashboard counts tracks with the same conditions the track list uses to show them, so
clicking a number always shows exactly those tracks.
"""

from dataclasses import asdict, dataclass, fields, replace
from urllib.parse import urlencode

from sqlalchemy import ColumnElement, Integer, and_, cast, distinct, exists, func, not_, or_
from sqlmodel import Session, col, select

from app.audio_analysis import ANALYSIS_VERSION
from app.keys import display
from app.models import (
    ChangeEntry,
    ChangeSet,
    DuplicateTrack,
    FinalTrack,
    LibraryAnalysis,
    RawTag,
    Track,
)
from app.tags import LOSSLESS_FORMATS

PER_PAGE = 50

# An album belongs to its album artist; files without one fall back to the track artist.
# That's also how Navidrome groups its artist list.
ALBUM_ARTIST = func.coalesce(func.nullif(Track.albumartist, ""), Track.artist)

# Lossy files below this are flagged (a DJ plays 320 kbps or lossless). 2% tolerance, because
# some encoders report a constant 320 kbps file as e.g. 319 kbps.
LOW_BITRATE_KBPS = 320
_LOW_BITRATE_LIMIT = LOW_BITRATE_KBPS * 1000 * 0.98

# Values that mean "unknown" for numeric fields like BPM (MusicBrainz Picard writes "0").
ZERO_VALUES = ("0", "0.0", "0.00", "00")


def is_missing(column) -> ColumnElement[bool]:
    return or_(column.is_(None), column == "")


MISSING: dict[str, ColumnElement[bool]] = {
    "Title": is_missing(Track.title),
    "Artist": is_missing(Track.artist),
    "Album": is_missing(Track.album),
    "Album artist": is_missing(Track.albumartist),
    "Track number": Track.tracknumber.is_(None),
    "Year": Track.year.is_(None),
    "Genre": is_missing(Track.genre),
    "Cover art": col(Track.has_cover).is_(False),
    "Lyrics": and_(col(Track.has_lyrics).is_(False), col(Track.has_lrc).is_(False)),
    "ReplayGain": Track.replaygain_track_gain.is_(None),
    "BPM": Track.bpm.is_(None),
    "Key": Track.key_camelot.is_(None),
    "Label": is_missing(Track.label),
    "Comment": is_missing(Track.comment),
    "MusicBrainz IDs": or_(is_missing(Track.mb_albumid), col(Track.mbid_invalid).is_(True)),
}

_READABLE = Track.error.is_(None)
_LOSSLESS = col(Track.format).in_(LOSSLESS_FORMATS)
_BPM_FIELD = or_(
    and_(RawTag.system == "id3", RawTag.name == "TBPM"),
    and_(RawTag.system == "vorbis", func.lower(RawTag.name).in_(("bpm", "tempo"))),
    and_(RawTag.system == "mp4", RawTag.name == "tmpo"),
)

# Final tracks (app/final.py): marked as done; "changed" when another program wrote to the file.
IS_FINAL = exists().where(FinalTrack.track_id == Track.id)
# Set-ready: everything a DJ needs is tagged. Also what the Final check asks for.
SET_READY = and_(
    _READABLE,
    not_(is_missing(Track.title)),
    not_(is_missing(Track.artist)),
    not_(is_missing(Track.genre)),
    Track.bpm.is_not(None),
    Track.key_camelot.is_not(None),
    col(Track.has_cover).is_(True),
)
CHANGED_OUTSIDE = exists().where(FinalTrack.track_id == Track.id, FinalTrack.mtime != Track.mtime)

# BPM and key from the audio (app/analysis.py): only sure decisions are compared with tags,
# and never for final tracks: the owner checked those, their tags stand.
_AUDIO = LibraryAnalysis
_SAME_TEMPO = 0.015  # tags hold rounded BPMs (87.5 -> 88)


def _tempo_near(a, b) -> ColumnElement[bool]:
    return func.abs(a - b) <= _SAME_TEMPO * b


_BPM_COMPARED = and_(
    _AUDIO.track_id == Track.id,
    col(_AUDIO.decided_bpm_sure).is_(True),
    _AUDIO.decided_bpm.is_not(None),
    Track.bpm > 0,
)
_BPM_OCTAVE = or_(
    _tempo_near(Track.bpm * 2, _AUDIO.decided_bpm), _tempo_near(Track.bpm, _AUDIO.decided_bpm * 2)
)


def by_tagwerk(*kinds: str, tags_only: bool = False) -> ColumnElement[bool]:
    """Tracks with a change of these kinds (app.models.ChangeSet.kind) that is still in place:
    written without error and not undone (Statistics: "Tagwerk's work"). ``tags_only``: only
    changes that wrote tags (an import without tag changes only moved the file)."""
    conditions = [
        ChangeEntry.track_id == Track.id,
        ChangeEntry.error.is_(None),
        col(ChangeEntry.undone).is_(False),
        ChangeSet.id == ChangeEntry.changeset_id,
        ChangeSet.undone_at.is_(None),
        col(ChangeSet.kind).in_(kinds),
    ]
    if tags_only:
        conditions.append(ChangeEntry.changes != "{}")
    return exists().where(*conditions)


AUDIO_FLAGS = ("audio_bpm_octave", "audio_bpm_differs", "audio_key_differs", "not_analysed")

# Named filters for things that aren't a single tag, with the label shown on the page.
FLAGS: dict[str, tuple[str, ColumnElement[bool]]] = {
    "untagged": ("No tags at all", and_(_READABLE, Track.tag_format.is_(None))),
    "unreadable": ("Could not be read", Track.error.is_not(None)),
    "invalid_mbid": ("Other IDs in MusicBrainz fields", col(Track.mbid_invalid).is_(True)),
    "lossless": ("Lossless (FLAC, WAV, AIFF)", _LOSSLESS),
    "low_bitrate": (
        f"Lossy below {LOW_BITRATE_KBPS} kbps",
        and_(not_(_LOSSLESS), Track.bitrate.is_not(None), Track.bitrate < _LOW_BITRATE_LIMIT),
    ),
    "bpm_zero": (
        "BPM stored as 0",
        exists().where(RawTag.track_id == Track.id, _BPM_FIELD, col(RawTag.value).in_(ZERO_VALUES)),
    ),
    "key_unrecognized": (
        "Key not recognized",
        and_(not_(is_missing(Track.key)), Track.key_camelot.is_(None)),
    ),
    "bpm_and_key": (
        "BPM and key set",
        and_(Track.bpm.is_not(None), Track.key_camelot.is_not(None)),
    ),
    "audio_bpm_octave": (
        "BPM probably half or double time",
        and_(not_(IS_FINAL), exists().where(_BPM_COMPARED, _BPM_OCTAVE)),
    ),
    "audio_bpm_differs": (
        "BPM differs from the audio",
        and_(
            not_(IS_FINAL),
            exists().where(
                _BPM_COMPARED, not_(_tempo_near(Track.bpm, _AUDIO.decided_bpm)), not_(_BPM_OCTAVE)
            ),
        ),
    ),
    "audio_key_differs": (
        "Key differs from the audio",
        and_(
            not_(IS_FINAL),
            exists().where(
                _AUDIO.track_id == Track.id,
                col(_AUDIO.decided_key_sure).is_(True),
                _AUDIO.decided_key.is_not(None),
                Track.key_camelot.is_not(None),
                Track.key_camelot != _AUDIO.decided_key,
            ),
        ),
    ),
    "not_analysed": (
        "BPM and key not analysed yet",
        and_(
            _READABLE,
            not_(exists().where(_AUDIO.track_id == Track.id, _AUDIO.version == ANALYSIS_VERSION)),
        ),
    ),
    "set_ready": ("Set-ready (title, artist, genre, BPM, key, cover)", SET_READY),
    "not_set_ready": ("Not set-ready yet", and_(_READABLE, not_(SET_READY))),
    "final": ("Final", IS_FINAL),
    "tagwerk_tags": ("Tags written by Tagwerk", by_tagwerk("edit", "import", tags_only=True)),
    "tagwerk_edited": (
        "Tags corrected in the library by Tagwerk",
        and_(by_tagwerk("edit"), not_(by_tagwerk("import"))),
    ),
    "tagwerk_imported": ("Imported through the inbox", by_tagwerk("import")),
    "tagwerk_converted": ("Converted to AIFF by Tagwerk", by_tagwerk("convert")),
    "final_changed": ("Final, changed outside Tagwerk", CHANGED_OUTSIDE),
    # Worked out after scans and writes (app/duplicates.py, ADR 0022)
    "duplicate": (
        "In the library more than once",
        exists().where(DuplicateTrack.track_id == Track.id),
    ),
}


def added_period(chars: int):
    """The year ("2026", chars=4) or month ("2026-10", chars=7) a track joined the library."""
    return func.strftime("%Y" if chars == 4 else "%Y-%m", Track.added_at)


def genre_is(genre: str) -> ColumnElement[bool]:
    """Matches one genre inside a multi-genre tag like "House; Tech House" or "House;Techno".

    Same rule as the dashboard's genre count: split on ";" and ignore surrounding spaces.
    """
    normalized = func.replace(func.replace(Track.genre, "; ", ";"), " ;", ";")
    padded = func.coalesce(";" + normalized + ";", "")
    return padded.contains(f";{genre.strip()};", autoescape=True)


@dataclass
class TrackFilter:
    """Everything the track list can be filtered by. Empty fields mean "no filter"."""

    q: str = ""  # search in title, artist, album, album artist, label, path
    format: str = ""
    missing: str = ""  # a key of MISSING
    flag: str = ""  # a key of FLAGS
    key: str = ""  # Camelot code, e.g. "8A"
    bpm_min: float | None = None
    bpm_max: float | None = None
    genre: str = ""
    decade: int | None = None  # e.g. 1990
    folder: str = ""  # path prefix, e.g. "House/Album"
    albumartist: str = ""  # album artist (or artist when none), exact
    album: str = ""  # exact
    field: str = ""  # raw tag field "system:name", e.g. "id3:TXXX:fBPM"
    value: str | None = None  # with field: only this exact value
    year: int | None = None  # release year, exact
    added: str = ""  # when it joined the library: "2026" or "2026-10"
    length_min: float | None = None  # minutes
    length_max: float | None = None  # minutes (below)
    label: str = ""  # record label, exact

    def conditions(self) -> list[ColumnElement[bool]]:
        c: list[ColumnElement[bool]] = []
        if self.q:
            c.append(
                or_(
                    *(
                        column.contains(self.q, autoescape=True)
                        for column in (
                            Track.title,
                            Track.artist,
                            Track.album,
                            Track.albumartist,
                            Track.label,
                            Track.path,
                        )
                    )
                )
            )
        if self.format:
            c.append(Track.format == self.format.lower())
        if self.missing in MISSING:
            c.extend((_READABLE, MISSING[self.missing]))
        if self.flag in FLAGS:
            c.append(FLAGS[self.flag][1])
        if self.key:
            c.append(Track.key_camelot == self.key.upper())
        if self.bpm_min is not None:
            c.append(Track.bpm >= self.bpm_min)
        if self.bpm_max is not None:
            c.append(Track.bpm < self.bpm_max)
        if self.genre:
            c.append(genre_is(self.genre))
        if self.decade is not None:
            c.append(and_(Track.year >= self.decade, Track.year <= self.decade + 9))
        if self.folder:
            c.append(Track.path.startswith(self.folder.rstrip("/") + "/", autoescape=True))
        if self.albumartist:
            c.append(ALBUM_ARTIST == self.albumartist)
        if self.album:
            c.append(Track.album == self.album)
        if self.year is not None:
            c.append(Track.year == self.year)
        if len(self.added) in (4, 7):
            c.append(added_period(len(self.added)) == self.added)
        if self.length_min is not None:
            c.append(Track.duration >= self.length_min * 60)
        if self.length_max is not None:
            c.append(Track.duration < self.length_max * 60)
        if self.label:
            c.append(Track.label == self.label)
        if self.field and ":" in self.field:
            system, name = self.field.split(":", 1)
            raw = [RawTag.track_id == Track.id, RawTag.system == system, RawTag.name == name]
            if self.value is not None:
                raw.append(RawTag.value == self.value)
            c.append(exists().where(*raw))
        return c

    def params(self, **changes) -> dict[str, str]:
        """The filter as URL query parameters (only the ones that are set)."""
        data = asdict(replace(self, **changes))
        return {k: str(v) for k, v in data.items() if v not in ("", None)}

    def url(self, path: str = "/tracks", **changes) -> str:
        query = urlencode(self.params(**changes))
        return f"{path}?{query}" if query else path

    def chips(self, notation: str) -> list[tuple[str, str]]:
        """Active filters as (label, URL without this filter), for the removable filter chips."""
        labels = {
            "q": lambda v: f"Search: {v}",
            "format": lambda v: f"Format: {v.upper()}",
            "missing": lambda v: f"Missing: {v}",
            "flag": lambda v: FLAGS[v][0] if v in FLAGS else v,
            "key": lambda v: f"Key: {display(v.upper(), notation) or v}",
            "bpm_min": lambda v: f"BPM ≥ {v:g}",
            "bpm_max": lambda v: f"BPM < {v:g}",
            "genre": lambda v: f"Genre: {v}",
            "decade": lambda v: f"{v}s",
            "folder": lambda v: f"Folder: {v}",
            "albumartist": lambda v: f"Artist: {v}",
            "album": lambda v: f"Album: {v}",
            "field": lambda v: f"Field: {v.split(':', 1)[-1]}",
            "value": lambda v: f"Value: {v if v else '(empty)'}",
            "year": lambda v: f"Released {v}",
            "added": lambda v: f"Added {v}",
            "length_min": lambda v: f"≥ {v:g} min",
            "length_max": lambda v: f"< {v:g} min",
            "label": lambda v: f"Label: {v}",
        }
        chips = []
        for f in fields(self):
            v = getattr(self, f.name)
            if v in ("", None):
                continue
            reset = {f.name: None if f.name == "value" else f.default}
            if f.name == "field":
                reset["value"] = None  # removing the field also removes its value
            chips.append((labels[f.name](v), self.url(**reset)))
        return chips


# Sort options: name -> (label, columns). NULL values always go last.
_KEY_NUMBER = cast(func.rtrim(Track.key_camelot, "AB"), Integer)
SORTS = {
    "artist": (
        "Artist",
        [ALBUM_ARTIST, Track.album, Track.discnumber, Track.tracknumber, Track.title],
    ),
    "title": ("Title", [Track.title]),
    "album": ("Album", [Track.album, Track.discnumber, Track.tracknumber]),
    "bpm": ("BPM", [Track.bpm]),
    "key": ("Key", [_KEY_NUMBER, Track.key_camelot]),
    "year": ("Year", [Track.year]),
    "genre": ("Genre", [Track.genre]),
    "label": ("Label", [Track.label]),
    "format": ("Format", [Track.format]),
    "bitrate": ("Bitrate", [Track.bitrate]),
    "duration": ("Length", [Track.duration]),
    "path": ("File", [Track.path]),
}


@dataclass
class TrackPage:
    tracks: list[Track]
    total: int
    page: int
    pages: int


def find_tracks(
    session: Session, f: TrackFilter, sort: str = "artist", desc: bool = False, page: int = 1
) -> TrackPage:
    conditions = f.conditions()
    total = session.exec(select(func.count(Track.id)).where(*conditions)).one()
    pages = max(1, -(-total // PER_PAGE))
    page = min(max(1, page), pages)
    columns = SORTS.get(sort, SORTS["artist"])[1]
    order = []
    for column in columns:
        order += [column.is_(None), column.desc() if desc else column]
    tracks = session.exec(
        select(Track)
        .where(*conditions)
        .order_by(*order, Track.path)
        .offset((page - 1) * PER_PAGE)
        .limit(PER_PAGE)
    ).all()
    return TrackPage(list(tracks), total, page, pages)


def count(session: Session, *conditions: ColumnElement[bool]) -> int:
    return session.exec(select(func.count(Track.id)).where(*conditions)).one()


@dataclass
class ArtistRow:
    name: str
    tracks: int
    albums: int


def list_artists(session: Session, q: str = "") -> list[ArtistRow]:
    query = (
        select(
            ALBUM_ARTIST,
            func.count(Track.id),
            func.count(distinct(func.nullif(Track.album, ""))),
        )
        .where(ALBUM_ARTIST.is_not(None), ALBUM_ARTIST != "")
        .group_by(ALBUM_ARTIST)
        .order_by(func.lower(ALBUM_ARTIST))
    )
    if q:
        query = query.where(ALBUM_ARTIST.contains(q, autoescape=True))
    return [ArtistRow(*row) for row in session.exec(query)]


@dataclass
class AlbumRow:
    artist: str | None
    album: str
    year: int | None
    tracks: int
    formats: str  # e.g. "flac, mp3"
    has_cover: bool


def list_albums(session: Session, q: str = "", artist: str = "") -> list[AlbumRow]:
    query = (
        select(
            ALBUM_ARTIST,
            Track.album,
            func.max(Track.year),
            func.count(Track.id),
            func.group_concat(distinct(Track.format)),
            func.max(Track.has_cover),
        )
        .where(not_(is_missing(Track.album)))
        .group_by(ALBUM_ARTIST, Track.album)
        .order_by(func.lower(ALBUM_ARTIST), func.lower(Track.album))
    )
    if q:
        query = query.where(
            or_(Track.album.contains(q, autoescape=True), ALBUM_ARTIST.contains(q, autoescape=True))
        )
    if artist:
        query = query.where(ALBUM_ARTIST == artist)
    return [
        AlbumRow(a, album, year, n, (formats or "").replace(",", ", "), bool(cover))
        for a, album, year, n, formats, cover in session.exec(query)
    ]
