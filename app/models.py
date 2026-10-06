"""Database tables.

Any change here needs a migration: ``alembic revision --autogenerate -m "what changed"``
(see docs/development.md).
"""

from datetime import UTC, datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class Track(SQLModel, table=True):
    """One audio file in the music library, with the tags as they are on disk."""

    id: int | None = Field(default=None, primary_key=True)

    # File
    path: str = Field(unique=True, index=True)  # relative to MUSIC_DIR
    format: str = Field(index=True)  # mp3, flac, wav, aiff, m4a
    size: int  # bytes
    mtime: float  # file modification time, used to skip unchanged files
    duration: float | None = None  # seconds
    bitrate: int | None = None  # bits per second
    sample_rate: int | None = None
    bits_per_sample: int | None = None
    channels: int | None = None

    # Tags (normalized across formats, see app/tags.py)
    tag_format: str | None = None  # id3, vorbis, mp4, riff-info; None = no tags at all
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    albumartist: str | None = None
    tracknumber: int | None = None
    tracktotal: int | None = None
    discnumber: int | None = None
    disctotal: int | None = None
    date: str | None = None  # as written in the file, e.g. "2019" or "2019-04-26"
    year: int | None = Field(default=None, index=True)
    genre: str | None = None  # multiple genres joined with "; "
    mb_trackid: str | None = None  # MusicBrainz recording ID
    mb_albumid: str | None = None  # MusicBrainz release ID
    mb_artistid: str | None = None
    mb_albumartistid: str | None = None
    mbid_invalid: bool = False  # a MusicBrainz field holds something that isn't an MBID
    discogs_releaseid: str | None = None  # Discogs numbers (app/ids.py)
    discogs_artistid: str | None = None
    has_cover: bool = False
    has_lyrics: bool = False  # embedded lyrics
    has_lrc: bool = False  # a .lrc lyrics file with the same name sits next to the track

    # DJ fields
    bpm: float | None = None
    key: str | None = None  # as written in the file
    key_camelot: str | None = Field(default=None, index=True)  # parsed, e.g. "8A"
    comment: str | None = None
    label: str | None = None
    catalognumber: str | None = None
    replaygain_track_gain: float | None = None  # dB

    error: str | None = None  # set when the file could not be read
    # Which version of the tag reader produced this row. Rows from an older version are
    # re-read on the next scan, so new fields get filled in (see app.scanner.SCAN_VERSION).
    scan_version: int = 0
    scanned_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RawTag(SQLModel, table=True):
    """One tag field of one file, exactly as stored (see app/rawtags.py)."""

    id: int | None = Field(default=None, primary_key=True)
    track_id: int = Field(foreign_key="track.id", index=True, ondelete="CASCADE")
    system: str  # id3, vorbis, mp4, riff-info
    name: str = Field(index=True)  # e.g. "TBPM", "bpm", "TXXX:fBPM"
    value: str  # shortened; binary data is stored as "<binary data>"


class PendingChange(SQLModel, table=True):
    """An edit that is saved but not yet written to the file (see the Changes page)."""

    __table_args__ = (UniqueConstraint("track_id", "field"),)

    id: int | None = Field(default=None, primary_key=True)
    track_id: int = Field(foreign_key="track.id", index=True, ondelete="CASCADE")
    field: str  # a key of app.writer.EDITABLE
    old_value: str | None = None  # as shown when the change was made
    new_value: str | None = None  # None removes the field
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ChangeSet(SQLModel, table=True):
    """One "Apply": the changes written together, which can be undone together."""

    id: int | None = Field(default=None, primary_key=True)
    applied_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    tracks: int = 0
    written: int = 0
    failed: int = 0
    fields: str = ""  # e.g. "BPM, Key"
    undone_at: datetime | None = None
    kind: str = Field(default="edit", sa_column_kwargs={"server_default": "edit"})  # edit, import,
    # folder (a new genre folder, see app/folders.py)
    # JSON, what else undo has to know. Folder changes: {"folder", "created", "added_genre"}.
    details: str | None = None


class ChangeEntry(SQLModel, table=True):
    """One file in a ChangeSet: what changed, and the snapshot to undo it."""

    id: int | None = Field(default=None, primary_key=True)
    changeset_id: int = Field(foreign_key="changeset.id", index=True, ondelete="CASCADE")
    track_id: int | None = Field(default=None, foreign_key="track.id", ondelete="SET NULL")
    path: str
    changes: str  # JSON: {field: [old, new]}
    snapshot: str | None = None  # JSON from app.writer.write(); None if writing failed
    mtime_after: float | None = None  # file time right after writing, to detect later edits
    error: str | None = None
    undone: bool = False
    # Where the file was before it moved; undo moves it back. Imports: in the inbox (relative
    # to IMPORT_DIR). Folder changes: in the library (relative to MUSIC_DIR).
    moved_from: str | None = None


class AppSetting(SQLModel, table=True):
    """User preferences that apply to every device, e.g. the dashboard mode."""

    key: str = Field(primary_key=True)
    value: str  # JSON


