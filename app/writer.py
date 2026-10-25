"""Write tags into audio files, and undo writes. The only module that changes music files.

Principles (docs/decisions/0009-writing-tags.md):
- Only the fields being edited are touched. Every other field stays exactly as it is,
  including ones Tagwerk doesn't know (beaTunes, Serato, ...).
- Before writing, the current raw values of everything that will change are captured in a
  **snapshot** (plain JSON). Undo writes the snapshot back, so the original stored values
  return exactly (e.g. a BPM stored as "0" comes back as "0").
- Values are written where the file already keeps them (a FLAC with "organization" keeps
  using "organization" for the label); new fields use Picard/Rekordbox conventions.
- Existing ID3 tags keep their version; new ID3 tags are v2.3, which DJ software reads best.
- Keys are written in standard notation ("Am", "F#"), as the ID3 TKEY spec defines.

Field values are strings in the app's common format: "3/12" for track numbers,
"Artist A; Artist B" for several values, "" or None to remove a field.

**Cover art** is the field "cover". Its value is the id of an image in the ImageStore
(app/images.py), or None to remove all embedded pictures. Pictures are big, so the snapshot
keeps the old ones in the ImageStore too and refers to them by id.

**Advanced tags** (ADR 0039) change any field by its raw name, e.g. "raw:id3:TXXX:fBPM"; see
RAW below. They are written before the normal fields, so a normal field always wins.
"""

import base64
import binascii
import json
import re
import struct
from collections.abc import Callable
from enum import Enum
from pathlib import Path

import mutagen
from mutagen._riff import RiffFile
from mutagen._vorbis import VCommentDict
from mutagen.flac import Picture
from mutagen.id3 import ID3, USLT, Frames, TextFrame, UrlFrame, UrlFrameU
from mutagen.mp4 import MP4Cover, MP4FreeForm, MP4Tags

from app.images import ImageStore, image_info
from app.keys import display, to_camelot
from app.rawtags import FLAC_PICTURES, SYSTEMS, id3_name, id3_texts, mp4_texts, used_as
from app.tags import DISCOGS_TRACK_RE, MBID_RE, is_comment_frame

# Editable fields: name -> label. Order is the default form order.
EDITABLE = {
    "title": "Title",
    "artist": "Artist",
    "album": "Album",
    "albumartist": "Album artist",
    "track": "Track",
    "disc": "Disc",
    "date": "Date",
    "genre": "Genre",
    "bpm": "BPM",
    "key": "Key",
    "comment": "Comment",
    "label": "Label",
    "catalognumber": "Catalog number",
}
# ID fields: their own sections on the edit page (ADR 0045), and "Fix IDs" (app/ids.py, ADR 0018).
IDS = {
    "mb_trackid": "MusicBrainz track ID",
    "mb_albumid": "MusicBrainz album ID",
    "mb_artistid": "MusicBrainz artist ID",
    "mb_albumartistid": "MusicBrainz album artist ID",
    "discogs_releaseid": "Discogs release ID",
    "discogs_artistid": "Discogs artist ID",
    "discogs_trackid": "Discogs track ID",  # release and position: 33199809-3
}
# ReplayGain (ADR 0028): gains in dB ("-6.20 dB"), peaks as linear amplitude ("0.988525",
# 1.0 is full scale). Its own section on the edit page, not part of the inbox and import.
REPLAYGAIN = {
    "replaygain_track_gain": "ReplayGain track gain",
    "replaygain_track_peak": "ReplayGain track peak",
    "replaygain_album_gain": "ReplayGain album gain",
    "replaygain_album_peak": "ReplayGain album peak",
}
_GAINS = {"replaygain_track_gain", "replaygain_album_gain"}
_PEAKS = {"replaygain_track_peak", "replaygain_album_peak"}
# Opus keeps gains in its own fields (RFC 7845): whole numbers in 1/256 dB, relative to the
# EBU R128 level of -23 LUFS instead of ReplayGain's -18 LUFS. It has no peak fields.
_R128 = {"replaygain_track_gain": "R128_TRACK_GAIN", "replaygain_album_gain": "R128_ALBUM_GAIN"}
R128_OFFSET = 5.0  # dB between the two reference levels
# "A; B" is written as two values. The MusicBrainz track ID can only hold one (ID3 UFID), and
# a track has one Discogs track ID.
MULTI_VALUE = {"artist", "albumartist", "genre", *IDS} - {"mb_trackid", "discogs_trackid"}
COVER = "cover"
# Every field a change can have, with its label: the text fields, IDs and cover art.
LABELS = {**EDITABLE, **REPLAYGAIN, **IDS, COVER: "Cover art"}
# Removing one program's private ID3 frames (PRIV), e.g. "private:TRAKTOR4" for the waveform,
# beat grid and cue points Traktor keeps in the file. Only removal; only ID3 has them.
PRIVATE = "private:"
# Not a tag: a copy on the Duplicates page queued for the library trash (ADR 0027). Moved by
# app/duplicates.py when the pending changes are applied, never written by this module.
TRASH = "trash"
# Advanced tags (ADR 0039): any field of a file by its raw name, as the track page lists it
# (app/rawtags.py): "raw:id3:TXXX:fBPM", "raw:vorbis:mood", "raw:riff-info:ISFT". The value is
# a JSON list of texts (a field can hold several), or None to remove the field. Fields that
# don't hold text (pictures, private data) can only be removed.
RAW = "raw:"
RIFF_INFO = RAW + "riff-info:"  # a WAV file's RIFF INFO chunk, written apart from its ID3 tag


TRAKTOR = PRIVATE + "TRAKTOR4"  # Traktor's waveform, beat grid and cue points


def private_owners(path: Path) -> set[str]:
    """Which programs keep private ID3 data in a file (e.g. {"TRAKTOR4"}). Never raises."""
    try:
        tags = mutagen.File(path).tags
        return {f.owner for f in tags.getall("PRIV")} if isinstance(tags, ID3) else set()
    except Exception:
        return set()


def supports(fmt: str | None, field: str) -> bool:
    """Whether a file format can hold a field: Opus has no ReplayGain peaks (RFC 7845)."""
    return not (fmt == "opus" and field in _PEAKS)


def label(field: str) -> str:
    """A change's field as shown on the pages."""
    if field.startswith(PRIVATE):
        return f"Private data ({field.removeprefix(PRIVATE)})"
    if field.startswith(RAW):
        system, name = raw_parts(field)
        return f"{name} ({SYSTEMS.get(system, system)})"
    if field == TRASH:
        return "Move to trash"
    return LABELS[field]


