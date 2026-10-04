"""Carry all tags of a file over to ID3, for converting a track to AIFF (app/convert.py).

AIFF stores its tags as ID3. This module only *builds* the ID3 frames from the source file;
writing them is app/writer.py's job (CLAUDE.md). Sources:
- **ID3** (WAV with an ID3 chunk): every frame is copied unchanged.
- **Vorbis comments** (FLAC): mapped like MusicBrainz Picard does (``title`` → TIT2,
  ``musicbrainz_trackid`` → UFID, ``replaygain_track_gain`` → TXXX:REPLAYGAIN_TRACK_GAIN, …).
  Any other key becomes a TXXX frame with the key's name, so nothing is dropped.
- **MP4 atoms** (ALAC in .m4a): mapped the same way;
  freeform ``----:com.apple.iTunes:NAME`` atoms are treated like the Vorbis key NAME.
- **RIFF INFO** (WAV without ID3): its few fields (title, artist, album, …).
All pictures are copied with their type (front cover, back cover, …) and description.
"""

import base64
from pathlib import Path

import mutagen
from mutagen.flac import Picture
from mutagen.id3 import (
    APIC,
    COMM,
    ID3,
    TXXX,
    UFID,
    USLT,
    Frames,
)
from mutagen.mp4 import MP4, MP4Cover

# Vorbis key → ID3 text frame (Picard's mapping for ID3v2.4).
_TEXT = {
    "title": "TIT2", "artist": "TPE1", "album": "TALB", "albumartist": "TPE2",
    "album artist": "TPE2", "album_artist": "TPE2", "date": "TDRC", "year": "TDRC",
    "originaldate": "TDOR", "genre": "TCON", "bpm": "TBPM", "tempo": "TBPM",
    "initialkey": "TKEY", "initial_key": "TKEY", "key": "TKEY", "label": "TPUB",
    "organization": "TPUB", "publisher": "TPUB", "composer": "TCOM", "lyricist": "TEXT",
    "conductor": "TPE3", "remixer": "TPE4", "copyright": "TCOP", "encodedby": "TENC",
    "encodersettings": "TSSE", "encoder": "TSSE", "isrc": "TSRC", "grouping": "TIT1",
    "subtitle": "TIT3", "mood": "TMOO", "language": "TLAN", "media": "TMED",
    "compilation": "TCMP", "albumsort": "TSOA", "artistsort": "TSOP", "titlesort": "TSOT",
    "albumartistsort": "TSO2", "composersort": "TSOC", "discsubtitle": "TSST",
}  # fmt: skip
# Vorbis key → TXXX description (Picard's names).
_TXXX = {
    "musicbrainz_albumid": "MusicBrainz Album Id",
    "musicbrainz_artistid": "MusicBrainz Artist Id",
    "musicbrainz_albumartistid": "MusicBrainz Album Artist Id",
    "musicbrainz_releasegroupid": "MusicBrainz Release Group Id",
    "musicbrainz_releasetrackid": "MusicBrainz Release Track Id",
    "musicbrainz_workid": "MusicBrainz Work Id",
    "releasecountry": "MusicBrainz Album Release Country",
    "releasestatus": "MusicBrainz Album Status",
    "releasetype": "MusicBrainz Album Type",
    "catalognumber": "CATALOGNUMBER",
    "barcode": "BARCODE",
    "asin": "ASIN",
    "script": "SCRIPT",
    "acoustid_id": "Acoustid Id",
    "acoustid_fingerprint": "Acoustid Fingerprint",
}
_NUMBERS = {  # number key, total keys, ID3 frame
    "track": ("tracknumber", ("tracktotal", "totaltracks"), "TRCK"),
    "disc": ("discnumber", ("disctotal", "totaldiscs"), "TPOS"),
}
_SKIP = {"metadata_block_picture", "coverart", "coverartmime", "vendor"}

# MP4 atom → Vorbis key (then mapped like a Vorbis comment).
_MP4 = {
    "\xa9nam": "title", "\xa9ART": "artist", "\xa9alb": "album", "aART": "albumartist",
    "\xa9day": "date", "\xa9gen": "genre", "\xa9wrt": "composer", "\xa9grp": "grouping",
    "\xa9cmt": "comment", "\xa9lyr": "lyrics", "\xa9too": "encoder", "cprt": "copyright",
    "soal": "albumsort", "soar": "artistsort", "sonm": "titlesort", "soaa": "albumartistsort",
    "soco": "composersort",
}  # fmt: skip
# MP4 freeform names that differ from the Vorbis key.
_MP4_FREEFORM = {
    "musicbrainz track id": "musicbrainz_trackid",
    "musicbrainz album id": "musicbrainz_albumid",
    "musicbrainz artist id": "musicbrainz_artistid",
    "musicbrainz album artist id": "musicbrainz_albumartistid",
    "musicbrainz release group id": "musicbrainz_releasegroupid",
    "musicbrainz release track id": "musicbrainz_releasetrackid",
    "musicbrainz work id": "musicbrainz_workid",
    "musicbrainz album release country": "releasecountry",
    "musicbrainz album status": "releasestatus",
    "musicbrainz album type": "releasetype",
    "acoustid id": "acoustid_id",
}
# RIFF INFO chunk id → Vorbis key.
_RIFF = {
    "INAM": "title", "IART": "artist", "IPRD": "album", "ICRD": "date", "IGNR": "genre",
    "ICMT": "comment", "ICOP": "copyright", "ISFT": "encoder", "ITRK": "tracknumber",
    "IPRT": "tracknumber",
}  # fmt: skip