class InboxTrack(SQLModel, table=True):
    """One audio file in the import inbox (IMPORT_DIR), not yet part of the library.

    Kept apart from ``Track`` on purpose: inbox tracks never show up in library counts,
    lists or statistics until they are moved into the library.
    """

    id: int | None = Field(default=None, primary_key=True)

    # File
    path: str = Field(unique=True, index=True)  # relative to IMPORT_DIR
    format: str
    size: int
    mtime: float
    duration: float | None = None
    bitrate: int | None = None
    sample_rate: int | None = None

    # Tags as found in the file (same meaning as on Track)
    tag_format: str | None = None
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    albumartist: str | None = None
    tracknumber: int | None = None
    tracktotal: int | None = None
    discnumber: int | None = None
    disctotal: int | None = None
    date: str | None = None
    year: int | None = None
    genre: str | None = None
    bpm: float | None = None
    key: str | None = None
    key_camelot: str | None = None
    comment: str | None = None
    label: str | None = None
    catalognumber: str | None = None
    mb_trackid: str | None = None
    has_cover: bool = False

    error: str | None = None  # set when the file could not be read
    found_at: datetime = Field(default_factory=lambda: datetime.now(UTC))  # first seen
    scanned_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class InboxValue(SQLModel, table=True):
    """A value the owner set for an inbox track on its review page (overrides the suggestion).

    Not written to the file until the track is imported. ``value`` None removes the field.
    """

    __table_args__ = (UniqueConstraint("track_id", "field"),)

    id: int | None = Field(default=None, primary_key=True)
    track_id: int = Field(foreign_key="inboxtrack.id", ondelete="CASCADE", index=True)
    field: str  # a key of app.writer.EDITABLE
    value: str | None = None


class FinalTrack(SQLModel, table=True):
    """A library track the owner marked as final: done, and locked against edits.

    Only stored here: no tag is written for it. ``mtime`` is the file's time when it was marked,
    so a later change by another program shows up as "changed outside Tagwerk".
    """

    track_id: int = Field(foreign_key="track.id", primary_key=True, ondelete="CASCADE")
    marked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    mtime: float
    # The filename before Tagwerk renamed it on marking (None: not renamed). Removing the mark
    # can go back to it.
    name_before: str | None = None


class _Lookup(SQLModel):
    """What one online source found for one track (app/identify.py).

    Lookups are slow and rate-limited, so results are kept: pages show them without asking
    again. ``query`` is what was asked (artist, title, length); when the owner changes the
    artist or title, the source is asked again.
    """

    source: str = Field(primary_key=True)  # musicbrainz, acoustid, discogs, itunes, deezer
    query: str  # JSON
    candidates: str = "[]"  # JSON: list of app.sources.base.Candidate as dicts, best first
    error: str | None = None  # the source couldn't be asked (network, key, rate limit)
    looked_up_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class OnlineLookup(_Lookup, table=True):
    """Online results for an inbox track."""

    track_id: int = Field(foreign_key="inboxtrack.id", primary_key=True, ondelete="CASCADE")


class LibraryLookup(_Lookup, table=True):
    """Online results for a library track ("Look up online"; results become pending changes)."""

    track_id: int = Field(foreign_key="track.id", primary_key=True, ondelete="CASCADE")


class _Analysis(SQLModel):
    """What the audio says about one track: BPM and key (app/analysis.py, ADR 0017).

    Analysing takes seconds per track, so results are kept. Tags don't change the sound, so a
    result stays valid when tags are written; it is redone when the method improves
    (``version``) or the file's length changes (another file under the same name).
    """

    bpm: float | None = None
    bpm_sure: bool = False
    key: str | None = None  # Camelot code, e.g. "7A"
    key_sure: bool = False
    # JSON: alternatives, plain-language notes and every method's answer
    detail: str = "{}"
    error: str | None = None  # the file couldn't be analysed (unreadable, silent, too short)
    version: int = 0  # app.audio_analysis.ANALYSIS_VERSION that produced this result
    duration: float | None = None  # the track's length when it was analysed
    analysed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class InboxAnalysis(_Analysis, table=True):
    """BPM and key from the audio of an inbox track (copied to the library on import)."""

    track_id: int = Field(foreign_key="inboxtrack.id", primary_key=True, ondelete="CASCADE")


class LibraryAnalysis(_Analysis, table=True):
    """BPM and key from the audio of a library track.

    ``decided_*``: the audio combined with the genre, filename and online BPMs (e.g. 174
    instead of the 87 the audio alone can't rule out). Worked out again when tags or online
    results change; the track list's "differs from the audio" filters use them.
    """

    track_id: int = Field(foreign_key="track.id", primary_key=True, ondelete="CASCADE")
    decided_bpm: float | None = None
    decided_bpm_sure: bool = False
    decided_key: str | None = None  # Camelot code
    decided_key_sure: bool = False
    decided_notes: str = "[]"  # JSON: why, in plain language