def label_order(field: str) -> int:
    """Where a field goes when changes are listed: form order, private data and advanced
    tags last."""
    order = list(LABELS)
    return order.index(field) if field in LABELS else len(order)


class WriteError(Exception):
    """A change can't be written, e.g. the format has no tags or the value is invalid."""


# --- Values ---------------------------------------------------------------------------------


def normalize(field: str, value: str | None) -> str | None:
    """Clean and validate a value typed in the form. Returns None to remove the field.

    Raises ValueError with a readable message for values that can't be written.
    """
    if field not in EDITABLE and field not in IDS and field not in REPLAYGAIN:
        raise ValueError(f"{field} can't be edited")
    value = (value or "").strip()
    if not value:
        return None
    if field in IDS:
        return _normalize_ids(field, value)
    if field in REPLAYGAIN:
        return _normalize_replaygain(field, value)
    if field in MULTI_VALUE:
        parts = [p.strip() for p in value.split(";") if p.strip()]
        return "; ".join(dict.fromkeys(parts)) or None
    if field == "bpm":
        try:
            bpm = float(value.replace(",", "."))
        except ValueError:
            raise ValueError("BPM must be a number, e.g. 128 or 127.5") from None
        if not 20 <= bpm <= 400:
            raise ValueError("BPM must be between 20 and 400")
        return f"{bpm:g}"
    if field == "key":
        code = to_camelot(value)
        if code is None:
            raise ValueError("Not a key Tagwerk knows, e.g. Am, 8A, 1m or F# minor")
        return display(code, "musical")
    if field in ("track", "disc"):
        if not re.fullmatch(r"\d{1,4}(/\d{1,4})?", value.replace(" ", "")):
            raise ValueError(f"{EDITABLE[field]} must look like 3 or 3/12")
        return value.replace(" ", "")
    if field == "date" and not re.fullmatch(r"\d{4}(-\d{2}(-\d{2})?)?", value):
        raise ValueError("Date must look like 2021 or 2021-05-14")
    return value


def _normalize_replaygain(field: str, value: str) -> str:
    """ "-6.2", "-6,2 dB" -> "-6.20 dB"; "0.98" -> "0.980000" (how taggers write them)."""
    match = re.fullmatch(r"([-+]?\d+(?:[.,]\d+)?)\s*(db)?", value, re.IGNORECASE)
    number = float(match.group(1).replace(",", ".")) if match else None
    if field in _GAINS:
        if number is None or not -60 <= number <= 60:
            raise ValueError("A gain is a number of dB between -60 and 60, e.g. -6.5")
        return f"{number:.2f} dB"
    if number is None or match.group(2) or not 0 <= number <= 10:
        raise ValueError("A peak is a number like 0.98 (1.0 is full scale)")
    return f"{number:.6f}"


# Links pasted from MusicBrainz or Discogs: the ID is taken out of them (ADR 0045). The page
# must be the field's kind: a recording's link is no release ID.
_MB_LINK = re.compile(r"musicbrainz\.org/([a-z-]+)/([0-9a-f-]{36})", re.IGNORECASE)
_DISCOGS_LINK = re.compile(
    r"discogs\.com/(?:.*/)?(release|master|artist|label)/(\d+)", re.IGNORECASE
)
_LINK_KINDS = {
    "mb_trackid": "recording",
    "mb_albumid": "release",
    "mb_artistid": "artist",
    "mb_albumartistid": "artist",
    "discogs_releaseid": "release",
    "discogs_artistid": "artist",
}


def _id_from_link(field: str, part: str) -> str:
    """ "https://musicbrainz.org/release/<id>" -> "<id>", "discogs.com/release/25124086-Name"
    -> "25124086"; anything else stays as it is. Raises ValueError for another kind of page."""
    is_mb = field.startswith("mb_")
    found = (_MB_LINK if is_mb else _DISCOGS_LINK).search(part)
    if not found:
        return part
    kind, found_id = found.group(1).lower(), found.group(2)
    if kind != _LINK_KINDS[field]:
        service = "MusicBrainz" if is_mb else "Discogs"
        raise ValueError(
            f"That's the link of a {service} {kind}, this field needs a {_LINK_KINDS[field]}"
        )
    return found_id


def _normalize_ids(field: str, value: str) -> str:
    if field == "discogs_trackid":  # one value, its position written as on Discogs ("A1")
        if not DISCOGS_TRACK_RE.match(value):
            raise ValueError("A Discogs track ID is the release and the position, e.g. 33199809-3")
        return value
    parts = [_id_from_link(field, p.strip()).lower() for p in value.split(";") if p.strip()]
    parts = list(dict.fromkeys(parts))
    if field.startswith("mb_"):
        if not all(MBID_RE.match(p) for p in parts):
            raise ValueError("A MusicBrainz ID looks like 0b6a4e7c-3a4f-4b8e-9d0e-1f2a3b4c5d6e")
        if field == "mb_trackid" and len(parts) > 1:
            raise ValueError("A track has only one MusicBrainz track ID")
    elif not all(p.isdigit() for p in parts):
        raise ValueError("A Discogs ID is a number, e.g. 25124086")
    return "; ".join(parts)


def current_value(track, field: str) -> str | None:
    """A field's value from a Track row, in the same format the form and normalize() use."""
    if field == "track":
        return _number(track.tracknumber, track.tracktotal)
    if field == "disc":
        return _number(track.discnumber, track.disctotal)
    if field == "bpm":
        return f"{track.bpm:g}" if track.bpm else None
    if field == "key":
        return display(track.key_camelot, "musical") if track.key_camelot else track.key
    if field == COVER:
        return "embedded" if track.has_cover else None
    if field in REPLAYGAIN:
        number = getattr(track, field)
        if number is None:
            return None
        return f"{number:.2f} dB" if field in _GAINS else f"{number:.6f}"
    return getattr(track, field)


def _number(n: int | None, total: int | None) -> str | None:
    if not n:
        return None
    return f"{n}/{total}" if total else str(n)


def _split(value: str | None) -> list[str]:
    return [p.strip() for p in (value or "").split(";") if p.strip()]


# --- Advanced tags: raw fields ----------------------------------------------------------------