def id3_frames(source: Path, riff_info: dict[bytes, str] | None = None) -> list:
    """All tags and pictures of ``source`` as ID3 frames."""
    audio = mutagen.File(source)
    if audio is None:
        raise ValueError("not a recognized audio file")
    tags = audio.tags
    if isinstance(tags, ID3):
        return list(tags.values())  # WAV with ID3: nothing to translate
    if isinstance(audio, MP4):
        values, pictures = _from_mp4(audio)
    elif tags is not None and hasattr(tags, "as_dict"):
        values = {k.lower(): list(v) for k, v in tags.as_dict().items()}
        pictures = list(getattr(audio, "pictures", [])) + _ogg_pictures(values)
    else:
        values, pictures = _from_riff(riff_info or {}), []
    return _frames(values) + _apics(pictures)


def _frames(values: dict[str, list[str]]) -> list:
    frames = []
    used = set(_SKIP)
    for number, totals, frame_id in _NUMBERS.values():
        n = next(iter(values.get(number, [])), "")
        total = next((values[t][0] for t in totals if values.get(t)), "")
        if n and total and "/" not in n:
            n = f"{n}/{total}"
        if n:
            frames.append(Frames[frame_id](encoding=3, text=[n]))
        used.update((number, *totals))
    for key, texts in values.items():
        texts = [t for t in texts if str(t).strip()]
        if key in used or not texts:
            continue
        used.add(key)
        if key in _TEXT:
            if key in ("bpm", "tempo"):
                texts = [str(round(float(texts[0])))] if _is_number(texts[0]) else texts
            frames.append(Frames[_TEXT[key]](encoding=3, text=texts))
        elif key in ("comment", "description"):
            frames.append(COMM(encoding=3, lang="eng", desc="", text=texts))
        elif key in ("lyrics", "unsyncedlyrics"):
            frames.append(USLT(encoding=3, lang="eng", desc="", text="\n".join(texts)))
        elif key == "musicbrainz_trackid":
            frames.append(UFID(owner="http://musicbrainz.org", data=texts[0].encode()))
        elif key.startswith("replaygain_"):
            frames.append(TXXX(encoding=3, desc=key.upper(), text=texts))
        else:
            frames.append(TXXX(encoding=3, desc=_TXXX.get(key, key.upper()), text=texts))
    return _merge_text_frames(frames)


def _merge_text_frames(frames: list) -> list:
    """Two keys for the same frame (e.g. "label" and "publisher"): keep the first."""
    seen, result = set(), []
    for frame in frames:
        if frame.HashKey in seen:
            continue
        seen.add(frame.HashKey)
        result.append(frame)
    return result


def _from_mp4(audio: MP4) -> tuple[dict[str, list[str]], list]:
    values: dict[str, list[str]] = {}
    pictures = []
    for atom, items in (audio.tags or {}).items():
        if atom == "covr":
            pictures = [_mp4_picture(c) for c in items]
        elif atom in ("trkn", "disk"):
            number, total = items[0] if items else (0, 0)
            prefix = "track" if atom == "trkn" else "disc"
            if number:
                values[f"{prefix}number"] = [str(number)]
            if total:
                values[f"{prefix}total"] = [str(total)]
        elif atom == "tmpo":
            values["bpm"] = [str(items[0])] if items else []
        elif atom == "cpil":
            values["compilation"] = ["1" if items else "0"]
        elif atom.startswith("----:"):
            name = atom.split(":", 2)[2]
            key = _MP4_FREEFORM.get(name.lower(), name.lower())
            values[key] = [bytes(v).decode("utf-8", "replace") for v in items]
        elif atom in _MP4:
            values[_MP4[atom]] = [str(v) for v in items]
        else:
            values[atom.lower()] = [str(v) for v in items if not isinstance(v, bytes)]
    return values, pictures


def _from_riff(info: dict[bytes, str]) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for chunk, text in info.items():
        key = _RIFF.get(chunk.decode("ascii", "replace"))
        if key and text.strip():
            values.setdefault(key, [text.strip()])
    return values


def _ogg_pictures(values: dict[str, list[str]]) -> list:
    pictures = []
    for encoded in values.get("metadata_block_picture", []):
        try:
            pictures.append(Picture(base64.b64decode(encoded)))
        except (ValueError, TypeError):
            continue  # a broken picture block is left out, not fatal
    return pictures


def _mp4_picture(cover: MP4Cover) -> Picture:
    picture = Picture()
    picture.type = 3  # MP4 has no picture types: front cover
    picture.mime = "image/png" if cover.imageformat == MP4Cover.FORMAT_PNG else "image/jpeg"
    picture.data = bytes(cover)
    return picture


def _apics(pictures: list[Picture]) -> list[APIC]:
    """ID3 tells pictures apart by their description: repeats get " (2)", " (3)", …"""
    frames, seen = [], set()
    for picture in pictures:
        desc = picture.desc or ""
        n = 1
        while desc in seen:
            n += 1
            desc = f"{picture.desc or ''} ({n})".strip()
        seen.add(desc)
        mime = picture.mime or "image/jpeg"
        frames.append(APIC(encoding=3, mime=mime, type=picture.type, desc=desc, data=picture.data))
    return frames


def _is_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True
