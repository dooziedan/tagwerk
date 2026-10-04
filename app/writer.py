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
"""

import base64
import re
from collections.abc import Callable
from enum import Enum
from pathlib import Path

import mutagen
from mutagen._vorbis import VCommentDict
from mutagen.flac import Picture
from mutagen.id3 import ID3, Frames
from mutagen.mp4 import MP4Cover, MP4FreeForm, MP4Tags

from app.images import ImageStore, image_info
from app.keys import display, to_camelot
from app.tags import is_comment_frame

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
MULTI_VALUE = {"artist", "albumartist", "genre"}  # "A; B" is written as two values
COVER = "cover"
# Every field a change can have, with its label: the text fields plus cover art.
LABELS = {**EDITABLE, COVER: "Cover art"}


class WriteError(Exception):
    """A change can't be written, e.g. the format has no tags or the value is invalid."""


# --- Values ---------------------------------------------------------------------------------


def normalize(field: str, value: str | None) -> str | None:
    """Clean and validate a value typed in the form. Returns None to remove the field.

    Raises ValueError with a readable message for values that can't be written.
    """
    if field not in EDITABLE:
        raise ValueError(f"{field} can't be edited")
    value = (value or "").strip()
    if not value:
        return None
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
    return getattr(track, field)


def _number(n: int | None, total: int | None) -> str | None:
    if not n:
        return None
    return f"{n}/{total}" if total else str(n)


def _split(value: str | None) -> list[str]:
    return [p.strip() for p in (value or "").split(";") if p.strip()]


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
    snapshot = handler.write(audio, changes, images)
    return {"system": handler.system, "fields": sorted(changes), **snapshot}


def undo(path: Path, snapshot: dict, images: ImageStore | None = None) -> None:
    """Restore the values captured by write()."""
    audio = mutagen.File(path)
    if audio is None:
        raise WriteError("not a recognized audio file")
    handler = _handler(audio)
    if handler.system != snapshot["system"]:
        raise WriteError("the file's tag format changed since the change was applied")
    handler.undo(audio, snapshot, images)


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
    COVER: lambda f: f.FrameID == "APIC",
}


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
            if any(_ID3_GROUPS[field](f) for field in changes)
        ]
        for field, value in changes.items():
            _ID3._set(tags, field, value, images)
        audio.save(v2_version=version)
        return {"frames": before, "created": created, "version": version}

    @staticmethod
    def _set(tags, field: str, value: str | None, images: ImageStore | None = None) -> None:
        group = _ID3_GROUPS[field]
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
        elif field == "catalognumber":
            tags.add(frames["TXXX"](encoding=3, desc=txxx_desc or "CATALOGNUMBER", text=[value]))
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
    def undo(audio, snapshot: dict, images: ImageStore | None) -> None:
        tags = audio.tags
        if tags is None:
            audio.add_tags()
            tags = audio.tags
        for f in [f for f in tags.values() if any(_ID3_GROUPS[x](f) for x in snapshot["fields"])]:
            del tags[f.HashKey]
        for data in snapshot["frames"]:
            tags.add(_frame_from_json(data, images))
        if snapshot["created"] and not tags:
            audio.delete()  # the file had no ID3 tags before: remove the empty block again
        else:
            audio.save(v2_version=snapshot["version"])


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
}
_VORBIS_NUMBERS = {
    "track": (["tracknumber", "track"], ["tracktotal", "totaltracks"]),
    "disc": (["discnumber", "disc"], ["disctotal", "totaldiscs"]),
}


def _vorbis_keys(field: str) -> list[str]:
    if field == COVER:
        return []  # handled by _Vorbis._write_cover / _undo_cover
    if field in _VORBIS_NUMBERS:
        number, total = _VORBIS_NUMBERS[field]
        return number + total
    return _VORBIS_KEYS[field]


class _Vorbis:
    system = "vorbis"

    @staticmethod
    def write(audio, changes: dict[str, str | None], images: ImageStore | None) -> dict:
        if audio.tags is None:
            audio.add_tags()
        tags = audio.tags
        present = {k.lower() for k in tags.keys()}  # noqa: SIM118
        before = {
            key: list(tags[key])
            for field in changes
            for key in _vorbis_keys(field)
            if key in present
        }
        snapshot: dict = {"values": before}
        for field, value in changes.items():
            if field == COVER:
                snapshot["cover"] = _Vorbis._write_cover(audio, value, images)
            elif field in _VORBIS_NUMBERS:
                _Vorbis._set_number(tags, present, field, value)
            else:
                keys = _VORBIS_KEYS[field]
                target = next((k for k in keys if k in present), keys[0])
                for k in keys:
                    if k in present:
                        del tags[k]
                if value is not None:
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
            for key in _vorbis_keys(field):
                if key in present:
                    del tags[key]
        for key, values in snapshot["values"].items():
            tags[key] = values
        if "cover" in snapshot:
            _Vorbis._undo_cover(audio, snapshot["cover"], images)
        audio.save()


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
    COVER: ["covr"],
}


def _mp4_existing(tags, keys: list[str]) -> list[str]:
    """Keys present in the file, matching freeform names case-insensitively."""
    wanted = {k.lower() for k in keys}
    return [k for k in tags if k.lower() in wanted]


class _MP4:
    system = "mp4"

    @staticmethod
    def write(audio, changes: dict[str, str | None], images: ImageStore | None) -> dict:
        if audio.tags is None:
            audio.add_tags()
        tags = audio.tags
        before = {}
        for field in changes:
            for key in _mp4_existing(tags, _MP4_KEYS[field]):
                before[key] = [_mp4_value_to_json(v, images) for v in tags[key]]
        for field, value in changes.items():
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
                tags[target] = [MP4FreeForm(value.encode())]
            else:
                tags[target] = _split(value) if field in MULTI_VALUE else [value]
        audio.save()
        return {"values": before}

    @staticmethod
    def undo(audio, snapshot: dict, images: ImageStore | None) -> None:
        tags = audio.tags
        for field in snapshot["fields"]:
            for key in _mp4_existing(tags, _MP4_KEYS[field]):
                del tags[key]
        for key, values in snapshot["values"].items():
            tags[key] = [_mp4_value_from_json(v, images) for v in values]
        audio.save()


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