# MP4 atoms that hold text (as mutagen reads and writes them); other names a DJ types become
# iTunes freeform fields ("MOOD" -> "----:com.apple.iTunes:MOOD"), like Picard writes them.
_MP4_TEXT_ATOMS = {
    "\xa9nam", "\xa9ART", "\xa9alb", "aART", "\xa9wrt", "\xa9day", "\xa9cmt", "\xa9grp",
    "\xa9gen", "\xa9lyr", "\xa9too", "desc", "purd", "catg", "keyw", "cprt", "soal", "soaa",
    "soar", "sonm", "soco", "sosn", "tvsh", "purl", "egid",
}  # fmt: skip
# MP4 atoms holding numbers, pairs, flags or pictures: never typed in.
_MP4_NOT_TEXT = {
    "trkn", "disk", "gnre", "tmpo", "cpil", "pgap", "pcst", "rtng", "stik", "hdvd", "shwm",
    "covr", "plID", "cnID", "geID", "atID", "sfID", "cmID", "akID", "tvsn", "tves", "\xa9mvi",
    "\xa9mvc",
}  # fmt: skip
# ID3 dates (ID3 timestamps): 2021, 2021-05, 2021-05-14 or 2021-05-14T20:30(:15)
_ID3_TIMESTAMPS = {"TDEN", "TDOR", "TDRC", "TDRL", "TDTG"}
_TIMESTAMP = re.compile(r"\d{4}(-\d{2}(-\d{2}(T\d{2}(:\d{2}(:\d{2})?)?)?)?)?")
# ID3v2.4 frames ID3v2.3 doesn't have: saving a v2.3 tag leaves them out (mutagen).
_ID3_V24_ONLY = {"TDEN", "TDRL", "TDTG", "TMOO", "TPRO", "TSOA", "TSOP", "TSOT", "TSST"}
# used_as() names fields like the track page; the writer's own names differ for two of them.
_FEEDS = {**{text: name for name, text in LABELS.items()}, "Track number": "track",
          "Disc number": "disc"}  # fmt: skip


def raw_field(system: str, name: str) -> str:
    """The change field for a raw tag field: ("id3", "TXXX:fBPM") -> "raw:id3:TXXX:fBPM"."""
    return f"{RAW}{system}:{name}"


def raw_parts(field: str) -> tuple[str, str]:
    """("id3", "TXXX:fBPM") for "raw:id3:TXXX:fBPM"."""
    system, _, name = field.removeprefix(RAW).partition(":")
    return system, name


def raw_values(value: str | None) -> list[str] | None:
    """A raw change's value as a list of texts (None: remove the field)."""
    return json.loads(value) if value is not None else None


def raw_value(values: list[str] | None) -> str | None:
    """The stored form of a raw change's texts: a JSON list, None for no values."""
    return json.dumps(values, ensure_ascii=False) if values else None


def feeds(field: str) -> str | None:
    """The normal field a raw field feeds, e.g. "bpm" for "raw:id3:TBPM". When both change, the
    normal field wins (ADR 0039)."""
    return _FEEDS.get(used_as(*raw_parts(field)) or "")


def holds_one_value(system: str, name: str) -> bool:
    """RIFF INFO fields, ID3 lyrics (USLT) and ID3 links (W…) hold one text each."""
    return system == "riff-info" or (system == "id3" and name.startswith(("USLT", "W")))


def new_raw_field(system: str, typed: str, id3v23: bool = False) -> str:
    """The change field for a field the owner adds, from the name typed. "MOOD" becomes
    "raw:id3:TXXX:MOOD" (MP3), "raw:vorbis:mood" (FLAC) or "raw:mp4:----:com.apple.iTunes:MOOD"
    (M4A). ``id3v23``: the file has an ID3v2.3 tag, which can't hold some newer frames.

    Raises ValueError with a readable message for names that can't hold text.
    """
    name = typed.strip()
    if not name:
        raise ValueError("Type the field's name, e.g. MOOD")
    if system == "id3":
        name = _new_id3_name(name, id3v23)
    elif system == "vorbis":
        if not all(" " <= c <= "}" and c != "=" for c in name):
            raise ValueError("A Vorbis name has plain letters, digits and spaces, e.g. MOOD")
        name = name.lower()  # Vorbis names ignore case; Tagwerk lists and writes them in lower case
        if name == "metadata_block_picture":
            raise ValueError("Pictures can't be typed in: use Cover art above")
    elif system == "mp4":
        if name in _MP4_NOT_TEXT:
            raise ValueError(f"{name} doesn't hold text, so it can't be typed in")
        if not name.startswith("----:") and name not in _MP4_TEXT_ATOMS:
            name = _FF + name
        if name.startswith("----:"):
            _, mean, key = (name.split(":", 2) + ["", ""])[:3]
            if not mean or not key:
                raise ValueError("A freeform name looks like ----:com.apple.iTunes:MOOD")
        try:
            name.encode("latin-1")
        except UnicodeEncodeError:
            raise ValueError("MP4 names can't hold that character") from None
    elif system == "riff-info":
        name = name.upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9]{3}", name):
            raise ValueError("A RIFF INFO name has four letters, e.g. ISFT")
    else:
        raise ValueError(f"Unknown tag system: {system}")
    return raw_field(system, name)


def _new_id3_name(name: str, v23: bool) -> str:
    """An ID3 name: a frame like TSRC stays itself, "TXXX:MOOD" and "COMM:DJ notes" get their
    parts, any other name becomes a TXXX field of its own ("MOOD" -> "TXXX:MOOD")."""
    frame_id, colon, rest = name.partition(":")
    frame_id = frame_id.upper()
    if frame_id in ("COMM", "USLT"):  # name and language: "COMM:DJ notes:eng"
        desc, lang = rest, "eng"
        if re.search(r":[A-Za-z]{3}$", rest):
            desc, lang = rest[:-4], rest[-3:].lower()
        return f"{frame_id}:{desc}:{lang}"
    if frame_id in ("TXXX", "WXXX"):
        if frame_id == "TXXX" and not rest:
            raise ValueError("Type a name after TXXX:, e.g. TXXX:MOOD")
        return f"{frame_id}:{rest}"
    if colon:
        raise ValueError("Only TXXX, WXXX, COMM and USLT have a name after the colon")
    cls = Frames.get(frame_id)
    if cls is None:
        return f"TXXX:{name}"  # a field of its own
    if not issubclass(cls, (TextFrame, UrlFrame)) or issubclass(cls, UrlFrameU):
        raise ValueError(f"{frame_id} doesn't hold text, so it can't be typed in")
    if v23 and frame_id in _ID3_V24_ONLY:
        raise ValueError(f"{frame_id} needs ID3v2.4 and this file has ID3v2.3: try TXXX:{name}")
    return frame_id


