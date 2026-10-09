"""Every tag field exactly as stored in a file, for the "Tag fields" page.

``app.tags`` reads the fields Tagwerk understands into one common format. This module
records *all* fields, including ones Tagwerk doesn't use (e.g. beaTunes or Serato data),
so you can see what your files really contain.
"""

from dataclasses import dataclass

from mutagen._vorbis import VCommentDict
from mutagen.flac import FLAC
from mutagen.id3 import ID3
from mutagen.mp4 import MP4FreeForm, MP4Tags

BINARY = "<binary data>"
UNREADABLE = "<unreadable>"
MAX_VALUE = 120  # characters stored per value; lyrics and long comments are shortened
MAX_NAME = 100  # characters per field name (a name is never data, but see _id3_name)

SYSTEMS = {"id3": "ID3", "vorbis": "Vorbis", "mp4": "MP4", "riff-info": "RIFF INFO"}


@dataclass(frozen=True)
class RawField:
    system: str  # id3, vorbis, mp4, riff-info
    name: str  # as the tag system names it, e.g. "TBPM", "bpm", "TXXX:fBPM"
    value: str


def collect(audio, riff_info: dict[bytes, str] | None = None) -> list[RawField]:
    """All tag fields of a file opened with mutagen (plus its RIFF INFO chunk, for WAV).

    Never raises: this is extra information, and an odd field must not make the whole file
    unreadable. A field whose value can't be turned into text is recorded as UNREADABLE.
    """
    try:
        return _collect(audio, riff_info)
    except Exception:  # pragma: no cover - safety net; individual fields are guarded below
        return []


def _collect(audio, riff_info: dict[bytes, str] | None) -> list[RawField]:
    fields: list[RawField] = []
    tags = audio.tags
    if isinstance(tags, ID3):
        fields += [
            RawField("id3", _id3_name(frame), _safe(_id3_value, frame)) for frame in tags.values()
        ]
    elif isinstance(tags, VCommentDict):
        for key in tags.keys():  # noqa: SIM118 (VCommentDict iterates differently)
            value = BINARY if key.lower() == "metadata_block_picture" else _safe(_join, tags[key])
            fields.append(RawField("vorbis", key, value))
    elif isinstance(tags, MP4Tags):
        fields += [
            RawField("mp4", key, _safe(_mp4_value, key, values)) for key, values in tags.items()
        ]
    if isinstance(audio, FLAC) and audio.pictures:
        fields.append(RawField("vorbis", "(FLAC picture block)", BINARY))
    for chunk_id, value in (riff_info or {}).items():
        fields.append(RawField("riff-info", chunk_id.decode("ascii", "replace"), _clean(value)))
    return fields


def _safe(func, *args) -> str:
    try:
        return func(*args)
    except Exception:
        return UNREADABLE


def _id3_name(frame) -> str:
    """The field's name, e.g. "TXXX:fBPM". mutagen's names for private frames (PRIV) and
    links (LINK) contain all their binary data: Traktor stores its whole analysis in
    PRIV:TRAKTOR4, so every file got its own field with a name of many kilobytes. Those are
    named by their owner only; any other name is cleaned and capped as a safety net."""
    if frame.FrameID == "PRIV":
        return f"PRIV:{_name_part(frame.owner)}"
    if frame.FrameID == "LINK":
        return f"LINK:{_name_part(frame.frameid)}:{_name_part(frame.url)}"
    return _name_part(frame.HashKey)


def _name_part(text: str) -> str:
    text = "".join(c if c.isprintable() else " " for c in str(text))
    text = " ".join(text.split())
    return text if len(text) <= MAX_NAME else text[: MAX_NAME - 1] + "…"


def _id3_value(frame) -> str:
    if frame.FrameID == "UFID":
        return _clean(frame.data.decode("ascii", "replace"))
    if hasattr(frame, "people"):  # TIPL / TMCL / IPLS: [["arranger", "Name"], ...]
        return _join(f"{role}: {name}" if name else role for role, name in frame.people)
    if hasattr(frame, "text"):
        text = frame.text
        return _join(text) if isinstance(text, list) else _clean(str(text))
    if hasattr(frame, "url"):
        return _clean(frame.url)
    if hasattr(frame, "data"):  # APIC, GEOB, PRIV, ...
        return BINARY
    return _clean(str(frame))


def _mp4_value(key: str, values) -> str:
    if key == "covr":
        return BINARY
    if not isinstance(values, list):  # single values, e.g. the compilation flag cpil = True
        values = [values]
    parts = []
    for value in values:
        if isinstance(value, MP4FreeForm):
            parts.append(bytes(value).decode("utf-8", "replace"))
        elif isinstance(value, tuple):  # trkn / disk: (3, 12)
            parts.append("/".join(str(n) for n in value))
        else:
            parts.append(str(value))
    return _join(parts)


def _join(values) -> str:
    return _clean("; ".join(str(v) for v in values))


def _clean(value: str) -> str:
    value = " ".join(value.replace("\x00", " ").split())
    return value if len(value) <= MAX_VALUE else value[: MAX_VALUE - 1] + "…"


# --- which raw fields feed which Tagwerk field ----------------------------------------------

