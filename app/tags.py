"""Read tags from audio files into one common format.

Every container format stores tags differently:

| Format     | Tag system                        |
|------------|-----------------------------------|
| MP3        | ID3                               |
| WAV, AIFF  | ID3 (WAV may only have RIFF INFO) |
| FLAC       | Vorbis comments                   |
| M4A        | MP4 atoms                         |

``read_file`` hides those differences and returns a ``FileInfo`` whose fields match the
columns of ``app.models.Track``. The field names follow MusicBrainz Picard's conventions,
because that's what most taggers (and Navidrome) understand.
"""

import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

import mutagen
from mutagen._vorbis import VCommentDict
from mutagen.flac import FLAC
from mutagen.id3 import ID3
from mutagen.mp4 import MP4Tags

# File extension -> format name used throughout the app.
FORMATS = {
    ".mp3": "mp3",
    ".flac": "flac",
    ".wav": "wav",
    ".aif": "aiff",
    ".aiff": "aiff",
    ".m4a": "m4a",
}

MBID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
MBID_FIELDS = ("mb_trackid", "mb_albumid", "mb_artistid", "mb_albumartistid")


class UnsupportedFileError(Exception):
    """The file isn't an audio format Tagwerk can read."""


@dataclass
class FileInfo:
    format: str
    duration: float | None = None
    bitrate: int | None = None
    sample_rate: int | None = None
    bits_per_sample: int | None = None
    channels: int | None = None

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
    mb_trackid: str | None = None
    mb_albumid: str | None = None
    mb_artistid: str | None = None
    mb_albumartistid: str | None = None
    mbid_invalid: bool = False
    has_cover: bool = False

    # Raw "track" and "disc" values like "3/12", split into number and total by _finish().
    _track: str | None = field(default=None, repr=False)
    _disc: str | None = field(default=None, repr=False)

    def as_columns(self) -> dict:
        """The values to store on a ``Track`` row."""
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}


def read_file(path: Path) -> FileInfo:
    """Read audio properties and tags. Raises ``mutagen.MutagenError`` for broken files."""
    fmt = FORMATS.get(path.suffix.lower())
    if fmt is None:
        raise UnsupportedFileError(path.suffix)

    audio = mutagen.File(path)
    if audio is None:
        raise UnsupportedFileError(f"not a recognized {fmt} file")

    info = FileInfo(
        format=fmt,
        duration=getattr(audio.info, "length", None),
        bitrate=getattr(audio.info, "bitrate", None) or None,
        sample_rate=getattr(audio.info, "sample_rate", None),
        bits_per_sample=getattr(audio.info, "bits_per_sample", None),
        channels=getattr(audio.info, "channels", None),
    )

    tags = audio.tags
    if isinstance(tags, ID3):
        _read_id3(tags, info)
    elif isinstance(tags, VCommentDict):
        _read_vorbis(tags, info)
        if isinstance(audio, FLAC) and audio.pictures:
            info.has_cover = True
    elif isinstance(tags, MP4Tags):
        _read_mp4(tags, info)
    elif fmt == "wav":
        # No ID3 chunk: fall back to the older RIFF INFO tags (Navidrome reads those too).
        _read_riff_info(path, info)

    _finish(info)
    return info


# --- ID3 (MP3, WAV, AIFF) ---------------------------------------------------------------


def _read_id3(tags: ID3, info: FileInfo) -> None:
    info.tag_format = "id3"
    info.title = _id3_text(tags, "TIT2")
    info.artist = _id3_text(tags, "TPE1")
    info.album = _id3_text(tags, "TALB")
    info.albumartist = _id3_text(tags, "TPE2")
    info._track = _id3_text(tags, "TRCK")
    info._disc = _id3_text(tags, "TPOS")
    info.date = _id3_text(tags, "TDRC") or _id3_text(tags, "TDOR")
    if "TCON" in tags:
        info.genre = _join(tags["TCON"].genres)  # .genres resolves numeric codes like "(17)"
    info.mb_albumid = _id3_text(tags, "TXXX:MusicBrainz Album Id")
    info.mb_artistid = _id3_text(tags, "TXXX:MusicBrainz Artist Id")
    info.mb_albumartistid = _id3_text(tags, "TXXX:MusicBrainz Album Artist Id")
    ufid = tags.get("UFID:http://musicbrainz.org")
    if ufid is not None:
        info.mb_trackid = ufid.data.decode("ascii", "replace") or None
    info.has_cover = bool(tags.getall("APIC"))


def _id3_text(tags: ID3, key: str) -> str | None:
    frame = tags.get(key)
    return _join(str(t) for t in frame.text) if frame is not None else None


# --- Vorbis comments (FLAC) ---------------------------------------------------------------