def normalize_raw(field: str, values: list[str]) -> list[str] | None:
    """Clean the texts typed for a raw field: line breaks as "\\n", spaces around them and
    empty ones gone. Returns None (remove the field) when nothing is left.

    Raises ValueError for values the field can't hold.
    """
    system, name = raw_parts(field)
    cleaned = [v.replace("\r\n", "\n").strip() for v in values]
    cleaned = [v for v in cleaned if v]
    if not cleaned:
        return None
    if len(cleaned) > 1 and holds_one_value(system, name):
        raise ValueError("This field holds one value")
    dates = system == "id3" and name in _ID3_TIMESTAMPS
    if dates and not all(_TIMESTAMP.fullmatch(v) for v in cleaned):
        raise ValueError("A date looks like 2021, 2021-05-14 or 2021-05-14T20:30")
    return cleaned


# --- Public API -----------------------------------------------------------------------------


def write(path: Path, changes: dict[str, str | None], images: ImageStore | None = None) -> dict:
    """Write normalized values into a file. Returns the snapshot needed to undo it.

    ``images`` is needed when the changes include cover art.
    """
    if COVER in changes and images is None:
        raise WriteError("cover art needs an image store")
    audio = mutagen.File(path)
    if audio is None:
        raise WriteError("not a recognized audio file")
    handler = _handler(audio)
    if handler is not _ID3 and any(f.startswith(PRIVATE) for f in changes):
        raise WriteError("only ID3 tags (MP3, WAV, AIFF) have private data")
    if _is_opus(audio) and any(changes.get(f) is not None for f in _PEAKS):
        raise WriteError("Opus files have no ReplayGain peak fields")
    riff = {f: v for f, v in changes.items() if f.startswith(RIFF_INFO)}
    if riff and type(audio).__name__ != "WAVE":
        raise WriteError("only WAV files have RIFF INFO")
    for field in changes:
        system = raw_parts(field)[0]
        if field.startswith(RAW) and field not in riff and system != handler.system:
            theirs = SYSTEMS.get(system, system)
            raise WriteError(f"this file's tags are {SYSTEMS[handler.system]}, not {theirs}")
    # Advanced tags first: when a normal field changes too, it is written last and wins.
    tag_changes = {f: v for f, v in changes.items() if f.startswith(RAW) and f not in riff}
    tag_changes |= {f: v for f, v in changes.items() if not f.startswith(RAW)}
    snapshot = handler.write(audio, tag_changes, images) if tag_changes else {}
    if riff:
        snapshot["riff_info"] = _RiffInfo.write(path, riff)
    return {"system": handler.system, "fields": sorted(tag_changes), **snapshot}


def undo(path: Path, snapshot: dict, images: ImageStore | None = None) -> None:
    """Restore the values captured by write()."""
    if snapshot["fields"]:
        audio = mutagen.File(path)
        if audio is None:
            raise WriteError("not a recognized audio file")
        handler = _handler(audio)
        if handler.system != snapshot["system"]:
            raise WriteError("the file's tag format changed since the change was applied")
        handler.undo(audio, snapshot, images)
    if "riff_info" in snapshot:
        _RiffInfo.undo(path, snapshot["riff_info"])


def tag_converted(path: Path, frames: list) -> None:
    """Put all tags into an AIFF that Tagwerk just converted (app/convert.py).

    Only for a brand-new file that isn't in the library yet, so no snapshot is needed:
    undoing a conversion removes the whole file. ID3v2.4 keeps several values per field
    (e.g. two artists) as they are, without joining them with "/".
    """
    audio = mutagen.File(path)
    if audio is None or type(audio).__name__ != "AIFF":
        raise WriteError("not a converted AIFF file")
    if audio.tags is None:
        audio.add_tags()
    for frame in frames:
        audio.tags.add(frame)
    audio.save(v2_version=4)


def _is_opus(audio) -> bool:
    return type(audio).__name__ == "OggOpus"


def _picture(data: bytes) -> Picture:
    """A front-cover picture block (FLAC, OGG, Opus) for image bytes."""
    mime, width, height = image_info(data)
    picture = Picture()
    picture.type = 3  # front cover
    picture.mime = mime
    picture.desc = ""
    picture.width, picture.height = width, height
    picture.depth = 24
    picture.data = data
    return picture


def tag_system(audio) -> str:
    """The tag system a file opened with mutagen has, or gets when it has no tags yet."""
    return _handler(audio).system


def _handler(audio):
    tags = audio.tags
    if tags is None:
        # No tags yet: MP4 and Vorbis files can get them, MP3/WAV/AIFF get ID3.
        kind = type(audio).__name__
        if kind == "MP4":
            return _MP4
        if kind in ("FLAC", "OggVorbis", "OggOpus"):
            return _Vorbis
        return _ID3
    if isinstance(tags, ID3):
        return _ID3
    if isinstance(tags, VCommentDict):
        return _Vorbis
    if isinstance(tags, MP4Tags):
        return _MP4
    raise WriteError(f"can't write tags of type {type(tags).__name__}")


# --- ID3 (MP3, WAV, AIFF) -------------------------------------------------------------------


MUSICBRAINZ_UFID = "http://musicbrainz.org"


def _id3_txxx(name: str) -> Callable:
    return lambda f: f.FrameID == "TXXX" and f.desc.lower() == name


