"""Database tables.

Any change here needs a migration: ``alembic revision --autogenerate -m "what changed"``
(see docs/development.md).
"""

from datetime import UTC, datetime

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
    has_cover: bool = False

    error: str | None = None  # set when the file could not be read
    scanned_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