def _read_vorbis(tags: VCommentDict, info: FileInfo) -> None:
    def get(*keys: str) -> str | None:
        for key in keys:
            if key in tags:
                return _join(tags[key])
        return None

    info.tag_format = "vorbis"
    info.title = get("title")
    info.artist = get("artist")
    info.album = get("album")
    info.albumartist = get("albumartist", "album artist", "album_artist")
    info._track = get("tracknumber", "track")
    info.tracktotal = _to_int(get("tracktotal", "totaltracks"))
    info._disc = get("discnumber", "disc")
    info.disctotal = _to_int(get("disctotal", "totaldiscs"))
    info.date = get("date", "year", "originaldate")
    info.genre = get("genre")
    info.mb_trackid = get("musicbrainz_trackid")
    info.mb_albumid = get("musicbrainz_albumid")
    info.mb_artistid = get("musicbrainz_artistid")
    info.mb_albumartistid = get("musicbrainz_albumartistid")
    info.has_cover = "metadata_block_picture" in tags


# --- MP4 atoms (M4A) ----------------------------------------------------------------------

_MP4_FREEFORM = "----:com.apple.iTunes:"


def _read_mp4(tags: MP4Tags, info: FileInfo) -> None:
    def text(key: str) -> str | None:
        return _join(str(v) for v in tags[key]) if key in tags else None

    def freeform(name: str) -> str | None:
        values = tags.get(_MP4_FREEFORM + name)
        return _join(bytes(v).decode("utf-8", "replace") for v in values) if values else None

    info.tag_format = "mp4"
    info.title = text("\xa9nam")
    info.artist = text("\xa9ART")
    info.album = text("\xa9alb")
    info.albumartist = text("aART")
    info.date = text("\xa9day")
    info.genre = text("\xa9gen")
    if tags.get("trkn"):
        info.tracknumber, info.tracktotal = (n or None for n in tags["trkn"][0])
    if tags.get("disk"):
        info.discnumber, info.disctotal = (n or None for n in tags["disk"][0])
    info.mb_trackid = freeform("MusicBrainz Track Id")
    info.mb_albumid = freeform("MusicBrainz Album Id")
    info.mb_artistid = freeform("MusicBrainz Artist Id")
    info.mb_albumartistid = freeform("MusicBrainz Album Artist Id")
    info.has_cover = bool(tags.get("covr"))


# --- RIFF INFO (WAV without ID3) ----------------------------------------------------------

_RIFF_INFO_FIELDS = {
    b"INAM": "title",
    b"IART": "artist",
    b"IPRD": "album",
    b"ICRD": "date",
    b"IGNR": "genre",
    b"ITRK": "_track",
    b"IPRT": "_track",
}


def _read_riff_info(path: Path, info: FileInfo) -> None:
    values = _riff_info_chunks(path)
    found = False
    for chunk_id, attr in _RIFF_INFO_FIELDS.items():
        if values.get(chunk_id) and getattr(info, attr) is None:
            setattr(info, attr, values[chunk_id])
            found = True
    if found:
        info.tag_format = "riff-info"


def _riff_info_chunks(path: Path) -> dict[bytes, str]:
    """Return the sub-chunks of a WAV file's ``LIST/INFO`` chunk, e.g. {b"INAM": "Title"}."""
    result: dict[bytes, str] = {}
    with path.open("rb") as f:
        header = f.read(12)
        if len(header) < 12 or header[:4] != b"RIFF" or header[8:12] != b"WAVE":
            return result
        while chunk := f.read(8):
            if len(chunk) < 8:
                break
            chunk_id, size = struct.unpack("<4sI", chunk)
            if chunk_id == b"LIST" and f.read(4) == b"INFO":
                data = f.read(size - 4)
                pos = 0
                while pos + 8 <= len(data):
                    sub_id, sub_size = struct.unpack("<4sI", data[pos : pos + 8])
                    raw = data[pos + 8 : pos + 8 + sub_size].split(b"\0", 1)[0]
                    result[sub_id] = _decode_riff(raw).strip()
                    pos += 8 + sub_size + (sub_size & 1)
                return result
            f.seek(size + (size & 1) - (4 if chunk_id == b"LIST" else 0), 1)
    return result


def _decode_riff(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


# --- shared helpers -----------------------------------------------------------------------


def _finish(info: FileInfo) -> None:
    """Split "3/12" style numbers, extract the year and check MusicBrainz IDs."""
    if info._track:
        number, total = _split_number(info._track)
        info.tracknumber = info.tracknumber or number
        info.tracktotal = info.tracktotal or total
    if info._disc:
        number, total = _split_number(info._disc)
        info.discnumber = info.discnumber or number
        info.disctotal = info.disctotal or total
    if info.date and (match := re.match(r"\d{4}", info.date)):
        info.year = int(match.group())
    info.mbid_invalid = any(
        value and not all(MBID_RE.match(part) for part in value.split("; "))
        for value in (getattr(info, name) for name in MBID_FIELDS)
    )


def _split_number(value: str) -> tuple[int | None, int | None]:
    number, _, total = value.partition("/")
    return _to_int(number), _to_int(total)


def _to_int(value: str | None) -> int | None:
    try:
        return int(value.strip()) if value else None
    except ValueError:
        return None


def _join(values) -> str | None:
    """Join multiple values ("Artist A", "Artist B") with "; ", dropping empties and dupes."""
    unique = list(dict.fromkeys(v.strip() for v in values if v and v.strip()))
    return "; ".join(unique) or None