# Which frames belong to each field (everything matching is replaced or restored together).
_ID3_GROUPS: dict[str, Callable] = {
    "title": lambda f: f.FrameID == "TIT2",
    "artist": lambda f: f.FrameID == "TPE1",
    "album": lambda f: f.FrameID == "TALB",
    "albumartist": lambda f: f.FrameID == "TPE2",
    "track": lambda f: f.FrameID == "TRCK",
    "disc": lambda f: f.FrameID == "TPOS",
    "date": lambda f: f.FrameID in ("TDRC", "TYER", "TDAT"),
    "genre": lambda f: f.FrameID == "TCON",
    "bpm": lambda f: f.FrameID == "TBPM",
    "key": lambda f: f.FrameID == "TKEY",
    # Every comment the reader shows (incl. copies like "ID3v1 Comment"); hidden player
    # comments like iTunNORM stay untouched.
    "comment": is_comment_frame,
    "label": lambda f: f.FrameID == "TPUB" or _id3_txxx("label")(f),
    "catalognumber": _id3_txxx("catalognumber"),
    "mb_trackid": lambda f: f.FrameID == "UFID" and f.owner == MUSICBRAINZ_UFID,
    "mb_albumid": _id3_txxx("musicbrainz album id"),
    "mb_artistid": _id3_txxx("musicbrainz artist id"),
    "mb_albumartistid": _id3_txxx("musicbrainz album artist id"),
    "discogs_releaseid": _id3_txxx("discogs_release_id"),
    "discogs_artistid": _id3_txxx("discogs_artist_id"),
    "discogs_trackid": _id3_txxx("discogs_track_id"),
    "replaygain_track_gain": _id3_txxx("replaygain_track_gain"),
    "replaygain_track_peak": _id3_txxx("replaygain_track_peak"),
    "replaygain_album_gain": _id3_txxx("replaygain_album_gain"),
    "replaygain_album_peak": _id3_txxx("replaygain_album_peak"),
    COVER: lambda f: f.FrameID == "APIC",
}
# TXXX frames by field, with the name used when the file has none yet (Picard's and Mp3tag's).
_ID3_TXXX = {
    "catalognumber": "CATALOGNUMBER",
    "mb_albumid": "MusicBrainz Album Id",
    "mb_artistid": "MusicBrainz Artist Id",
    "mb_albumartistid": "MusicBrainz Album Artist Id",
    "discogs_releaseid": "DISCOGS_RELEASE_ID",
    "discogs_artistid": "DISCOGS_ARTIST_ID",
    "discogs_trackid": "DISCOGS_TRACK_ID",
    "replaygain_track_gain": "REPLAYGAIN_TRACK_GAIN",
    "replaygain_track_peak": "REPLAYGAIN_TRACK_PEAK",
    "replaygain_album_gain": "REPLAYGAIN_ALBUM_GAIN",
    "replaygain_album_peak": "REPLAYGAIN_ALBUM_PEAK",
}


def _id3_group(field: str) -> Callable:
    if field.startswith(PRIVATE):
        owner = field.removeprefix(PRIVATE)
        return lambda f: f.FrameID == "PRIV" and f.owner == owner
    if field.startswith(RAW):
        name = raw_parts(field)[1]
        return lambda f: id3_name(f) == name  # named as on the track page (app/rawtags.py)
    return _ID3_GROUPS[field]


class _ID3:
    system = "id3"

    @staticmethod
    def write(audio, changes: dict[str, str | None], images: ImageStore | None) -> dict:
        created = audio.tags is None
        if created:
            audio.add_tags()
        tags = audio.tags
        version = 3 if created else tags.version[1]
        before = [
            _frame_to_json(f, images)
            for f in tags.values()
            if any(_id3_group(field)(f) for field in changes)
        ]
        for field, value in changes.items():
            _ID3._set(tags, field, value, images)
        audio.save(v2_version=version)
        return {"frames": before, "created": created, "version": version}

    @staticmethod
    def _set(tags, field: str, value: str | None, images: ImageStore | None = None) -> None:
        if field.startswith(RAW):
            _ID3._set_raw(tags, raw_parts(field)[1], raw_values(value))
            return
        group = _id3_group(field)
        existing = [f for f in tags.values() if group(f)]
        lang = next((f.lang for f in existing if field == "comment"), "eng")
        txxx_desc = next((f.desc for f in existing if f.FrameID == "TXXX"), None)
        has_tpub = any(f.FrameID == "TPUB" for f in existing)
        for f in existing:
            del tags[f.HashKey]
        if value is None:
            return
        frames = Frames
        if field == COVER:
            data = images.get(value)
            mime = image_info(data)[0]
            tags.add(frames["APIC"](encoding=3, mime=mime, type=3, desc="", data=data))
        elif field == "comment":
            tags.add(frames["COMM"](encoding=3, lang=lang, desc="", text=[value]))
        elif field == "mb_trackid":
            tags.add(frames["UFID"](owner=MUSICBRAINZ_UFID, data=value.encode("ascii")))
        elif field in _ID3_TXXX:
            text = _split(value) if field in MULTI_VALUE else [value]
            tags.add(frames["TXXX"](encoding=3, desc=txxx_desc or _ID3_TXXX[field], text=text))
        elif field == "label" and txxx_desc and not has_tpub:
            tags.add(frames["TXXX"](encoding=3, desc=txxx_desc, text=[value]))  # keep its spot
        else:
            frame_id = {
                "title": "TIT2", "artist": "TPE1", "album": "TALB", "albumartist": "TPE2",
                "track": "TRCK", "disc": "TPOS", "date": "TDRC", "genre": "TCON",
                "bpm": "TBPM", "key": "TKEY", "label": "TPUB",
            }[field]  # fmt: skip
            if field == "bpm":
                value = str(round(float(value)))  # TBPM is an integer by the ID3 spec
            text = _split(value) if field in MULTI_VALUE else [value]
            tags.add(frames[frame_id](encoding=3, text=text))

    @staticmethod
    def _set_raw(tags, name: str, values: list[str] | None) -> None:
        """Change one frame in place, so its name, language and kind stay as they are; a new
        one is made from its name ("TXXX:MOOD", "COMM:DJ notes:eng", "TSRC")."""
        existing = [f for f in tags.values() if id3_name(f) == name]
        if values is None:
            for f in existing:
                del tags[f.HashKey]
            return
        if len(existing) > 1 or (existing and not _id3_holds_text(existing[0])):
            raise WriteError(f"{name} doesn't hold text: it can only be removed")
        frame = existing[0] if existing else _new_id3_frame(name)
        if isinstance(frame, UrlFrame):
            frame.url = values[0]
        elif isinstance(frame, USLT):
            frame.text = values[0]
        else:
            frame.text = values
        if hasattr(frame, "encoding"):
            frame.encoding = 3  # UTF-8 (UTF-16 in ID3v2.3), so any character fits
        if not existing:
            tags.add(frame)

    @staticmethod
    def undo(audio, snapshot: dict, images: ImageStore | None) -> None:
        tags = audio.tags
        if tags is None:
            audio.add_tags()
            tags = audio.tags
        for f in [f for f in tags.values() if any(_id3_group(x)(f) for x in snapshot["fields"])]:
            del tags[f.HashKey]
        for data in snapshot["frames"]:
            tags.add(_frame_from_json(data, images))
        if snapshot["created"] and not tags:
            audio.delete()  # the file had no ID3 tags before: remove the empty block again
        else:
            audio.save(v2_version=snapshot["version"])