_ID3 = {
    "TIT2": "Title", "TPE1": "Artist", "TALB": "Album", "TPE2": "Album artist",
    "TRCK": "Track number", "TPOS": "Disc number", "TDRC": "Date", "TDOR": "Date",
    "TCON": "Genre", "TBPM": "BPM", "TKEY": "Key", "TPUB": "Label", "COMM": "Comment",
    "USLT": "Lyrics", "SYLT": "Lyrics", "APIC": "Cover art",
    "UFID:http://musicbrainz.org": "MusicBrainz track ID",
    "TXXX:musicbrainz album id": "MusicBrainz album ID",
    "TXXX:musicbrainz artist id": "MusicBrainz artist ID",
    "TXXX:musicbrainz album artist id": "MusicBrainz album artist ID",
    "TXXX:discogs_release_id": "Discogs release ID", "TXXX:discogs_artist_id": "Discogs artist ID",
    "TXXX:catalognumber": "Catalog number", "TXXX:label": "Label",
    "TXXX:replaygain_track_gain": "ReplayGain track gain",
    "TXXX:replaygain_track_peak": "ReplayGain track peak",
    "TXXX:replaygain_album_gain": "ReplayGain album gain",
    "TXXX:replaygain_album_peak": "ReplayGain album peak",
}  # fmt: skip
_VORBIS = {
    "title": "Title", "artist": "Artist", "album": "Album", "albumartist": "Album artist",
    "album artist": "Album artist", "album_artist": "Album artist",
    "tracknumber": "Track number", "track": "Track number", "tracktotal": "Track number",
    "totaltracks": "Track number", "discnumber": "Disc number", "disc": "Disc number",
    "disctotal": "Disc number", "totaldiscs": "Disc number", "date": "Date", "year": "Date",
    "originaldate": "Date", "genre": "Genre", "bpm": "BPM", "tempo": "BPM",
    "initialkey": "Key", "initial_key": "Key", "key": "Key", "comment": "Comment",
    "description": "Comment", "label": "Label", "organization": "Label", "publisher": "Label",
    "catalognumber": "Catalog number", "replaygain_track_gain": "ReplayGain track gain",
    "replaygain_track_peak": "ReplayGain track peak",
    "replaygain_album_gain": "ReplayGain album gain",
    "replaygain_album_peak": "ReplayGain album peak",
    "r128_track_gain": "ReplayGain track gain", "r128_album_gain": "ReplayGain album gain",
    "lyrics": "Lyrics", "unsyncedlyrics": "Lyrics", "metadata_block_picture": "Cover art",
    "(flac picture block)": "Cover art",
    "musicbrainz_trackid": "MusicBrainz track ID", "musicbrainz_albumid": "MusicBrainz album ID",
    "musicbrainz_artistid": "MusicBrainz artist ID",
    "musicbrainz_albumartistid": "MusicBrainz album artist ID",
    "discogs_release_id": "Discogs release ID", "discogs_artist_id": "Discogs artist ID",
}  # fmt: skip
_MP4 = {
    "\xa9nam": "Title", "\xa9art": "Artist", "\xa9alb": "Album", "aart": "Album artist",
    "trkn": "Track number", "disk": "Disc number", "\xa9day": "Date", "\xa9gen": "Genre",
    "tmpo": "BPM", "\xa9cmt": "Comment", "\xa9lyr": "Lyrics", "covr": "Cover art",
    "----:com.apple.itunes:initialkey": "Key", "----:com.apple.itunes:key": "Key",
    "----:com.apple.itunes:label": "Label", "----:com.apple.itunes:publisher": "Label",
    "----:com.apple.itunes:catalognumber": "Catalog number",
    "----:com.apple.itunes:replaygain_track_gain": "ReplayGain track gain",
    "----:com.apple.itunes:replaygain_track_peak": "ReplayGain track peak",
    "----:com.apple.itunes:replaygain_album_gain": "ReplayGain album gain",
    "----:com.apple.itunes:replaygain_album_peak": "ReplayGain album peak",
    "----:com.apple.itunes:musicbrainz track id": "MusicBrainz track ID",
    "----:com.apple.itunes:musicbrainz album id": "MusicBrainz album ID",
    "----:com.apple.itunes:musicbrainz artist id": "MusicBrainz artist ID",
    "----:com.apple.itunes:musicbrainz album artist id": "MusicBrainz album artist ID",
    "----:com.apple.itunes:discogs_release_id": "Discogs release ID",
    "----:com.apple.itunes:discogs_artist_id": "Discogs artist ID",
}  # fmt: skip
_RIFF = {
    "INAM": "Title", "IART": "Artist", "IPRD": "Album", "ICRD": "Date", "IGNR": "Genre",
    "ITRK": "Track number", "IPRT": "Track number", "ICMT": "Comment",
}  # fmt: skip


def used_as(system: str, name: str) -> str | None:
    """The Tagwerk field a raw tag field feeds, or None if Tagwerk ignores it."""
    if system == "id3":
        frame_id = name.split(":", 1)[0]
        if frame_id == "COMM" and name.split(":")[1].lower().startswith("itun"):
            return None  # hidden player data like iTunNORM, skipped by the tag reader
        if frame_id in ("COMM", "USLT", "SYLT", "APIC"):
            return _ID3[frame_id]
        if frame_id == "TXXX":
            return _ID3.get("TXXX:" + name.split(":", 1)[1].lower()) if ":" in name else None
        return _ID3.get(name)
    if system == "vorbis":
        return _VORBIS.get(name.lower())
    if system == "mp4":
        return _MP4.get(name.lower())
    if system == "riff-info":
        return _RIFF.get(name)
    return None
