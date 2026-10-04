"""Cover art for display: embedded in the file, or an image file next to it. Read-only."""

import base64
from pathlib import Path

import mutagen
from mutagen.flac import FLAC, Picture
from mutagen.id3 import ID3
from mutagen.mp4 import MP4Cover, MP4Tags

# Image files next to a track that count as its cover, in order of preference.
SIDECAR_NAMES = ("cover", "folder", "front", "album")
SIDECAR_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


def find_cover(path: Path) -> tuple[bytes, str] | None:
    """(image bytes, MIME type) of a track's cover, or None."""
    try:
        embedded = _embedded(path)
    except Exception:  # an unreadable file simply has no cover to show
        embedded = None
    return embedded or _sidecar(path)


def _embedded(path: Path) -> tuple[bytes, str] | None:
    audio = mutagen.File(path)
    if audio is None:
        return None
    if isinstance(audio, FLAC) and audio.pictures:
        return _best_picture(audio.pictures)
    tags = audio.tags
    if isinstance(tags, ID3):
        frames = tags.getall("APIC")
        if frames:
            front = [f for f in frames if f.type == 3] or frames  # 3 = front cover
            return front[0].data, front[0].mime or "image/jpeg"
    elif isinstance(tags, MP4Tags) and tags.get("covr"):
        cover = tags["covr"][0]
        mime = "image/png" if cover.imageformat == MP4Cover.FORMAT_PNG else "image/jpeg"
        return bytes(cover), mime
    elif tags is not None and "metadata_block_picture" in tags:  # OGG / Opus
        pictures = [Picture(base64.b64decode(v)) for v in tags["metadata_block_picture"]]
        return _best_picture(pictures)
    return None


def _best_picture(pictures: list[Picture]) -> tuple[bytes, str]:
    front = [p for p in pictures if p.type == 3] or pictures
    return front[0].data, front[0].mime or "image/jpeg"


def _sidecar(path: Path) -> tuple[bytes, str] | None:
    try:
        candidates = {p.name.lower(): p for p in path.parent.iterdir() if p.is_file()}
    except OSError:
        return None
    for name in SIDECAR_NAMES:
        for suffix, mime in SIDECAR_TYPES.items():
            found = candidates.get(name + suffix)
            if found:
                return found.read_bytes(), mime
    return None