def _id3_holds_text(frame) -> bool:
    """Text frames (incl. TXXX, COMM), lyrics (USLT) and links, as app/rawtags.py reads them."""
    return id3_texts(frame) is not None


def _new_id3_frame(name: str):
    """An empty frame for a name checked by new_raw_field()."""
    frame_id, _, rest = name.partition(":")
    if frame_id in ("COMM", "USLT"):
        desc, _, lang = rest.rpartition(":")
        return Frames[frame_id](encoding=3, desc=desc, lang=lang)
    if frame_id in ("TXXX", "WXXX"):
        return Frames[frame_id](encoding=3, desc=rest)
    frame = Frames[frame_id]()
    if not _id3_holds_text(frame):
        raise WriteError(f"{frame_id} doesn't hold text")
    return frame


def _frame_to_json(frame, images: ImageStore | None = None) -> dict:
    attrs = {
        spec.name: _to_json(getattr(frame, spec.name, None), images) for spec in frame._framespec
    }
    for spec in getattr(frame, "_optionalspec", []):
        if hasattr(frame, spec.name):
            attrs[spec.name] = _to_json(getattr(frame, spec.name), images)
    return {"id": frame.FrameID, "attrs": attrs}


def _frame_from_json(data: dict, images: ImageStore | None = None):
    return Frames[data["id"]](**{k: _from_json(v, images) for k, v in data["attrs"].items()})


def _to_json(value, images: ImageStore | None = None):
    if isinstance(value, bytes):
        if images is not None and len(value) > 1024:  # pictures go to the image store
            return {"image": images.put(value)}
        return {"b64": base64.b64encode(value).decode()}
    if isinstance(value, Enum):
        return int(value.value)
    if isinstance(value, (list, tuple)):
        return [_to_json(v, images) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)  # e.g. ID3TimeStamp


def _from_json(value, images: ImageStore | None = None):
    if isinstance(value, dict) and "b64" in value:
        return base64.b64decode(value["b64"])
    if isinstance(value, dict) and "image" in value:
        return images.get(value["image"])
    if isinstance(value, list):
        return [_from_json(v, images) for v in value]
    return value


# --- Vorbis comments (FLAC, OGG, Opus) ------------------------------------------------------

# field -> keys that hold it; the first one is used when the file has none of them yet.
_VORBIS_KEYS = {
    "title": ["title"],
    "artist": ["artist"],
    "album": ["album"],
    "albumartist": ["albumartist", "album artist", "album_artist"],
    "date": ["date", "year"],
    "genre": ["genre"],
    "bpm": ["bpm", "tempo"],
    "key": ["initialkey", "initial_key", "key"],
    "comment": ["comment", "description"],
    "label": ["label", "organization", "publisher"],
    "catalognumber": ["catalognumber"],
    "mb_trackid": ["musicbrainz_trackid"],
    "mb_albumid": ["musicbrainz_albumid"],
    "mb_artistid": ["musicbrainz_artistid"],
    "mb_albumartistid": ["musicbrainz_albumartistid"],
    "discogs_releaseid": ["discogs_release_id"],
    "discogs_artistid": ["discogs_artist_id"],
    "discogs_trackid": ["discogs_track_id"],
    "replaygain_track_gain": ["replaygain_track_gain"],
    "replaygain_track_peak": ["replaygain_track_peak"],
    "replaygain_album_gain": ["replaygain_album_gain"],
    "replaygain_album_peak": ["replaygain_album_peak"],
}
_VORBIS_NUMBERS = {
    "track": (["tracknumber", "track"], ["tracktotal", "totaltracks"]),
    "disc": (["discnumber", "disc"], ["disctotal", "totaldiscs"]),
}


def _vorbis_keys(field: str, opus: bool = False) -> list[str]:
    if field == COVER or field == RAW + "vorbis:" + FLAC_PICTURES:
        return []  # pictures: handled by _Vorbis._write_cover / _undo_cover / _set_raw
    if field.startswith(RAW):
        return [raw_parts(field)[1].lower()]
    if field in _VORBIS_NUMBERS:
        number, total = _VORBIS_NUMBERS[field]
        return number + total
    if opus and field in _R128:  # a REPLAYGAIN_* gain some taggers add is replaced too
        return [_R128[field].lower(), *_VORBIS_KEYS[field]]
    return _VORBIS_KEYS[field]


def r128_gain(value: str) -> str:
    """A ReplayGain gain ("-6.20 dB") as Opus writes it: 1/256 dB relative to -23 LUFS."""
    return str(round((float(value.split()[0]) - R128_OFFSET) * 256))


