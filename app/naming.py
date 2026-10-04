"""Folder and filename patterns: where an imported track goes, and the name of a final track.

Patterns use placeholders in braces, e.g. ``{artist} - {title} [{bpm} {key}]``:
- a part in brackets ``[...]`` or ``(...)`` disappears when all its placeholders are empty,
  so a track without BPM/key becomes "Artist - Title", not "Artist - Title [ ]";
- characters that Windows/SMB shares don't allow in names are replaced by "-";
- folder patterns may contain "/" for subfolders; an empty folder becomes "_Unsorted".

Import only chooses the **folder**; the filename stays as it arrived. The filename pattern is
used only when the owner marks a track as final and has switched renaming on (CLAUDE.md).

Genre folders are never created without the owner's OK (ADR 0010): a track whose main genre
has no folder yet goes to ``_Unsorted``, and the Changes page proposes the new folder
(app/folders.py).
"""

import re
from datetime import datetime
from pathlib import Path

from app.genres import GenreMap
from app.keys import display, to_camelot

UNSORTED = "_Unsorted"
PLACEHOLDERS = {
    "artist": "Artist",
    "title": "Title",
    "bpm": "BPM",
    "key": "Key",
    "genre": "Main genre",
    "label": "Label",
    "year": "Year",
    "album": "Album",
    "albumartist": "Album artist",
    "track": "Track number",
    "catalognumber": "Catalog number",
}
FOLDER_PLACEHOLDERS = {"genre", "artist", "albumartist", "label", "year", "added_year",
                       "added_month"}  # fmt: skip
_FIELD = re.compile(r"\{(\w+)\}")
_GROUP = re.compile(r"\[[^\[\]]*\]|\([^()]*\)")
_FORBIDDEN = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
# How those characters are written instead: readable, and allowed on every share.
_REPLACE = {":": " -", "?": "", "*": "", '"': "'", "/": "-", "\\": "-", "<": "", ">": "", "|": "-"}


def _safe(text: str) -> str:
    return _FORBIDDEN.sub(lambda m: _REPLACE.get(m.group(0), ""), text)


class PatternError(ValueError):
    """A pattern with unknown placeholders."""


def check(pattern: str, folders: bool = False) -> None:
    allowed = FOLDER_PLACEHOLDERS if folders else set(PLACEHOLDERS)
    unknown = [f for f in _FIELD.findall(pattern) if f not in allowed]
    if unknown:
        names = ", ".join("{" + f + "}" for f in sorted(allowed))
        raise PatternError(f"Unknown: {', '.join('{' + u + '}' for u in unknown)}. Use {names}.")
    if not _FIELD.search(pattern):
        raise PatternError("The pattern needs at least one placeholder, e.g. {artist}.")


def render(pattern: str, values: dict[str, str | None]) -> str:
    """One name (no "/"): placeholders filled, empty bracket parts removed, made file-safe."""

    def group(match: re.Match) -> str:
        names = _FIELD.findall(match.group(0))
        if names and not any(values.get(n) for n in names):
            return ""  # every placeholder in it is empty
        return match.group(0)

    text = _GROUP.sub(group, pattern)
    text = _FIELD.sub(lambda m: _safe(str(values.get(m.group(1)) or "")), text)
    text = _safe(text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"(\s-\s*)+(?=\s-\s)", "", text)  # "A -  - B" -> "A - B"
    return text.strip(" -_.,")


def values_for(track_values: dict[str, str | None], genres: GenreMap, notation: str,
               added: datetime | None = None) -> dict[str, str | None]:  # fmt: skip
    """Placeholder values from a track's tag values (as in the edit form)."""
    artist = (track_values.get("artist") or "").split(";")[0].strip() or None
    bpm = track_values.get("bpm")
    key = track_values.get("key")
    date = track_values.get("date") or ""
    added = added or datetime.now()
    return {
        "artist": artist,
        "title": track_values.get("title"),
        "bpm": f"{round(float(bpm))}" if bpm else None,
        "key": display(to_camelot(key), notation) if key and to_camelot(key) else key,
        "genre": main_genre(track_values.get("genre"), genres),
        "label": track_values.get("label"),
        "year": date[:4] if date[:4].isdigit() else None,
        "album": track_values.get("album"),
        "albumartist": (track_values.get("albumartist") or "").split(";")[0].strip() or artist,
        "track": (track_values.get("track") or "").split("/")[0] or None,
        "catalognumber": track_values.get("catalognumber"),
        "added_year": f"{added:%Y}",
        "added_month": f"{added:%Y-%m}",
    }


def main_genre(genre: str | None, genres: GenreMap) -> str | None:
    """The main genre of a genre tag: "Liquid; Vocal" -> "Drum & Bass"."""
    tidy = genres.tidy((genre or "").split(";"))
    return tidy[0] if tidy else None


def existing_folders(music_dir: Path) -> list[str]:
    """The folders at the top of the library (not hidden ones, not _Unsorted)."""
    try:
        return sorted(p.name for p in music_dir.iterdir()
                      if p.is_dir() and not p.name.startswith((".", "_")))  # fmt: skip
    except OSError:
        return []


def genre_folder(genre: str | None, allowed: list[str]) -> str | None:
    """The folder for a main genre, spelled as in ``allowed``; None when it has none yet."""
    wanted = _safe(genre or "").strip(" .").lower()
    return next((a for a in allowed if wanted and _safe(a).strip(" .").lower() == wanted), None)


def folder(layout: str, pattern: str, values: dict[str, str | None], genre_folders: list[str],
           existing: list[str] = ()) -> str:  # fmt: skip
    """The library folder for an imported track, relative to MUSIC_DIR.

    Genre layout: only folders the owner chose: the ticked main genres or, with none ticked,
    the genre folders already in the library (``existing``). Anything else -> _Unsorted.
    """
    if layout == "genre":
        parts = [genre_folder(values.get("genre"), genre_folders or list(existing)) or ""]
    elif layout == "artist":
        parts = [values.get("artist") or values.get("albumartist") or ""]  # not "Various Artists"
    elif layout == "date":
        parts = [values["added_year"], values["added_month"]]
    else:
        parts = [render(p, values) for p in pattern.split("/")]
    parts = [_safe(p).strip(" .") for p in parts]
    # The first level always exists (_Unsorted if empty); empty subfolders are left out.
    return "/".join([parts[0] or UNSORTED] + [p for p in parts[1:] if p])


def filename(pattern: str, values: dict[str, str | None], suffix: str) -> str:
    """The name of a final track (the extension stays as it is)."""
    return (render(pattern, values) or "Untitled") + suffix
