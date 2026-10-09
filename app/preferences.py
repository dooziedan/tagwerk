"""User preferences, stored in the database (so they live in /config, the same on every device).

Not to be confused with ``app.config``, which holds the container's environment settings.
"""

import json
from dataclasses import asdict, dataclass, field, fields
from typing import Annotated, Literal

from fastapi import Depends
from sqlmodel import Session, select

from app.db import SessionDep
from app.keys import NOTATIONS
from app.models import AppSetting

# The night-sky look (ADR 0021): full effects, or lighter ones for weak devices.
EFFECTS = {
    "full": "Full",
    "light": "Lighter",
}

# Where imported tracks go (only folders: filenames never change on import).
LAYOUTS = {
    "genre": "Genre folders",
    "artist": "Artist folders",
    "date": "Date added",
    "custom": "Own pattern",
}
# How independently Tagwerk handles the inbox (ADR 0007).
AUTOMATIONS = {
    "ask": "Always ask",
    "auto": "Import complete tracks automatically",
}

KeyNotation = Literal["camelot", "openkey", "musical"]
Effects = Literal["full", "light"]


@dataclass
class Preferences:
    key_notation: KeyNotation = "camelot"
    # MusicBrainz IDs are irrelevant for edits, bootlegs and promos, so they're opt-in.
    show_musicbrainz: bool = False
    # Look (docs/design.md): "light" turns off blur, star drift and glows for weak devices.
    # (Old databases may still hold "style"/"appearance" rows: load() ignores unknown keys.)
    effects: Effects = "full"
    # Set once the owner confirmed having a backup, before the very first write to files.
    backup_confirmed: bool = False
    # The setup wizard was completed (or skipped); until then the start page leads there.
    setup_done: bool = False

    # Import (wizard step 3/4, Settings → Import)
    folder_layout: str = "genre"
    folder_pattern: str = "{genre}"  # for the "custom" layout; folders only
    genre_folders: list[str] = field(default_factory=list)  # empty: the existing folders
    # Main genres the owner keeps in _Unsorted: no new folder is proposed for them.
    kept_unsorted: list[str] = field(default_factory=list)
    automation: str = "ask"
    # Remove Traktor's private data (PRIV:TRAKTOR4) from files while importing (ADR 0016).
    remove_traktor_on_import: bool = False
    # The genre map (app/genres.py) as plain text; empty: the built-in one.
    genre_map: str = ""

    # Online identification (Settings → Online lookups, app/identify.py): which sources to ask.
    online_sources: list[str] = field(
        default_factory=lambda: ["acoustid", "musicbrainz", "discogs", "deezer", "itunes"]
    )

    # Final tracks (wizard step 5, Settings → Final tracks): rename when marked final.
    rename_on_final: bool = False
    filename_pattern: str = "{artist} - {title}"


def load(session: Session) -> Preferences:
    stored = {row.key: json.loads(row.value) for row in session.exec(select(AppSetting))}
    prefs = Preferences()
    for f in fields(Preferences):
        if f.name in stored:
            setattr(prefs, f.name, stored[f.name])
    return _validated(prefs)


def save(session: Session, prefs: Preferences) -> Preferences:
    prefs = _validated(prefs)
    for name, value in asdict(prefs).items():
        session.merge(AppSetting(key=name, value=json.dumps(value)))
    session.commit()
    return prefs


def _validated(prefs: Preferences) -> Preferences:
    """Fall back to defaults for unknown values (e.g. from a newer or older version)."""
    default = Preferences()
    if prefs.key_notation not in NOTATIONS:
        prefs.key_notation = default.key_notation
    prefs.show_musicbrainz = bool(prefs.show_musicbrainz)
    prefs.backup_confirmed = bool(prefs.backup_confirmed)
    if prefs.effects not in EFFECTS:
        prefs.effects = default.effects
    for flag in ("setup_done", "rename_on_final"):
        setattr(prefs, flag, bool(getattr(prefs, flag)))
    if prefs.folder_layout not in LAYOUTS:
        prefs.folder_layout = default.folder_layout
    if prefs.automation not in AUTOMATIONS:
        prefs.automation = default.automation
    for names in ("genre_folders", "kept_unsorted", "online_sources"):
        value = getattr(prefs, names)
        value = value if isinstance(value, list) else []
        setattr(prefs, names, [str(g).strip() for g in value if str(g).strip()])
    for text in ("folder_pattern", "filename_pattern", "genre_map"):
        setattr(prefs, text, str(getattr(prefs, text) or ""))
    prefs.folder_pattern = prefs.folder_pattern.strip() or default.folder_pattern
    prefs.filename_pattern = prefs.filename_pattern.strip() or default.filename_pattern
    return prefs


def get_preferences(session: SessionDep) -> Preferences:
    return load(session)


PreferencesDep = Annotated[Preferences, Depends(get_preferences)]