class _Vorbis:
    system = "vorbis"

    @staticmethod
    def write(audio, changes: dict[str, str | None], images: ImageStore | None) -> dict:
        if audio.tags is None:
            audio.add_tags()
        tags = audio.tags
        opus = _is_opus(audio)
        present = {k.lower() for k in tags.keys()}  # noqa: SIM118
        wanted = {key for field in changes for key in _vorbis_keys(field, opus)}
        before: dict[str, list] = {}  # names as the file spells them, for an exact undo
        for key, value in tags:  # (tags.keys() would give them in lower case)
            if key.lower() in wanted:
                before.setdefault(key, []).append(_vorbis_to_json(key, value, images))
        snapshot: dict = {"values": before}
        for field, value in changes.items():
            if field == COVER:
                snapshot["cover"] = _Vorbis._write_cover(audio, value, images)
            elif field.startswith(RAW):
                _Vorbis._set_raw(audio, raw_parts(field)[1], raw_values(value), snapshot, images)
            elif field in _VORBIS_NUMBERS:
                _Vorbis._set_number(tags, present, field, value)
            else:
                keys = _vorbis_keys(field, opus)
                target = next((k for k in keys if k in present), keys[0])
                for k in keys:
                    if k in present:
                        del tags[k]
                if value is not None and opus and field in _R128:
                    tags[_R128[field]] = [r128_gain(value)]
                elif value is not None:
                    tags[target] = _split(value) if field in MULTI_VALUE else [value]
        audio.save()
        return snapshot

    @staticmethod
    def _write_cover(audio, value: str | None, images: ImageStore) -> dict:
        """FLAC keeps pictures in their own blocks, OGG/Opus in METADATA_BLOCK_PICTURE."""
        tags = audio.tags
        flac = hasattr(audio, "add_picture")
        before = {
            "pictures": [images.put(p.write()) for p in audio.pictures] if flac else [],
            "comments": [
                images.put(base64.b64decode(v)) for v in tags.get("metadata_block_picture", [])
            ],
        }
        if flac:
            audio.clear_pictures()
        if "metadata_block_picture" in tags:
            del tags["metadata_block_picture"]
        if value is not None:
            picture = _picture(images.get(value))
            if flac:
                audio.add_picture(picture)
            else:
                tags["metadata_block_picture"] = [base64.b64encode(picture.write()).decode()]
        return before

    @staticmethod
    def _undo_cover(audio, before: dict, images: ImageStore) -> None:
        tags = audio.tags
        if hasattr(audio, "add_picture"):
            audio.clear_pictures()
            for image_id in before["pictures"]:
                audio.add_picture(Picture(images.get(image_id)))
        if "metadata_block_picture" in tags:
            del tags["metadata_block_picture"]
        if before["comments"]:
            tags["metadata_block_picture"] = [
                base64.b64encode(images.get(i)).decode() for i in before["comments"]
            ]

    @staticmethod
    def _set_raw(audio, name: str, values: list[str] | None, snapshot: dict, images) -> None:
        """Advanced tags: one comment by its name, spelt as the file spells it (Vorbis names
        ignore case). FLAC's picture blocks can only be removed."""
        tags = audio.tags
        if name == FLAC_PICTURES:
            if values is not None:
                raise WriteError("pictures can only be removed here: use Cover art")
            snapshot["flac_pictures"] = [_to_json(p.write(), images) for p in audio.pictures]
            audio.clear_pictures()
            return
        if values is not None and name.lower() == "metadata_block_picture":
            raise WriteError("pictures can only be removed here: use Cover art")
        spelling = next((k for k, _ in tags if k.lower() == name.lower()), name)
        if name in tags:
            del tags[name]
        if values is not None:
            tags[spelling] = values

    @staticmethod
    def _set_number(tags, present: set[str], field: str, value: str | None) -> None:
        number_keys, total_keys = _VORBIS_NUMBERS[field]
        number_key = next((k for k in number_keys if k in present), number_keys[0])
        total_key = next((k for k in total_keys if k in present), total_keys[0])
        for k in number_keys + total_keys:
            if k in present:
                del tags[k]
        if value is None:
            return
        number, _, total = value.partition("/")
        tags[number_key] = [number]
        if total:
            tags[total_key] = [total]

    @staticmethod
    def undo(audio, snapshot: dict, images: ImageStore | None) -> None:
        tags = audio.tags
        present = {k.lower() for k in tags.keys()}  # noqa: SIM118
        for field in snapshot["fields"]:
            for key in _vorbis_keys(field, _is_opus(audio)):
                if key in present:
                    del tags[key]
        for key, values in snapshot["values"].items():
            tags[key] = [_vorbis_from_json(v, images) for v in values]
        if "cover" in snapshot:
            _Vorbis._undo_cover(audio, snapshot["cover"], images)
        if "flac_pictures" in snapshot:  # removed with Advanced tags
            audio.clear_pictures()
            for data in snapshot["flac_pictures"]:
                audio.add_picture(Picture(_from_json(data, images)))
        audio.save()


def _vorbis_to_json(key: str, value: str, images: ImageStore | None):
    """A comment's value for the snapshot. Pictures (METADATA_BLOCK_PICTURE, only removed with
    Advanced tags) go to the image store, so the snapshot stays small."""
    if key.lower() != "metadata_block_picture" or images is None:
        return value
    try:
        data = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return value
    if base64.b64encode(data).decode() != value:
        return value  # not written the usual way: kept as it is, for an exact undo
    return {"picture": images.put(data)}


def _vorbis_from_json(value, images: ImageStore | None) -> str:
    if isinstance(value, dict) and "picture" in value:
        return base64.b64encode(images.get(value["picture"])).decode()
    return value


# --- MP4 atoms (M4A) ------------------------------------------------------------------------

_FF = "----:com.apple.iTunes:"
_MP4_KEYS = {
    "title": ["\xa9nam"],
    "artist": ["\xa9ART"],
    "album": ["\xa9alb"],
    "albumartist": ["aART"],
    "track": ["trkn"],
    "disc": ["disk"],
    "date": ["\xa9day"],
    "genre": ["\xa9gen"],
    "bpm": ["tmpo"],
    "comment": ["\xa9cmt"],
    "key": [_FF + "initialkey", _FF + "KEY"],
    "label": [_FF + "LABEL", _FF + "publisher"],
    "catalognumber": [_FF + "CATALOGNUMBER"],
    "mb_trackid": [_FF + "MusicBrainz Track Id"],
    "mb_albumid": [_FF + "MusicBrainz Album Id"],
    "mb_artistid": [_FF + "MusicBrainz Artist Id"],
    "mb_albumartistid": [_FF + "MusicBrainz Album Artist Id"],
    "discogs_releaseid": [_FF + "DISCOGS_RELEASE_ID"],
    "discogs_artistid": [_FF + "DISCOGS_ARTIST_ID"],
    "discogs_trackid": [_FF + "DISCOGS_TRACK_ID"],
    "replaygain_track_gain": [_FF + "replaygain_track_gain"],
    "replaygain_track_peak": [_FF + "replaygain_track_peak"],
    "replaygain_album_gain": [_FF + "replaygain_album_gain"],
    "replaygain_album_peak": [_FF + "replaygain_album_peak"],
    COVER: ["covr"],
}


def _mp4_existing(tags, keys: list[str]) -> list[str]:
    """Keys present in the file, matching freeform names case-insensitively."""
    wanted = {k.lower() for k in keys}
    return [k for k in tags if k.lower() in wanted]


def _mp4_present(tags, field: str) -> list[str]:
    """A field's keys in the file. A raw field is exactly its own key."""
    if field.startswith(RAW):
        name = raw_parts(field)[1]
        return [name] if name in tags else []
    return _mp4_existing(tags, _MP4_KEYS[field])


class _MP4:
    system = "mp4"

    @staticmethod
    def write(audio, changes: dict[str, str | None], images: ImageStore | None) -> dict:
        if audio.tags is None:
            audio.add_tags()
        tags = audio.tags
        before = {}
        for field in changes:
            for key in _mp4_present(tags, field):
                values = tags[key] if isinstance(tags[key], list) else [tags[key]]
                before[key] = [_mp4_value_to_json(v, images) for v in values]
        for field, value in changes.items():
            if field.startswith(RAW):
                _MP4._set_raw(tags, raw_parts(field)[1], raw_values(value))
                continue
            existing = _mp4_existing(tags, _MP4_KEYS[field])
            target = existing[0] if existing else _MP4_KEYS[field][0]
            for key in existing:
                del tags[key]
            if value is None:
                continue
            if field == COVER:
                data = images.get(value)
                png = image_info(data)[0] == "image/png"
                fmt = MP4Cover.FORMAT_PNG if png else MP4Cover.FORMAT_JPEG
                tags[target] = [MP4Cover(data, imageformat=fmt)]
            elif field in ("track", "disc"):
                number, _, total = value.partition("/")
                tags[target] = [(int(number), int(total or 0))]
            elif field == "bpm":
                tags[target] = [round(float(value))]  # the tmpo atom holds an integer
            elif target.startswith(_FF):
                parts = _split(value) if field in MULTI_VALUE else [value]
                tags[target] = [MP4FreeForm(p.encode()) for p in parts]
            else:
                tags[target] = _split(value) if field in MULTI_VALUE else [value]
        audio.save()
        return {"values": before}

    @staticmethod
    def _set_raw(tags, name: str, values: list[str] | None) -> None:
        """Advanced tags: text atoms (©nam …) and freeform fields (----:mean:name, as UTF-8)."""
        if values is not None and name in tags and _mp4_not_text(tags[name]):
            raise WriteError(f"{name} doesn't hold text: it can only be removed")
        if name in tags:
            del tags[name]
        if values is None:
            return
        if name.startswith("----:"):
            tags[name] = [MP4FreeForm(v.encode("utf-8")) for v in values]
        else:
            tags[name] = values

    @staticmethod
    def undo(audio, snapshot: dict, images: ImageStore | None) -> None:
        tags = audio.tags
        for field in snapshot["fields"]:
            for key in _mp4_present(tags, field):
                del tags[key]
        for key, values in snapshot["values"].items():
            restored = [_mp4_value_from_json(v, images) for v in values]
            single = key in _MP4_FLAGS and len(restored) == 1  # cpil = True, not [True]
            tags[key] = restored[0] if single else restored
        audio.save()


_MP4_FLAGS = {"cpil", "pgap", "pcst"}  # mutagen keeps these as one True/False, not a list


def _mp4_not_text(values) -> bool:
    """Numbers, pairs, flags, pictures and binary data: only removable with Advanced tags."""
    try:
        return mp4_texts(values) is None
    except UnicodeDecodeError:
        return True


def _mp4_value_to_json(value, images: ImageStore | None = None):
    if isinstance(value, MP4Cover):
        return {"cover": images.put(bytes(value)), "format": int(value.imageformat)}
    if isinstance(value, MP4FreeForm):
        return {"ff": base64.b64encode(bytes(value)).decode(), "format": int(value.dataformat)}
    if isinstance(value, tuple):
        return {"tuple": list(value)}
    return value


def _mp4_value_from_json(value, images: ImageStore | None = None):
    if isinstance(value, dict) and "cover" in value:
        return MP4Cover(images.get(value["cover"]), imageformat=value["format"])
    if isinstance(value, dict) and "ff" in value:
        return MP4FreeForm(base64.b64decode(value["ff"]), dataformat=value["format"])
    if isinstance(value, dict) and "tuple" in value:
        return tuple(value["tuple"])
    return value


# --- RIFF INFO (WAV) --------------------------------------------------------------------------


class _RiffInfo:
    """A WAV file's RIFF INFO chunk (``LIST``/``INFO``): a few text fields such as INAM (title)
    or ISFT (software). Only Advanced tags change it; normal edits go to the ID3 tag (ADR 0009).
    The snapshot is the whole chunk as it was, so undo puts back the exact bytes."""

    @staticmethod
    def write(path: Path, changes: dict[str, str | None]) -> dict:
        with path.open("r+b") as f:
            riff = RiffFile(f)
            chunk = _info_chunk(riff)
            before = chunk.read() if chunk else None
            items = _info_items(before or b"INFO")
            for field, value in changes.items():
                name = raw_parts(field)[1].encode("ascii")
                values = raw_values(value)
                at = next((i for i, (n, _) in enumerate(items) if n == name), len(items))
                items = [item for item in items if item[0] != name]
                if values is not None:  # a text ends with a zero byte, like other taggers do
                    items.insert(at, (name, values[0].encode("utf-8") + b"\0"))
            # With every field removed, the empty chunk stays in its place: undo is then exact.
            _replace_info(f, riff, chunk, b"INFO" + b"".join(_info_item(n, v) for n, v in items))
        return {"chunk": base64.b64encode(before).decode() if before is not None else None}

    @staticmethod
    def undo(path: Path, snapshot: dict) -> None:
        before = snapshot["chunk"]
        with path.open("r+b") as f:
            riff = RiffFile(f)
            data = base64.b64decode(before) if before else None
            _replace_info(f, riff, _info_chunk(riff), data)


def _info_chunk(riff):
    """The LIST chunk holding INFO, or None."""
    return next(
        (c for c in riff.root.subchunks() if c.id == "LIST" and getattr(c, "name", "") == "INFO"),
        None,
    )


def _info_items(data: bytes) -> list[tuple[bytes, bytes]]:
    """The fields in an INFO chunk's data ("INFO" + fields), each with its bytes as stored."""
    items, pos = [], 4
    while pos + 8 <= len(data):
        name, size = struct.unpack("<4sI", data[pos : pos + 8])
        items.append((name, data[pos + 8 : pos + 8 + size]))
        pos += 8 + size + (size & 1)
    return items


def _info_item(name: bytes, value: bytes) -> bytes:
    return struct.pack("<4sI", name, len(value)) + value + b"\0" * (len(value) & 1)


def _replace_info(f, riff, chunk, data: bytes | None) -> None:
    """Put ``data`` into the INFO chunk: resize it, add it at the end, or remove it (None)."""
    if data is None:
        if chunk is not None:
            chunk.delete()
    elif chunk is None:
        # Added as a plain chunk, then named LIST: mutagen would read a new LIST chunk's
        # first bytes before they are written.
        added = riff.root.insert_chunk("JUNK", data)
        f.seek(added.offset)
        f.write(b"LIST")
    else:
        chunk.resize(len(data))
        chunk.write(data)
